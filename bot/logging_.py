"""Structured JSONL logger. Single writer; designed for tail -f debugging and
downstream grep/jq analysis."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .config import CFG

_LOCK = threading.Lock()


def log(event: str, **fields: Any) -> None:
    rec = {"ts": time.time(), "event": event, **fields}
    line = json.dumps(rec, default=str, separators=(",", ":"))
    with _LOCK:
        _append(CFG.log_path, line)
        print(line, file=sys.stderr)


def _append(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
