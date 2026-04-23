"""Pre-trade risk gates. Each returns a Decision describing whether an intended
order is allowed and why not if blocked.

All checks operate on explicit inputs (no singletons) so tests can drive edge
cases directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .config import CFG


class Block(str, Enum):
    OK = "OK"
    DAILY_LOSS = "DAILY_LOSS_LIMIT_REACHED"
    DRAWDOWN = "MAX_DRAWDOWN_BREACHED"
    POSITION_CAP = "MAX_POSITION_USD_EXCEEDED"
    EVENT_CAP = "MAX_PER_EVENT_USD_EXCEEDED"
    OPEN_CAP = "MAX_OPEN_POSITIONS_REACHED"
    BANKROLL = "INSUFFICIENT_BANKROLL"


@dataclass
class Decision:
    allowed: bool
    block: Block
    size_usd: float


@dataclass
class AccountState:
    bankroll_usd: float            # current bankroll (after realized PnL)
    peak_bankroll_usd: float       # high-water mark
    realized_pnl_today_usd: float  # negative number for losses
    open_positions: int
    exposure_per_event_usd: dict[str, float]
    cash_available_usd: float


def check(
    state: AccountState,
    intended_size_usd: float,
    event_id: str | None,
) -> Decision:
    if intended_size_usd <= 0:
        return Decision(False, Block.POSITION_CAP, 0.0)

    if state.realized_pnl_today_usd <= -abs(CFG.daily_loss_limit_usd):
        return Decision(False, Block.DAILY_LOSS, 0.0)

    if state.peak_bankroll_usd > 0:
        drawdown = 1.0 - (state.bankroll_usd / state.peak_bankroll_usd)
        if drawdown >= CFG.max_drawdown_pct:
            return Decision(False, Block.DRAWDOWN, 0.0)

    if state.open_positions >= CFG.max_open_positions:
        return Decision(False, Block.OPEN_CAP, 0.0)

    size = min(intended_size_usd, CFG.max_position_usd)

    if event_id is not None:
        already = state.exposure_per_event_usd.get(event_id, 0.0)
        headroom = max(0.0, CFG.max_per_event_usd - already)
        if headroom <= 0:
            return Decision(False, Block.EVENT_CAP, 0.0)
        size = min(size, headroom)

    if size > state.cash_available_usd:
        size = state.cash_available_usd
    if size <= 0:
        return Decision(False, Block.BANKROLL, 0.0)

    return Decision(True, Block.OK, round(size, 2))
