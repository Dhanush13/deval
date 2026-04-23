"""One-shot on-chain setup: approve USDC and CTF transfers for the Polymarket
exchange so the EOA (sig_type=0) can actually trade.

Uses py-clob-client helpers where available; falls back to printing the exact
transactions the user must send via a wallet UI if the helper isn't present.

Only run once per wallet. Safe to re-run — allowance checks are idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import CFG


def main() -> int:
    if not CFG.pk_hex:
        print("PK_HEX unset. Aborting.", file=sys.stderr)
        return 1

    try:
        from py_clob_client.client import ClobClient  # type: ignore
    except ImportError:
        print("py-clob-client not installed. Run `uv sync` first.", file=sys.stderr)
        return 1

    client = ClobClient(
        host=CFG.clob_host,
        key=CFG.pk_hex,
        chain_id=CFG.chain_id,
        signature_type=CFG.signature_type,
    )
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    print("API credentials established for", client.get_address())

    # The newer client exposes `approve` / `set_approvals` helpers depending on version.
    for candidate in ("set_approvals", "approve", "set_allowances"):
        fn = getattr(client, candidate, None)
        if callable(fn):
            print(f"calling client.{candidate}() …")
            try:
                print(fn())
                print("approvals set. You can now trade.")
                return 0
            except Exception as exc:
                print(f"{candidate}() raised: {exc}", file=sys.stderr)

    print(
        "No approval helper found on this py-clob-client version. Approve manually:\n"
        "  - USDC.approve(CTF_EXCHANGE, uint256.max)\n"
        "  - CTF.setApprovalForAll(CTF_EXCHANGE, true)\n"
        "  - USDC.approve(NEG_RISK_EXCHANGE, uint256.max)\n"
        "  - CTF.setApprovalForAll(NEG_RISK_EXCHANGE, true)\n"
        "See https://docs.polymarket.com/ for current contract addresses.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
