# deval — narrow Polymarket whale-copy bot

A deliberately small Polymarket bot. One strategy (whale-copy), one process, one
log. DRY_RUN on by default. No Claude API in v1.

## What it does

1. **Rank wallets** from the public 86M-trade history (`warproxxx/poly_data`) using
   FIFO-reconstructed realized PnL, with in-sample / out-of-sample validation and
   optional category filter (default: `crypto`).
2. **Poll fills** from the ranked wallets via the Goldsky subgraph.
3. **Enter** after a configurable delay if the market's midpoint hasn't drifted
   away from the whale's fill, sized via quarter-Kelly capped by `MAX_POSITION_USD`.
4. **Exit** on the first of: stop-loss, target hit (85% of expected move),
   volume spike (3× rolling 1-hour median), stale thesis (24h + <2¢ move).

## Safety rails (all env-driven)

- `DRY_RUN=true` logs intended orders instead of signing them.
- `DAILY_LOSS_LIMIT_USD`, `MAX_DRAWDOWN_PCT`, `MAX_OPEN_POSITIONS`,
  `MAX_POSITION_USD`, `MAX_PER_EVENT_USD`, `STOP_LOSS_PCT` — all enforced
  pre-trade in `bot/risk.py`.
- Every intended order is written to `state/positions.db` with a UUID *before*
  signing, so a crash mid-order is recoverable.

## Setup

```bash
uv sync
cp .env.example .env
# edit .env — set PK_HEX, confirm DRY_RUN=true

# clone the vendored data repo (required for the ranker):
mkdir -p vendor && git clone https://github.com/warproxxx/poly_data vendor/poly_data
# then download the poly_data snapshot per their README
```

## Build the target list

```bash
uv run python scripts/rank_wallets.py --category crypto --top-n 20
# writes state/targets.json
```

## Shadow-replay gate

```bash
uv run python scripts/shadow_replay.py --days 30 --fees-bps 200
```

This prints a JSON summary and exits 0 **only if** Sharpe ≥ 1.5, max drawdown ≤
1500 bps, and mean PnL > 0. **Do not flip DRY_RUN=false until this passes.** Exit
code is intentionally non-zero when the gate fails — CI-friendly.

## Approve on-chain (once per wallet)

```bash
uv run python scripts/setup_allowances.py
```

## Run the bot (dry-run by default)

```bash
uv run python -m bot.copy_bot
# or under tmux for VPS use:
scripts/start.sh
```

Structured logs stream to stderr and `state/log.jsonl`. Tail with:

```bash
tail -f state/log.jsonl | jq .
```

## Tests

```bash
uv run pytest
```

Covers PnL FIFO correctness, sizing math, risk gates, and all four exit triggers.

## Reality

The tweet that inspired this project reports an n=1, 27-day result. Our plan assumes
the strategy can lose money. The shadow-replay gate is the bot's circuit breaker;
if it fails on your fee assumption, the strategy does not go live.

## License

MIT (or whatever you prefer — add a LICENSE file before publishing).
