"""Decide whether a run produced anything worth committing.

Naively diffing `data/automation/` would commit every single day, because
`processing_state.json` carries `lastRunAt` and the telemetry file carries
`runAt`. A year of that is 365 commits that say nothing, and it buries the
handful of commits that actually mean something.

So "meaningful" is defined narrowly: did the *substantive* stores change —
observations, candidates, the review queue, aliases? Timestamps, counters and
telemetry ride along when something real changed, and are dropped when nothing
did.

Losing a run's counters is harmless: deduplication is keyed on the source-native
id and the lookback window overlaps deliberately, so nothing depends on the
state file having advanced.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Changes in these files justify a commit.
SUBSTANTIVE = (
    "data/automation/observations.json",
    "data/automation/candidates.json",
    "data/automation/review_queue.json",
    "data/automation/aliases.json",
)

# These ride along, but never justify a commit on their own.
INCIDENTAL = (
    "data/automation/processing_state.json",
    "data/automation/query_telemetry.json",
)

# Volatile keys ignored when comparing — they move on every run by design.
VOLATILE_KEYS = {"lastRunAt", "runAt", "lastSeenAt", "collectedAt", "generatedAt"}


def _strip_volatile(node):
    """Recursively drop keys that change every run regardless of content."""
    if isinstance(node, dict):
        return {k: _strip_volatile(v) for k, v in sorted(node.items()) if k not in VOLATILE_KEYS}
    if isinstance(node, list):
        return [_strip_volatile(v) for v in node]
    return node


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd or ROOT, capture_output=True, text=True, check=False
    ).stdout


def changed_paths(cwd: Path | None = None) -> list[str]:
    out = _git("status", "--porcelain", "--", "data/automation", cwd=cwd)
    paths = []
    for line in out.splitlines():
        if len(line) > 3:
            paths.append(line[3:].strip().strip('"'))
    return paths


def file_is_substantively_changed(path: str, cwd: Path | None = None) -> bool:
    """True if the file's content changed once volatile keys are ignored."""
    root = cwd or ROOT
    full = root / path
    if not full.exists():
        return True                                  # deletion is substantive
    committed = _git("show", f"HEAD:{path}", cwd=root)
    if not committed.strip():
        return True                                  # new file
    try:
        old = _strip_volatile(json.loads(committed))
        new = _strip_volatile(json.loads(full.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return True                                  # can't tell → treat as changed
    return old != new


def assess(cwd: Path | None = None) -> dict:
    """Report what changed and whether it warrants a commit."""
    changed = changed_paths(cwd)
    substantive = [
        p for p in changed
        if p in SUBSTANTIVE and file_is_substantively_changed(p, cwd)
    ]
    incidental = [p for p in changed if p in INCIDENTAL or p not in SUBSTANTIVE]
    unexpected = [
        p for p in changed
        if not p.startswith("data/automation/")
    ]
    return {
        "changed": changed,
        "substantive": substantive,
        "incidental": incidental,
        "unexpected": unexpected,
        "shouldCommit": bool(substantive),
        "reason": (
            f"{len(substantive)} substantive file(s) changed: {', '.join(substantive)}"
            if substantive
            else "only timestamps/counters moved — not committing"
        ),
    }


def main() -> int:
    report = assess()
    print(json.dumps(report, indent=2))
    if report["unexpected"]:
        print(f"::error::run touched files outside data/automation: {report['unexpected']}")
        return 2
    # Exit 0 when there is something to commit, 1 when there is not — so the
    # workflow can branch on it without parsing JSON.
    return 0 if report["shouldCommit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
