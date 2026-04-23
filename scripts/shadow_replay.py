"""Replay the last N days of target-wallet fills against the copy strategy, using
historical trades.csv to simulate exits. Produces a go/no-go report.

Every signal is evaluated as if the bot were live; we assume fills at
(whale_price + 1¢) and simulate the exit triggers deterministically against the
recorded trade tape. No network calls; no Claude API calls.

Usage:
    uv run python scripts/shadow_replay.py --days 30 --fees-bps 200
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import CFG
from bot.exit import ExitInputs, check_exit


def _load_normalized(csv: Path) -> pl.DataFrame:
    df = pl.read_csv(csv)
    side = next((c for c in ("side", "direction", "buy_or_sell") if c in df.columns), None)
    if side is None:
        sys.exit("trades.csv lacks a side column; run normalize_goldsky first")
    return df.select(
        [
            pl.col("maker").alias("wallet"),
            pl.col("market_id"),
            pl.col("timestamp").alias("ts"),
            pl.col(side).str.to_uppercase().alias("side"),
            pl.col("token_amount").alias("size"),
            pl.col("price"),
        ]
    ).sort("ts")


def _simulate_exit(
    entry_ts: int,
    entry_price: float,
    target_price: float,
    side: str,
    subsequent: Iterable[dict],
    hour_s: int = 3600,
) -> tuple[str, float, int]:
    """Walk forward through market trades; first exit trigger wins. Returns
    (reason, exit_price, exit_ts). Falls back to holding through the last observed
    trade if no trigger fires."""
    vol_hist: list[float] = []
    bucket_start = entry_ts
    bucket_vol = 0.0
    last_price = entry_price
    last_ts = entry_ts

    for trade in subsequent:
        t_ts = int(trade["ts"])
        t_price = float(trade["price"])
        t_size = float(trade["size"])

        # bucket volume in 10-minute windows
        while t_ts - bucket_start >= 600:
            vol_hist.append(bucket_vol)
            if len(vol_hist) > 6:
                del vol_hist[:-6]
            bucket_start += 600
            bucket_vol = 0.0

        bucket_vol += t_size
        last_price = t_price
        last_ts = t_ts

        hours_since = (t_ts - entry_ts) / 3600.0
        reason = check_exit(ExitInputs(
            side=side,
            entry_price=entry_price,
            target_price=target_price,
            current_price=t_price,
            hours_since_entry=hours_since,
            volume_10m=bucket_vol,
            volume_1h_history=vol_hist[-6:],
        ))
        if reason is not None:
            return reason, t_price, t_ts

    return "MARK_LAST", last_price, last_ts


def _pnl_bps(entry: float, exit_: float, side: str, fees_bps: float) -> float:
    if side == "BUY":
        gross_pct = (exit_ - entry) / entry
    else:
        gross_pct = (entry - exit_) / entry
    return gross_pct * 10_000 - fees_bps


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mu = statistics.mean(returns)
    sd = statistics.pstdev(returns)
    if sd == 0:
        return 0.0
    # Rough Sharpe — no time normalization since each observation is one trade.
    return mu / sd * math.sqrt(len(returns))


def _max_drawdown(cum: list[float]) -> float:
    peak = -math.inf
    dd = 0.0
    for v in cum:
        peak = max(peak, v)
        dd = min(dd, v - peak)
    return -dd  # positive number representing worst drawdown


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=CFG.trades_csv)
    ap.add_argument("--targets", type=Path, default=CFG.targets_json)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--fees-bps", type=float, default=200.0, help="round-trip fee+slippage assumption")
    ap.add_argument("--output", type=Path, default=CFG.log_path.parent / "shadow_report.json")
    args = ap.parse_args()

    if not args.csv.exists():
        sys.exit(f"trades CSV not found: {args.csv}")
    if not args.targets.exists():
        sys.exit(f"targets.json not found: {args.targets}. Run scripts/rank_wallets.py first.")

    targets = {r["wallet"].lower(): r for r in json.loads(args.targets.read_text())}
    df = _load_normalized(args.csv)

    # Filter to last N days
    max_ts = int(df["ts"].max())
    min_ts = max_ts - args.days * 86400
    df = df.filter(pl.col("ts") >= min_ts)

    # Pre-index trades per market for forward walk
    market_trades: dict[str, list[dict]] = defaultdict(list)
    for row in df.iter_rows(named=True):
        market_trades[row["market_id"]].append(row)
    for trades in market_trades.values():
        trades.sort(key=lambda t: t["ts"])

    # Iterate whale fills (only rows where wallet is in targets)
    target_rows = df.filter(pl.col("wallet").str.to_lowercase().is_in(list(targets))).to_dicts()

    results: list[dict] = []
    for fill in target_rows:
        whale_ts = int(fill["ts"])
        whale_price = float(fill["price"])
        side = fill["side"]
        tid = fill["market_id"]

        # simulate entry at whale_price + 1¢
        entry_price = min(0.99, whale_price + 0.01) if side == "BUY" else max(0.01, whale_price - 0.01)
        target_price = min(0.99, entry_price + 0.15) if side == "BUY" else max(0.01, entry_price - 0.15)

        subsequent = [t for t in market_trades.get(tid, []) if t["ts"] > whale_ts]
        reason, exit_price, exit_ts = _simulate_exit(
            whale_ts, entry_price, target_price, side, subsequent
        )
        pnl_bps = _pnl_bps(entry_price, exit_price, side, args.fees_bps)
        results.append({
            "wallet": fill["wallet"],
            "market_id": tid,
            "entry_ts": whale_ts,
            "exit_ts": exit_ts,
            "entry_price": round(entry_price, 4),
            "exit_price": round(exit_price, 4),
            "side": side,
            "exit_reason": reason,
            "pnl_bps": round(pnl_bps, 2),
        })

    returns = [r["pnl_bps"] for r in results]
    cum = []
    running = 0.0
    for r in returns:
        running += r
        cum.append(running)

    hit_rate = sum(1 for r in returns if r > 0) / len(returns) if returns else 0.0
    report = {
        "n_trades": len(results),
        "hit_rate": round(hit_rate, 4),
        "mean_pnl_bps": round(statistics.mean(returns), 2) if returns else 0,
        "median_pnl_bps": round(statistics.median(returns), 2) if returns else 0,
        "total_pnl_bps": round(sum(returns), 2),
        "sharpe": round(_sharpe(returns), 3),
        "max_drawdown_bps": round(_max_drawdown(cum), 2),
        "days_covered": args.days,
        "fees_bps_assumed": args.fees_bps,
        "exit_reason_counts": {k: sum(1 for r in results if r["exit_reason"] == k) for k in {"STOP_LOSS", "TARGET_HIT", "VOLUME_EXIT", "STALE_THESIS", "MARK_LAST"}},
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"summary": report, "trades": results[:500]}, indent=2))
    print(json.dumps(report, indent=2))

    # go-live gate
    if report["sharpe"] >= 1.5 and report["max_drawdown_bps"] <= 1500 and report["mean_pnl_bps"] > 0:
        print("GO-LIVE GATE: PASS")
        return 0
    print("GO-LIVE GATE: FAIL (Sharpe >= 1.5 AND max_dd <= 1500bps AND mean > 0 required)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
