"""SQLite-backed position store. Idempotent: every intent is persisted with a
UUID *before* the order is signed, so a crash mid-order is recoverable.

Schema:
    intents(signal_uuid PK, ts, token_id, event_id, side, size_usd, entry_price,
            target_price, status, order_id, closed_ts, exit_reason, realized_pnl)
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS intents (
    signal_uuid   TEXT PRIMARY KEY,
    ts            REAL NOT NULL,
    token_id      TEXT NOT NULL,
    event_id      TEXT,
    side          TEXT NOT NULL,
    size_usd      REAL NOT NULL,
    entry_price   REAL NOT NULL,
    target_price  REAL,
    status        TEXT NOT NULL,
    order_id      TEXT,
    closed_ts     REAL,
    exit_reason   TEXT,
    realized_pnl  REAL
);
CREATE INDEX IF NOT EXISTS idx_intents_status ON intents(status);
CREATE INDEX IF NOT EXISTS idx_intents_token ON intents(token_id);
CREATE INDEX IF NOT EXISTS idx_intents_event ON intents(event_id);
"""

OPEN_STATUSES = ("PENDING", "FILLED")


@dataclass
class Intent:
    signal_uuid: str
    ts: float
    token_id: str
    event_id: str | None
    side: str
    size_usd: float
    entry_price: float
    target_price: float | None
    status: str  # PENDING | FILLED | CANCELED | CLOSED
    order_id: str | None = None
    closed_ts: float | None = None
    exit_reason: str | None = None
    realized_pnl: float | None = None


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def new_uuid() -> str:
    return str(uuid.uuid4())


def record_intent(
    conn: sqlite3.Connection,
    *,
    token_id: str,
    event_id: str | None,
    side: str,
    size_usd: float,
    entry_price: float,
    target_price: float | None,
) -> Intent:
    sid = new_uuid()
    intent = Intent(
        signal_uuid=sid,
        ts=time.time(),
        token_id=token_id,
        event_id=event_id,
        side=side,
        size_usd=size_usd,
        entry_price=entry_price,
        target_price=target_price,
        status="PENDING",
    )
    conn.execute(
        "INSERT INTO intents (signal_uuid, ts, token_id, event_id, side, size_usd, "
        "entry_price, target_price, status) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            intent.signal_uuid,
            intent.ts,
            intent.token_id,
            intent.event_id,
            intent.side,
            intent.size_usd,
            intent.entry_price,
            intent.target_price,
            intent.status,
        ),
    )
    return intent


def mark_filled(conn: sqlite3.Connection, signal_uuid: str, order_id: str | None) -> None:
    conn.execute(
        "UPDATE intents SET status='FILLED', order_id=? WHERE signal_uuid=?",
        (order_id, signal_uuid),
    )


def mark_canceled(conn: sqlite3.Connection, signal_uuid: str) -> None:
    conn.execute(
        "UPDATE intents SET status='CANCELED', closed_ts=? WHERE signal_uuid=?",
        (time.time(), signal_uuid),
    )


def mark_closed(
    conn: sqlite3.Connection,
    signal_uuid: str,
    exit_reason: str,
    realized_pnl: float,
) -> None:
    conn.execute(
        "UPDATE intents SET status='CLOSED', closed_ts=?, exit_reason=?, realized_pnl=? "
        "WHERE signal_uuid=?",
        (time.time(), exit_reason, realized_pnl, signal_uuid),
    )


def open_intents(conn: sqlite3.Connection) -> list[Intent]:
    rows = conn.execute(
        f"SELECT * FROM intents WHERE status IN ({','.join('?'*len(OPEN_STATUSES))})",
        OPEN_STATUSES,
    ).fetchall()
    return [_row_to_intent(r) for r in rows]


def exposure_by_event(conn: sqlite3.Connection) -> dict[str, float]:
    out: dict[str, float] = {}
    rows = conn.execute(
        "SELECT event_id, SUM(size_usd) AS exposure FROM intents "
        f"WHERE status IN ({','.join('?'*len(OPEN_STATUSES))}) "
        "GROUP BY event_id",
        OPEN_STATUSES,
    ).fetchall()
    for r in rows:
        if r["event_id"]:
            out[r["event_id"]] = float(r["exposure"] or 0.0)
    return out


def realized_pnl_since(conn: sqlite3.Connection, since_ts: float) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(realized_pnl), 0.0) AS pnl FROM intents "
        "WHERE status='CLOSED' AND closed_ts >= ?",
        (since_ts,),
    ).fetchone()
    return float(row["pnl"] or 0.0)


def peak_bankroll(conn: sqlite3.Connection, starting_bankroll: float) -> float:
    """Running max of (starting_bankroll + cumulative realized_pnl over time)."""
    rows = conn.execute(
        "SELECT realized_pnl FROM intents WHERE status='CLOSED' "
        "ORDER BY closed_ts ASC"
    ).fetchall()
    peak = starting_bankroll
    running = starting_bankroll
    for r in rows:
        running += float(r["realized_pnl"] or 0.0)
        if running > peak:
            peak = running
    return peak


def _row_to_intent(row: sqlite3.Row) -> Intent:
    return Intent(
        signal_uuid=row["signal_uuid"],
        ts=row["ts"],
        token_id=row["token_id"],
        event_id=row["event_id"],
        side=row["side"],
        size_usd=row["size_usd"],
        entry_price=row["entry_price"],
        target_price=row["target_price"],
        status=row["status"],
        order_id=row["order_id"],
        closed_ts=row["closed_ts"],
        exit_reason=row["exit_reason"],
        realized_pnl=row["realized_pnl"],
    )


def find_pending_by_order(conn: sqlite3.Connection, order_ids: Iterable[str]) -> list[Intent]:
    """On restart, look up intents whose stored order_id is in the live open-orders set
    to resync state."""
    ids = list(order_ids)
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM intents WHERE order_id IN ({placeholders})",
        ids,
    ).fetchall()
    return [_row_to_intent(r) for r in rows]
