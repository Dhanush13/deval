"""Kelly-based position sizing with hard caps.

The full Kelly fraction is f* = (p*b - q) / b, where b = payout_ratio = (1/price - 1),
p = estimated win probability, q = 1 - p.

We deliberately apply KELLY_MULTIPLIER (default 0.25, i.e. quarter-Kelly) as the BASELINE
— not just a cap — because (a) p_win estimates are noisy, (b) multiple agents evaluating
the same market are not independent, (c) full-Kelly volatility wipes retail accounts.
"""

from __future__ import annotations

from .config import CFG


def full_kelly_fraction(p_win: float, market_price: float) -> float:
    """Raw Kelly fraction. Negative EV → 0."""
    if not 0.0 < market_price < 1.0:
        return 0.0
    if not 0.0 <= p_win <= 1.0:
        return 0.0
    b = (1.0 / market_price) - 1.0
    if b <= 0:
        return 0.0
    q = 1.0 - p_win
    f = (p_win * b - q) / b
    return max(0.0, f)


def kelly_size(
    p_win: float,
    market_price: float,
    bankroll_usd: float,
    half_position: bool = False,
) -> float:
    """Dollar size in USDC. Applies quarter-Kelly baseline, KELLY_CAP, MAX_POSITION_USD.

    `half_position=True` halves the result (used when only 1 agent agrees vs. 2+).
    """
    if bankroll_usd <= 0:
        return 0.0
    raw = full_kelly_fraction(p_win, market_price)
    if raw <= 0:
        return 0.0
    scaled = min(raw * CFG.kelly_multiplier, CFG.kelly_cap)
    size = bankroll_usd * scaled
    size = min(size, CFG.max_position_usd)
    if half_position:
        size *= 0.5
    return round(size, 2)
