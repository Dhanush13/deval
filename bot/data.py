"""Polars loader for vendor/poly_data/processed/trades.csv.

Schema (from poly_data/processed/trades.csv):
    timestamp       int/str   unix seconds when the trade filled
    market_id       str       token_id on CTF (one side of a condition)
    maker           str       0x... wallet that placed the resting order
    taker           str       0x... wallet that crossed the spread
    price           float     0..1  USDC per token
    usd_amount      float     USDC notional
    token_amount    float     units of conditional token moved

The CSV does NOT include realized profit — pnl.py reconstructs it by FIFO-matching
buys and sells per (wallet, market_id).

`condition_id` is NOT in the CSV directly; we map market_id → condition_id via the
markets metadata table if available (poly_data/processed/markets.csv). For now we
treat `market_id` (the token) as the book unit — YES and NO tokens of the same
condition are separate book-positions, which is correct for PnL.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

REQUIRED_COLUMNS = {
    "timestamp",
    "market_id",
    "maker",
    "taker",
    "price",
    "usd_amount",
    "token_amount",
}


def load_trades(path: Path) -> pl.DataFrame:
    """Eager load — small-enough for test fixtures. Use load_trades_lazy for prod."""
    df = pl.read_csv(path)
    _validate(df)
    return df


def load_trades_lazy(path: Path) -> pl.LazyFrame:
    """Streaming scan; safe for the full 86M-row production CSV."""
    lf = pl.scan_csv(path)
    # cheap schema check via columns
    cols = set(lf.collect_schema().names())
    missing = REQUIRED_COLUMNS - cols
    if missing:
        raise ValueError(f"trades.csv missing required columns: {sorted(missing)}")
    return lf


def _validate(df: pl.DataFrame) -> None:
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"trades.csv missing required columns: {sorted(missing)}")
