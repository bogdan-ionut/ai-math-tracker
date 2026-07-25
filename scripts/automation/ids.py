"""Stable identifier derivation.

Every generated id must be a pure function of the thing it names, so that
re-running the pipeline over the same window produces byte-identical output and
creates no duplicate records. Nothing here may use time, randomness, or
collection order.
"""
from __future__ import annotations

import hashlib
import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _sha(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def observation_id(source_type: str, source_native_id: str) -> str:
    """Stable id for a discovered signal.

    Keyed on the source-native id (e.g. the tweet id), so the same tweet seen in
    ten different queries, or on ten different days, is always one observation.
    """
    return f"obs_{_sha(f'{source_type}:{source_native_id}')}"


def candidate_id(canonical_name: str, external: dict[str, list[str]] | None = None) -> str:
    """Stable id for a proposed result.

    Prefers the strongest external identifier available so that the same problem
    discovered through different routes converges on one candidate. Falls back to
    the normalised name.
    """
    external = external or {}
    for kind in ("erdos", "arxiv", "doi", "oeis"):
        values = external.get(kind) or []
        if values:
            return f"cand_{kind}_{slugify(sorted(values)[0])}"
    return f"cand_{_sha(slugify(canonical_name))}"


def review_id(reason: str, subject_id: str) -> str:
    """Stable id for a review-queue entry.

    Keyed on (reason, subject) so re-running does not enqueue the same question
    twice, but a genuinely different concern about the same subject still gets
    its own entry.
    """
    return f"rev_{_sha(f'{reason}:{subject_id}')}"


def text_hash(text: str | None) -> str | None:
    """Full-strength hash of source text, for change detection and provenance."""
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    """Lowercase, ASCII-ish, hyphen-separated."""
    v = value.lower()
    for a, b in (("ő", "o"), ("ö", "o"), ("é", "e"), ("ü", "u"), ("ß", "ss")):
        v = v.replace(a, b)
    v = _SLUG_RE.sub("-", v).strip("-")
    return v[:64] or "unknown"
