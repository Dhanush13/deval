"""Exit triggers. Four triggers, evaluated in priority order:

    STOP_LOSS     — adverse move > STOP_LOSS_PCT (non-negotiable; the tweet omits this)
    TARGET_HIT    — at 85% of expected move from entry to target
    VOLUME_EXIT   — 10-min volume > 3 * rolling 1h MEDIAN (median, not mean)
    STALE_THESIS  — 24h elapsed and |price change| < 2%

Returns the first trigger that fires, or None.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .config import CFG


@dataclass
class ExitInputs:
    side: str                     # "BUY" or "SELL" (position direction)
    entry_price: float            # filled price
    target_price: float           # expected move target
    current_price: float          # current midpoint
    hours_since_entry: float
    volume_10m: float
    volume_1h_history: list[float]  # recent 10-min-window totals for rolling 1h median


def check_exit(e: ExitInputs) -> str | None:
    # side-aware adverse move
    if e.side.upper() == "BUY":
        adverse_pct = max(0.0, (e.entry_price - e.current_price) / max(e.entry_price, 1e-9))
        target_progress = (e.current_price - e.entry_price) / max(e.target_price - e.entry_price, 1e-9)
    else:  # SELL / short
        adverse_pct = max(0.0, (e.current_price - e.entry_price) / max(e.entry_price, 1e-9))
        target_progress = (e.entry_price - e.current_price) / max(e.entry_price - e.target_price, 1e-9)

    if adverse_pct >= CFG.stop_loss_pct:
        return "STOP_LOSS"

    if target_progress >= CFG.exit_target_fraction:
        return "TARGET_HIT"

    if e.volume_1h_history:
        med = statistics.median(e.volume_1h_history)
        if med > 0 and e.volume_10m > med * CFG.exit_volume_mult:
            return "VOLUME_EXIT"

    if e.hours_since_entry >= CFG.exit_stale_hours:
        move = abs(e.current_price - e.entry_price)
        if move < CFG.exit_stale_move:
            return "STALE_THESIS"

    return None
