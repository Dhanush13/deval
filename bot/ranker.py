"""Select target wallets to copy-trade.

Unlike the tweet's naive query, we:
  1. Reconstruct realized PnL via FIFO (since the CSV has no profit column).
  2. Split the trade history 80/20 into in-sample (IS) and out-of-sample (OOS).
  3. Require the wallet to be profitable with >= 65% win rate in the OOS window,
     and to have at least MIN_IS_TRADES total closed events in-sample.
  4. Optionally filter to a category (e.g. "crypto") — the tweet's own Day-7 retro
     shows sports wallets have ~52% OOS win rate and should be excluded.

Returns JSON-serialisable list of dicts sorted by OOS realized PnL desc.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

from .pnl import reconcile, win_rate

MIN_IS_CLOSED_EVENTS = 100
MIN_OOS_CLOSED_EVENTS = 20
MIN_OOS_WIN_RATE = 0.65
TOP_N = 20


@dataclass
class Target:
    wallet: str
    is_pnl: float
    oos_pnl: float
    is_trades: int
    oos_trades: int
    is_win_rate: float
    oos_win_rate: float
    score: float  # OOS PnL, tie-break by OOS win rate


def _split(trades: list[Mapping], oos_fraction: float = 0.2) -> tuple[list[Mapping], list[Mapping]]:
    """Split globally by timestamp so all wallets see the same temporal cutoff."""
    if not trades:
        return [], []
    ordered = sorted(trades, key=lambda t: t["ts"])
    n = len(ordered)
    cut_idx = max(1, int(n * (1 - oos_fraction)))
    return ordered[:cut_idx], ordered[cut_idx:]


def rank(
    trades: Iterable[Mapping],
    *,
    category_filter: str | None = None,
    market_categories: Mapping[str, str] | None = None,
    top_n: int = TOP_N,
) -> list[dict]:
    """Rank wallets. `market_categories` maps market_id -> category ("crypto", …)."""
    all_trades = list(trades)

    if category_filter and market_categories is not None:
        allowed = {mid for mid, cat in market_categories.items() if cat == category_filter}
        all_trades = [t for t in all_trades if t["market_id"] in allowed]

    is_trades, oos_trades = _split(all_trades)
    is_stats = reconcile(is_trades)
    oos_stats = reconcile(oos_trades)

    targets: list[Target] = []
    for wallet, is_s in is_stats.items():
        if is_s.closed_events < MIN_IS_CLOSED_EVENTS:
            continue
        oos_s = oos_stats.get(wallet)
        if oos_s is None or oos_s.closed_events < MIN_OOS_CLOSED_EVENTS:
            continue
        if win_rate(oos_s) < MIN_OOS_WIN_RATE:
            continue
        if oos_s.realized_pnl <= 0:
            continue

        targets.append(
            Target(
                wallet=wallet,
                is_pnl=round(is_s.realized_pnl, 2),
                oos_pnl=round(oos_s.realized_pnl, 2),
                is_trades=is_s.closed_events,
                oos_trades=oos_s.closed_events,
                is_win_rate=round(win_rate(is_s), 4),
                oos_win_rate=round(win_rate(oos_s), 4),
                score=round(oos_s.realized_pnl, 2),
            )
        )

    targets.sort(key=lambda t: (t.score, t.oos_win_rate), reverse=True)
    return [asdict(t) for t in targets[:top_n]]
