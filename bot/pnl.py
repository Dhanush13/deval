"""FIFO PnL reconciliation per (wallet, market_id).

poly_data's processed/trades.csv does not carry a realized-profit column; the tweet's
snippet assumes one exists, which is wrong. We reconstruct realized PnL here.

Expected normalized schema (DataFrame or list of dicts):
    wallet     str
    market_id  str      (the token_id on CTF; YES and NO are separate markets)
    ts         int      unix seconds
    side       str      "BUY" | "SELL"  (from wallet's perspective)
    size       float    tokens moved
    price      float    USDC per token (0..1)

Rules:
- BUY adds a lot {size, cost_basis=price} to the wallet's inventory.
- SELL consumes inventory FIFO; realized_pnl += size * (sell_price - lot_cost_basis).
- If SELL > inventory, the excess opens a SHORT lot at that price (rare on Polymarket
  retail but possible via conditional-token mechanics).
- Unrealized positions at cutoff are NOT counted as profit unless `mark_to_final`
  is supplied.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable, Mapping


@dataclass
class Lot:
    size: float
    price: float


@dataclass
class WalletStats:
    wallet: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    realized_pnl: float = 0.0
    # number of *closing* trade events (not opens). Used for win_rate denominator.
    closed_events: int = 0


def reconcile(
    trades: Iterable[Mapping],
    mark_to_final: Mapping[str, float] | None = None,
) -> dict[str, WalletStats]:
    """Return {wallet: WalletStats} with realized PnL from FIFO matching.

    `mark_to_final` optionally maps market_id -> final price. When provided,
    any still-open long/short inventory is marked at that price and its PnL
    folded into `realized_pnl` for ranker convenience. Do not use this for
    out-of-sample evaluation.
    """
    # (wallet, market_id) -> deque of open Lot (positive size = long, negative = short)
    books: dict[tuple[str, str], deque[Lot]] = defaultdict(deque)
    stats: dict[str, WalletStats] = {}

    def get(w: str) -> WalletStats:
        s = stats.get(w)
        if s is None:
            s = WalletStats(wallet=w)
            stats[w] = s
        return s

    # trades must be processed in ts order for FIFO to be meaningful
    sorted_trades = sorted(trades, key=lambda t: (t["wallet"], t["market_id"], t["ts"]))

    for t in sorted_trades:
        w = t["wallet"]
        mid = t["market_id"]
        side = t["side"]
        size = float(t["size"])
        price = float(t["price"])
        if size <= 0:
            continue

        st = get(w)
        st.trades += 1
        book = books[(w, mid)]

        if side == "BUY":
            _consume_short(book, size, price, st)
        elif side == "SELL":
            _consume_long(book, size, price, st)
        else:
            raise ValueError(f"unknown side {side!r}")

    if mark_to_final:
        for (w, mid), book in books.items():
            final = mark_to_final.get(mid)
            if final is None:
                continue
            st = get(w)
            for lot in book:
                st.realized_pnl += lot.size * (final - lot.price) if lot.size > 0 else abs(lot.size) * (lot.price - final)
            book.clear()

    return stats


def _consume_short(book: deque[Lot], size: float, price: float, st: WalletStats) -> None:
    """BUY: first cover any existing shorts (negative-size lots) FIFO, then open long."""
    remaining = size
    while remaining > 0 and book and book[0].size < 0:
        lot = book[0]
        short_size = -lot.size
        close = min(short_size, remaining)
        pnl = close * (lot.price - price)  # short profits if price dropped
        st.realized_pnl += pnl
        st.closed_events += 1
        if pnl > 0:
            st.wins += 1
        elif pnl < 0:
            st.losses += 1
        lot.size += close  # moves toward zero
        if lot.size == 0:
            book.popleft()
        remaining -= close
    if remaining > 0:
        book.append(Lot(size=remaining, price=price))


def _consume_long(book: deque[Lot], size: float, price: float, st: WalletStats) -> None:
    """SELL: first close any longs FIFO, then open short."""
    remaining = size
    while remaining > 0 and book and book[0].size > 0:
        lot = book[0]
        close = min(lot.size, remaining)
        pnl = close * (price - lot.price)
        st.realized_pnl += pnl
        st.closed_events += 1
        if pnl > 0:
            st.wins += 1
        elif pnl < 0:
            st.losses += 1
        lot.size -= close
        if lot.size == 0:
            book.popleft()
        remaining -= close
    if remaining > 0:
        book.append(Lot(size=-remaining, price=price))


def win_rate(s: WalletStats) -> float:
    if s.closed_events == 0:
        return 0.0
    return s.wins / s.closed_events
