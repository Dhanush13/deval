"""One-shot: read vendor/poly_data/processed/trades.csv, rank wallets, write
state/targets.json.

The input CSV must be pre-normalized to include a `side` column ("BUY"|"SELL"
from the wallet's perspective). If your poly_data export lacks it, run
`normalize_goldsky.py` (TODO) to derive it from goldsky/orderFilled.csv.

Usage:
    uv run python scripts/rank_wallets.py [--category crypto] [--top-n 20]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import CFG
from bot.ranker import rank


def _load_trades_for_ranker(csv_path: Path) -> list[dict]:
    lf = pl.scan_csv(csv_path)
    cols = set(lf.collect_schema().names())
    needed = {"maker", "market_id", "timestamp", "price", "token_amount"}
    missing = needed - cols
    if missing:
        sys.exit(f"trades.csv missing required columns: {sorted(missing)}")

    # `side` must be present (per module docstring). Accept common aliases.
    side_col = next((c for c in ("side", "direction", "buy_or_sell") if c in cols), None)
    if side_col is None:
        sys.exit(
            "trades.csv does not contain a BUY/SELL side column. Re-run poly_data "
            "with orderFilled normalization, or add a `side` column derived from "
            "maker_asset_id (USDC == BUY for the maker)."
        )

    df = lf.select(
        [
            pl.col("maker").alias("wallet"),
            pl.col("market_id"),
            pl.col("timestamp").alias("ts"),
            pl.col(side_col).str.to_uppercase().alias("side"),
            pl.col("token_amount").alias("size"),
            pl.col("price"),
        ]
    ).collect(streaming=True)
    return df.to_dicts()


def _load_market_categories(markets_csv: Path | None) -> dict[str, str]:
    if markets_csv is None or not markets_csv.exists():
        return {}
    df = pl.read_csv(markets_csv)
    cols = set(df.columns)
    if "token1" in cols and "token2" in cols and "category" in cols:
        out: dict[str, str] = {}
        for row in df.iter_rows(named=True):
            cat = row.get("category") or ""
            if row.get("token1"):
                out[str(row["token1"])] = cat
            if row.get("token2"):
                out[str(row["token2"])] = cat
        return out
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=CFG.trades_csv)
    ap.add_argument(
        "--markets-csv",
        type=Path,
        default=CFG.trades_csv.parent.parent / "markets.csv",
    )
    ap.add_argument("--category", default="crypto")
    ap.add_argument("--top-n", type=int, default=20)
    ap.add_argument("--output", type=Path, default=CFG.targets_json)
    args = ap.parse_args()

    if not args.csv.exists():
        sys.exit(f"trades CSV not found: {args.csv}. Clone warproxxx/poly_data into vendor/.")

    trades = _load_trades_for_ranker(args.csv)
    categories = _load_market_categories(args.markets_csv)
    category_filter = args.category if categories else None

    targets = rank(
        trades,
        category_filter=category_filter,
        market_categories=categories or None,
        top_n=args.top_n,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(targets, indent=2))
    print(f"wrote {len(targets)} targets to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
