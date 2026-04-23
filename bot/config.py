"""Centralised config. All tunables are env-driven with sane, conservative defaults.

Nothing else in `bot/` should call `os.environ` directly — import from here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(exist_ok=True)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw is not None else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw is not None else default


@dataclass(frozen=True)
class Config:
    # wallet / auth
    pk_hex: str | None
    funder: str | None
    clob_host: str
    chain_id: int
    signature_type: int

    # mode
    dry_run: bool
    bankroll_usd: float

    # risk rails
    daily_loss_limit_usd: float
    max_drawdown_pct: float
    max_position_usd: float
    max_open_positions: int
    max_per_event_usd: float
    stop_loss_pct: float

    # scanner / entry filters
    gap_min: float
    depth_min_usd: float
    hours_min: float
    hours_max: float
    whale_copy_delay_s: float
    whale_price_drift_max: float

    # sizing
    kelly_cap: float
    kelly_multiplier: float

    # exit
    exit_target_fraction: float
    exit_volume_mult: float
    exit_stale_hours: float
    exit_stale_move: float

    # paths
    trades_csv: Path
    positions_db: Path
    targets_json: Path
    log_path: Path


def load() -> Config:
    return Config(
        pk_hex=os.getenv("PK_HEX"),
        funder=os.getenv("FUNDER"),
        clob_host=os.getenv("CLOB_HOST", "https://clob.polymarket.com"),
        chain_id=_env_int("CHAIN_ID", 137),
        signature_type=_env_int("SIGNATURE_TYPE", 0),
        dry_run=_env_bool("DRY_RUN", True),
        bankroll_usd=_env_float("BANKROLL_USD", 50.0),
        daily_loss_limit_usd=_env_float("DAILY_LOSS_LIMIT_USD", 5.0),
        max_drawdown_pct=_env_float("MAX_DRAWDOWN_PCT", 0.15),
        max_position_usd=_env_float("MAX_POSITION_USD", 10.0),
        max_open_positions=_env_int("MAX_OPEN_POSITIONS", 5),
        max_per_event_usd=_env_float("MAX_PER_EVENT_USD", 15.0),
        stop_loss_pct=_env_float("STOP_LOSS_PCT", 0.15),
        gap_min=_env_float("GAP_MIN", 0.07),
        depth_min_usd=_env_float("DEPTH_MIN_USD", 500.0),
        hours_min=_env_float("HOURS_MIN", 4.0),
        hours_max=_env_float("HOURS_MAX", 168.0),
        whale_copy_delay_s=_env_float("WHALE_COPY_DELAY_S", 60.0),
        whale_price_drift_max=_env_float("WHALE_PRICE_DRIFT_MAX", 0.02),
        kelly_cap=_env_float("KELLY_CAP", 0.25),
        kelly_multiplier=_env_float("KELLY_MULTIPLIER", 0.25),
        exit_target_fraction=_env_float("EXIT_TARGET_FRACTION", 0.85),
        exit_volume_mult=_env_float("EXIT_VOLUME_MULT", 3.0),
        exit_stale_hours=_env_float("EXIT_STALE_HOURS", 24.0),
        exit_stale_move=_env_float("EXIT_STALE_MOVE", 0.02),
        trades_csv=Path(os.getenv("POLY_DATA_TRADES_CSV", "./vendor/poly_data/processed/trades.csv")),
        positions_db=STATE_DIR / "positions.db",
        targets_json=STATE_DIR / "targets.json",
        log_path=STATE_DIR / "log.jsonl",
    )


CFG = load()
