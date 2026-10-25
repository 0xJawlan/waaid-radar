"""Persistent state in data/state.json: what was seen, posted and reminded.

The file is rewritten only when something in it changed, so the scheduled
workflow commits only real changes (plus a monthly heartbeat).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SCHEMA_VERSION = 1


def empty_state() -> dict:
    return {"version": SCHEMA_VERSION, "programs": {}, "health": {}, "meta": {}}


def load_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    for key, default in empty_state().items():
        data.setdefault(key, default)
    return data


def dump_state(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def save_state(path: Path, state: dict) -> bool:
    """Write atomically; return True when the file actually changed."""
    text = dump_state(state)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)
    return True
