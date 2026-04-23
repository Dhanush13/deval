"""Gamma market metadata (read-only, no auth). Thin httpx wrapper."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, Field

GAMMA_BASE = "https://gamma-api.polymarket.com"


class Market(BaseModel):
    id: str
    question: str
    condition_id: str | None = Field(default=None, alias="conditionId")
    event_id: str | None = Field(default=None, alias="eventId")
    token_ids: list[str] = Field(default_factory=list, alias="clobTokenIds")
    end_date: datetime | None = Field(default=None, alias="endDate")
    category: str | None = None
    volume: float = 0.0
    active: bool = True
    closed: bool = False

    model_config = {"populate_by_name": True, "extra": "ignore"}

    def hours_to_resolution(self, now: datetime | None = None) -> float | None:
        if self.end_date is None:
            return None
        now = now or datetime.now(timezone.utc)
        if self.end_date.tzinfo is None:
            end = self.end_date.replace(tzinfo=timezone.utc)
        else:
            end = self.end_date
        return (end - now).total_seconds() / 3600.0


def _parse(raw: dict[str, Any]) -> Market | None:
    try:
        tids = raw.get("clobTokenIds")
        if isinstance(tids, str):
            import json as _json
            try:
                raw = {**raw, "clobTokenIds": _json.loads(tids)}
            except Exception:
                raw = {**raw, "clobTokenIds": []}
        return Market.model_validate(raw)
    except Exception:
        return None


def list_markets(limit: int = 500, client: httpx.Client | None = None) -> list[Market]:
    owns_client = client is None
    client = client or httpx.Client(base_url=GAMMA_BASE, timeout=15.0)
    try:
        r = client.get("/markets", params={"active": "true", "closed": "false", "limit": limit})
        r.raise_for_status()
        data = r.json()
    finally:
        if owns_client:
            client.close()
    rows = data if isinstance(data, list) else data.get("data", [])
    out: list[Market] = []
    for row in rows:
        m = _parse(row)
        if m is not None and m.active and not m.closed:
            out.append(m)
    return out
