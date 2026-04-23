"""Thin wrapper over py_clob_client. Import lazily so tests that don't touch it
don't need the dep installed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import CFG
from .logging_ import log


@dataclass
class OrderResult:
    placed: bool
    order_id: str | None
    raw: dict[str, Any] | None
    note: str = ""


class Clob:
    """Lazily-constructed CLOB client. Instantiating this does NOT sign anything;
    it only prepares credentials. Orders are only signed inside place_limit()."""

    def __init__(self) -> None:
        self._client: Any = None

    def _connect(self) -> Any:
        if self._client is not None:
            return self._client
        if not CFG.pk_hex:
            raise RuntimeError("PK_HEX is unset; cannot construct CLOB client")

        from py_clob_client.client import ClobClient  # type: ignore

        kwargs: dict[str, Any] = dict(
            host=CFG.clob_host,
            key=CFG.pk_hex,
            chain_id=CFG.chain_id,
            signature_type=CFG.signature_type,
        )
        if CFG.funder:
            kwargs["funder"] = CFG.funder

        c = ClobClient(**kwargs)
        creds = c.create_or_derive_api_creds()
        c.set_api_creds(creds)
        self._client = c
        return c

    # ---- read-only (no signing) --------------------------------------------------
    def midpoint(self, token_id: str) -> float:
        c = self._connect()
        return float(c.get_midpoint(token_id)["mid"])

    def book(self, token_id: str) -> dict[str, Any]:
        c = self._connect()
        return c.get_order_book(token_id)

    def open_orders(self) -> list[dict[str, Any]]:
        c = self._connect()
        return list(c.get_orders())

    # ---- signed --------------------------------------------------------------------
    def place_limit(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> OrderResult:
        """Place a signed limit order. DRY_RUN short-circuits to a log line."""
        side = side.upper()
        assert side in {"BUY", "SELL"}, f"side must be BUY/SELL, got {side!r}"
        if size <= 0:
            return OrderResult(placed=False, order_id=None, raw=None, note="size<=0")

        payload = {"token_id": token_id, "side": side, "price": round(price, 3), "size": round(size, 2)}
        if CFG.dry_run:
            log("dry_run.place_limit", **payload)
            return OrderResult(placed=False, order_id=None, raw=None, note="DRY_RUN")

        from py_clob_client.clob_types import OrderArgs  # type: ignore
        from py_clob_client.order_builder.constants import BUY, SELL  # type: ignore

        c = self._connect()
        args = OrderArgs(
            token_id=token_id,
            price=payload["price"],
            size=payload["size"],
            side=BUY if side == "BUY" else SELL,
        )
        signed = c.create_order(args)
        resp = c.post_order(signed)
        order_id = resp.get("orderID") or resp.get("orderId") or resp.get("id")
        log("place_limit.response", order_id=order_id, **payload)
        return OrderResult(placed=bool(order_id), order_id=order_id, raw=resp)

    def cancel(self, order_id: str) -> dict[str, Any]:
        if CFG.dry_run:
            log("dry_run.cancel", order_id=order_id)
            return {"canceled": [order_id], "dry_run": True}
        c = self._connect()
        return c.cancel(order_id=order_id)
