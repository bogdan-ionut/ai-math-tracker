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


class ContractError(RuntimeError):
    """Raised when a persisted file does not match its declared model.

    Distinct from CorruptStoreError: the file parses perfectly, it simply is not
    what the code claims it is. That is the more dangerous case, because
    everything downstream keeps working on data it has misread.
    """


def validate_records(model: type, rows: Any, *, path: Path, when: str) -> list:
    """Check `rows` against `model` and say clearly what failed.

    Every model here sets `extra = "forbid"`, which is worth nothing unless
    something validates. Until now the workflow checked only that these files
    were parseable JSON, so six fields the extraction stage wrote had never been
    declared and nothing noticed.

    Validating on **write** catches the bug in the run that caused it; on
    **read**, it catches a file edited by hand or left behind by an older
    version.
    """
    from pydantic import TypeAdapter, ValidationError

    if not isinstance(rows, list):
        raise ContractError(f"{path} ({when}): expected a list, got {type(rows).__name__}")
    try:
        return TypeAdapter(list[model]).validate_python(rows)
    except ValidationError as exc:
        first = exc.errors()[:3]
        detail = "; ".join(
            f"[{'.'.join(str(p) for p in e['loc'])}] {e['msg']}" for e in first
        )
        raise ContractError(
            f"{path} ({when}) does not match {model.__name__}: "
            f"{exc.error_count()} error(s) — {detail}"
        ) from exc


def read_records(path: Path, model: type, default: Any = None) -> list[dict]:
    """Read and validate, returning plain dicts so callers keep working on dicts."""
    rows = read_json(path, default if default is not None else [])
    validate_records(model, rows, path=path, when="on read")
    return rows


def write_records(path: Path, model: type, rows: list) -> None:
    """Validate, then write atomically. A contract breach never reaches disk."""
    validate_records(model, rows, path=path, when="before write")
    write_json(path, rows)


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


def backlog_path() -> Path:
    """Fetched-but-not-yet-processed tweets, carried to the next run.

    A run caps how many observations it creates. Everything above the cap used
    to be counted and dropped, so a busy day silently lost the surplus and the
    only trace was a number in the summary. These records are already paid for;
    parking them here costs nothing and the next run consumes them first.
    """
    return DATA_DIR / "ingest_backlog.json"


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
