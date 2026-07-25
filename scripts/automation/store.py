"""Atomic, corruption-tolerant JSON storage for the automation layer.

Two rules this module exists to enforce:

1. **Writes are atomic.** Everything goes to a sibling ``*.tmp`` and is then
   ``os.replace``d, which is atomic on POSIX. A process killed mid-write can
   never leave a half-written data file behind.

2. **A failure never destroys good data.** Reading a corrupt file raises rather
   than silently returning ``[]`` — because "the API returned nothing" and "the
   file is broken" must not lead to the same outcome (overwriting real records
   with an empty list).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "automation"
RAW_DIR = DATA_DIR / "raw" / "twitter"


class CorruptStoreError(RuntimeError):
    """Raised when an existing data file cannot be parsed."""


def read_json(path: Path, default: Any) -> Any:
    """Read JSON, returning ``default`` only when the file genuinely does not exist."""
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CorruptStoreError(f"cannot read {path}: {exc}") from exc
    if not text.strip():
        # An empty file is a previous failed write, not an empty dataset.
        raise CorruptStoreError(f"{path} is empty — refusing to treat as no data")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorruptStoreError(f"{path} is not valid JSON: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    """Serialise ``payload`` to ``path`` atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def observations_path() -> Path:
    return DATA_DIR / "observations.json"


def candidates_path() -> Path:
    return DATA_DIR / "candidates.json"


def review_queue_path() -> Path:
    return DATA_DIR / "review_queue.json"


def aliases_path() -> Path:
    return DATA_DIR / "aliases.json"


def state_path() -> Path:
    return DATA_DIR / "processing_state.json"


def raw_path(day: str) -> Path:
    return RAW_DIR / f"{day}.json"


def prune_raw(keep_days: int, today: str) -> list[str]:
    """Delete raw day-files older than ``keep_days``. Returns the names removed."""
    from datetime import date, timedelta

    if not RAW_DIR.exists():
        return []
    try:
        cutoff = date.fromisoformat(today) - timedelta(days=keep_days)
    except ValueError:
        return []
    removed: list[str] = []
    for f in sorted(RAW_DIR.glob("*.json")):
        try:
            when = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if when < cutoff:
            f.unlink()
            removed.append(f.name)
    return removed
