"""Poll target wallets for fresh fills.

Polymarket fills land on-chain (Polygon) as Goldsky-indexed events. For robustness we
expose a `WhaleFeed` protocol and ship two implementations:

  1. `GoldskyWhaleFeed` — production. Queries the public Goldsky subgraph for recent
     `OrderFilled` events by maker/taker address.
  2. `StubWhaleFeed`    — used by shadow_replay and tests. Replays recorded fills.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

import httpx

GOLDSKY_URL = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/polymarket-orderbook-matic/prod/gn"

_ORDER_FILLED_QUERY = """
query ($wallets: [Bytes!]!, $since: BigInt!) {
  orderFilleds(
    where: { or: [{ maker_in: $wallets }, { taker_in: $wallets }], timestamp_gt: $since }
    orderBy: timestamp
    orderDirection: desc
    first: 200
  ) {
    id
    timestamp
    maker
    taker
    makerAssetId
    makerAmountFilled
    takerAssetId
    takerAmountFilled
  }
}
"""


@dataclass
class WhaleFill:
    whale: str        # the target wallet that filled
    token_id: str     # CTF token_id they ended up long (or reduced short in)
    side: str         # "BUY" if the whale acquired the token, "SELL" if they offloaded
    price: float      # effective USDC/token
    size: float       # tokens moved
    ts: int


class WhaleFeed(Protocol):
    def poll(self, wallets: Iterable[str], since_ts: int) -> list[WhaleFill]: ...


class GoldskyWhaleFeed:
    def __init__(self, url: str = GOLDSKY_URL, client: httpx.Client | None = None) -> None:
        self._url = url
        self._client = client or httpx.Client(timeout=15.0)

    def poll(self, wallets: Iterable[str], since_ts: int) -> list[WhaleFill]:
        wallets = [w.lower() for w in wallets]
        if not wallets:
            return []
        r = self._client.post(
            self._url,
            json={"query": _ORDER_FILLED_QUERY, "variables": {"wallets": wallets, "since": str(since_ts)}},
        )
        r.raise_for_status()
        events = r.json().get("data", {}).get("orderFilleds", []) or []
        out: list[WhaleFill] = []
        for ev in events:
            fill = _interpret(ev, set(wallets))
            if fill is not None:
                out.append(fill)
        return out


def _interpret(ev: dict, whale_set: set[str]) -> WhaleFill | None:
    """Turn a raw OrderFilled event into a WhaleFill from the whale's perspective.

    CTF conventions: maker_asset_id == "0" means USDC. Any other asset_id is an
    outcome token.
    """
    try:
        maker = ev["maker"].lower()
        taker = ev["taker"].lower()
        maker_asset = str(ev["makerAssetId"])
        taker_asset = str(ev["takerAssetId"])
        maker_amt = float(ev["makerAmountFilled"])
        taker_amt = float(ev["takerAmountFilled"])
        ts = int(ev["timestamp"])
    except (KeyError, ValueError, TypeError):
        return None

    # Determine whale side & token
    if maker in whale_set:
        whale = maker
        gave_asset, gave_amt = maker_asset, maker_amt
        got_asset, got_amt = taker_asset, taker_amt
    elif taker in whale_set:
        whale = taker
        gave_asset, gave_amt = taker_asset, taker_amt
        got_asset, got_amt = maker_asset, maker_amt
    else:
        return None

    # One side is USDC ("0"), the other is the outcome token.
    if gave_asset == "0" and got_asset != "0":
        # whale paid USDC, received tokens → BUY
        if got_amt <= 0:
            return None
        price = gave_amt / got_amt / 1e6 if gave_amt > 1e6 else gave_amt / got_amt
        return WhaleFill(whale=whale, token_id=got_asset, side="BUY", price=_clip_price(price), size=got_amt, ts=ts)
    if got_asset == "0" and gave_asset != "0":
        if gave_amt <= 0:
            return None
        price = got_amt / gave_amt / 1e6 if got_amt > 1e6 else got_amt / gave_amt
        return WhaleFill(whale=whale, token_id=gave_asset, side="SELL", price=_clip_price(price), size=gave_amt, ts=ts)
    return None


def _clip_price(p: float) -> float:
    if p < 0:
        return 0.0
    if p > 1:
        return 1.0
    return round(p, 4)


class StubWhaleFeed:
    """Feed that returns pre-recorded fills. Used by shadow_replay + tests."""

    def __init__(self, fills: list[WhaleFill]) -> None:
        self._fills = sorted(fills, key=lambda f: f.ts)

    def poll(self, wallets: Iterable[str], since_ts: int) -> list[WhaleFill]:
        wset = {w.lower() for w in wallets}
        return [f for f in self._fills if f.ts > since_ts and f.whale.lower() in wset]
