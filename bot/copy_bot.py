"""Single async loop. Polls whale fills, applies risk gates, places orders,
monitors exits.

Run with:
    DRY_RUN=true uv run python -m bot.copy_bot

Loop cadence:
    - whale feed poll: every 5s
    - exit check:      every 30s
"""

from __future__ import annotations

import asyncio
import json
import signal
import time
from pathlib import Path
from typing import Any

from . import positions, risk, sizing
from .clob import Clob
from .config import CFG
from .exit import ExitInputs, check_exit
from .gamma import Market, list_markets
from .logging_ import log
from .whale_feed import GoldskyWhaleFeed, StubWhaleFeed, WhaleFeed, WhaleFill

POLL_WHALE_S = 5.0
POLL_EXIT_S = 30.0


def _load_targets() -> dict[str, dict]:
    path = CFG.targets_json
    if not path.exists():
        log("targets.missing", path=str(path))
        return {}
    rows = json.loads(path.read_text())
    return {r["wallet"].lower(): r for r in rows}


def _build_market_index(markets: list[Market]) -> dict[str, Market]:
    idx: dict[str, Market] = {}
    for m in markets:
        for tid in m.token_ids:
            idx[tid] = m
    return idx


async def _poll_whales(
    feed: WhaleFeed,
    wallets: list[str],
    last_seen_ts: int,
) -> tuple[list[WhaleFill], int]:
    loop = asyncio.get_running_loop()
    fills = await loop.run_in_executor(None, feed.poll, wallets, last_seen_ts)
    if fills:
        last_seen_ts = max(f.ts for f in fills)
    return fills, last_seen_ts


async def _maybe_enter(
    fill: WhaleFill,
    clob: Clob,
    conn,
    markets_idx: dict[str, Market],
    targets: dict[str, dict],
) -> None:
    tid = fill.token_id
    market = markets_idx.get(tid)
    if market is None:
        log("enter.skip", reason="unknown_market", token_id=tid)
        return

    hours = market.hours_to_resolution()
    if hours is not None and (hours < CFG.hours_min or hours > CFG.hours_max):
        log("enter.skip", reason="hours_out_of_band", token_id=tid, hours=hours)
        return

    # Wait configured delay (mimics the tweet's 60s copy delay) before querying the
    # current midpoint, to allow the market to settle.
    await asyncio.sleep(CFG.whale_copy_delay_s)

    loop = asyncio.get_running_loop()
    try:
        mid = await loop.run_in_executor(None, clob.midpoint, tid)
    except Exception as exc:
        log("enter.midpoint_error", token_id=tid, err=str(exc))
        return

    # Reject if midpoint has drifted away from the whale's fill by more than the cap
    drift = abs(mid - fill.price)
    if drift > CFG.whale_price_drift_max:
        log("enter.skip", reason="price_drift", token_id=tid, mid=mid, whale_px=fill.price)
        return

    # Size
    target = targets.get(fill.whale.lower(), {})
    p_win = float(target.get("oos_win_rate") or 0.6)
    entry_price = round(mid + 0.01, 3)  # 1¢ slippage budget

    bankroll, peak = _compute_bankroll(conn)
    size_usd = sizing.kelly_size(p_win=p_win, market_price=entry_price, bankroll_usd=bankroll)
    if size_usd <= 0:
        log("enter.skip", reason="sizing_zero", token_id=tid, p_win=p_win, px=entry_price)
        return

    state = risk.AccountState(
        bankroll_usd=bankroll,
        peak_bankroll_usd=peak,
        realized_pnl_today_usd=positions.realized_pnl_since(conn, time.time() - 86400),
        open_positions=len(positions.open_intents(conn)),
        exposure_per_event_usd=positions.exposure_by_event(conn),
        cash_available_usd=bankroll,  # conservative — treats bankroll as all cash
    )
    decision = risk.check(state, size_usd, market.event_id)
    if not decision.allowed:
        log("enter.blocked", reason=decision.block.value, token_id=tid, size=size_usd)
        return

    token_qty = round(decision.size_usd / entry_price, 2)
    target_px = round(min(0.99, entry_price + 0.15), 3)  # default 15¢ expected move
    intent = positions.record_intent(
        conn,
        token_id=tid,
        event_id=market.event_id,
        side=fill.side,
        size_usd=decision.size_usd,
        entry_price=entry_price,
        target_price=target_px,
    )
    log("enter.intent", signal_uuid=intent.signal_uuid, token_id=tid, size=decision.size_usd, entry=entry_price, target=target_px)

    try:
        result = await loop.run_in_executor(
            None,
            lambda: clob.place_limit(tid, fill.side, entry_price, token_qty),
        )
    except Exception as exc:
        positions.mark_canceled(conn, intent.signal_uuid)
        log("enter.place_error", signal_uuid=intent.signal_uuid, err=str(exc))
        return

    if result.placed:
        positions.mark_filled(conn, intent.signal_uuid, result.order_id)
    elif result.note == "DRY_RUN":
        positions.mark_filled(conn, intent.signal_uuid, order_id=None)
    else:
        positions.mark_canceled(conn, intent.signal_uuid)


def _compute_bankroll(conn) -> tuple[float, float]:
    base = CFG.bankroll_usd
    realized_total = conn.execute(
        "SELECT COALESCE(SUM(realized_pnl), 0.0) AS pnl FROM intents WHERE status='CLOSED'"
    ).fetchone()["pnl"]
    cur = base + float(realized_total or 0.0)
    peak = positions.peak_bankroll(conn, base)
    return cur, max(peak, cur)


async def _exit_loop(clob: Clob, conn) -> None:
    loop = asyncio.get_running_loop()
    # Simple rolling volume window per token_id held in memory
    vol_history: dict[str, list[float]] = {}
    while True:
        try:
            intents = [i for i in positions.open_intents(conn) if i.status == "FILLED"]
            for intent in intents:
                try:
                    current = await loop.run_in_executor(None, clob.midpoint, intent.token_id)
                    book = await loop.run_in_executor(None, clob.book, intent.token_id)
                except Exception as exc:
                    log("exit.midpoint_error", signal_uuid=intent.signal_uuid, err=str(exc))
                    continue

                vol_10m = _estimate_recent_volume(book)
                hist = vol_history.setdefault(intent.token_id, [])
                hist.append(vol_10m)
                if len(hist) > 6:
                    del hist[:-6]

                inputs = ExitInputs(
                    side=intent.side,
                    entry_price=intent.entry_price,
                    target_price=intent.target_price or intent.entry_price,
                    current_price=current,
                    hours_since_entry=(time.time() - intent.ts) / 3600.0,
                    volume_10m=vol_10m,
                    volume_1h_history=hist[:-1],
                )
                reason = check_exit(inputs)
                if reason is None:
                    continue

                # close: place the opposite side at current midpoint, no waiting
                close_side = "SELL" if intent.side.upper() == "BUY" else "BUY"
                qty = round(intent.size_usd / intent.entry_price, 2)
                try:
                    await loop.run_in_executor(
                        None,
                        lambda: clob.place_limit(intent.token_id, close_side, round(current, 3), qty),
                    )
                except Exception as exc:
                    log("exit.close_error", signal_uuid=intent.signal_uuid, err=str(exc))
                    continue

                realized = _realized_pnl(intent, current)
                positions.mark_closed(conn, intent.signal_uuid, reason, realized)
                log("exit.closed", signal_uuid=intent.signal_uuid, reason=reason, realized_pnl=realized)
        except Exception as exc:  # pragma: no cover
            log("exit.loop_error", err=str(exc))

        await asyncio.sleep(POLL_EXIT_S)


def _estimate_recent_volume(book: dict[str, Any]) -> float:
    """Very rough: sum of top-of-book sizes. Real impl would subscribe to trade tape."""
    try:
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        return float(sum(float(b.get("size", 0)) for b in bids[:3])) + float(
            sum(float(a.get("size", 0)) for a in asks[:3])
        )
    except Exception:
        return 0.0


def _realized_pnl(intent, current_price: float) -> float:
    qty = intent.size_usd / max(intent.entry_price, 1e-9)
    if intent.side.upper() == "BUY":
        return round(qty * (current_price - intent.entry_price), 4)
    return round(qty * (intent.entry_price - current_price), 4)


async def main() -> None:
    targets = _load_targets()
    if not targets:
        log("boot.no_targets")
        return
    wallets = list(targets.keys())
    markets = list_markets(limit=500)
    markets_idx = _build_market_index(markets)
    log("boot", targets=len(targets), markets=len(markets), dry_run=CFG.dry_run)

    clob = Clob()
    conn = positions.connect(CFG.positions_db)
    feed: WhaleFeed = GoldskyWhaleFeed()
    last_seen_ts = int(time.time()) - 300  # start 5 min in the past

    stop = asyncio.Event()

    def _handler(*_: Any) -> None:
        stop.set()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, _handler)

    exit_task = asyncio.create_task(_exit_loop(clob, conn))

    try:
        while not stop.is_set():
            fills, last_seen_ts = await _poll_whales(feed, wallets, last_seen_ts)
            for f in fills:
                asyncio.create_task(_maybe_enter(f, clob, conn, markets_idx, targets))
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_WHALE_S)
            except asyncio.TimeoutError:
                pass
    finally:
        exit_task.cancel()
        conn.close()
        log("shutdown")


if __name__ == "__main__":
    asyncio.run(main())
