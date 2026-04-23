#!/usr/bin/env bash
# Launch the bot under tmux so it survives ssh disconnects and a single crash-loop
# restart is easy. Uses DRY_RUN from .env — do NOT flip that to false until
# shadow_replay passes the go-live gate.

set -euo pipefail
cd "$(dirname "$0")/.."

: "${SESSION:=deval}"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not installed. See https://docs.astral.sh/uv/." >&2
  exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux not installed. Falling back to foreground." >&2
  exec uv run python -m bot.copy_bot
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session '$SESSION' already running. Attach with: tmux attach -t $SESSION"
  exit 0
fi

tmux new-session -d -s "$SESSION" "uv run python -m bot.copy_bot 2>&1 | tee -a state/console.log"
echo "bot launched in tmux session '$SESSION'. Attach with: tmux attach -t $SESSION"
