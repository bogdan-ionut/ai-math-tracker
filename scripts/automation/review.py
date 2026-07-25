"""The review queue — where everything uncertain goes.

Design stance: an entry here is a *success*, not a failure. The pipeline is
tuned for recall at the search layer and caution at the merge layer, so the
queue is the intended destination for anything ambiguous, conflicting, or
uncorroborated. A human glancing at a queue entry costs seconds; a wrong
automatic merge corrupts a curated dataset.

Entry ids are derived from (reason, subject), so re-running the pipeline over
the same data does not enqueue the same question twice, while a genuinely
different concern about the same subject still gets its own entry.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from scripts.automation.ids import review_id
from scripts.automation.models import utc_now_iso

ReviewReason = Literal[
    "no_corroboration",            # social post with no external identifier
    "low_confidence",              # extraction confidence below the floor
    "conflicting_claim",           # contradicts a recorded result
    "identifier_conflict",         # explicit identifiers disagree
    "registry_conflict",           # one identifier maps to two curated records
    "ambiguous_identity",          # shortlist could not be resolved
    "judge_failed",                # the model errored — never guess
    "judge_uncertain",             # judge asked for human review
    "insufficient_information",    # judge could not tell
    "related_problem",             # connected but distinct; recorded, not merged
    "attempted_protected_write",   # a bug-catcher; should never appear
]

ReviewStatus = Literal["open", "resolved", "dismissed"]


class ReviewEntry(BaseModel):
    model_config = {"extra": "forbid"}

    id: str
    reason: ReviewReason
    status: ReviewStatus = "open"
    createdAt: str
    lastSeenAt: str

    observationId: Optional[str] = None
    candidateId: Optional[str] = None
    problemRef: Optional[str] = None

    title: str
    detail: str
    sourceUrl: Optional[str] = None
    shortlist: list[dict] = Field(default_factory=list)
    conflictingFields: list[str] = Field(default_factory=list)
    decision: Optional[str] = None
    judgeConfidence: Optional[float] = None

    @staticmethod
    def create(
        reason: ReviewReason,
        *,
        title: str,
        detail: str,
        observation_id: str | None = None,
        candidate_id: str | None = None,
        problem_ref: str | None = None,
        source_url: str | None = None,
        shortlist: list[dict] | None = None,
        conflicting_fields: list[str] | None = None,
        decision: str | None = None,
        judge_confidence: float | None = None,
        now: str | None = None,
    ) -> "ReviewEntry":
        stamp = now or utc_now_iso()
        subject = observation_id or candidate_id or problem_ref or title
        return ReviewEntry(
            id=review_id(reason, subject),
            reason=reason,
            createdAt=stamp,
            lastSeenAt=stamp,
            observationId=observation_id,
            candidateId=candidate_id,
            problemRef=problem_ref,
            title=title,
            detail=detail,
            sourceUrl=source_url,
            shortlist=shortlist or [],
            conflictingFields=conflicting_fields or [],
            decision=decision,
            judgeConfidence=judge_confidence,
        )


def upsert(queue: list[dict], entry: ReviewEntry) -> tuple[list[dict], bool]:
    """Add an entry, or refresh `lastSeenAt` if the same question is already open.

    Returns (queue, created). A resolved or dismissed entry is **not** reopened —
    a human has already answered that question, and re-asking it every day is how
    a review queue becomes noise nobody reads.
    """
    by_id = {e["id"]: dict(e) for e in queue}
    existing = by_id.get(entry.id)

    if existing is None:
        by_id[entry.id] = entry.model_dump(mode="json")
        created = True
    else:
        created = False
        if existing.get("status") == "open":
            existing["lastSeenAt"] = entry.lastSeenAt
            # keep the richest detail we have seen
            if len(entry.detail) > len(existing.get("detail", "")):
                existing["detail"] = entry.detail
            if entry.shortlist and not existing.get("shortlist"):
                existing["shortlist"] = entry.shortlist
        by_id[entry.id] = existing

    ordered = sorted(by_id.values(), key=lambda e: (e.get("createdAt", ""), e["id"]))
    return ordered, created


def open_entries(queue: list[dict]) -> list[dict]:
    return [e for e in queue if e.get("status") == "open"]


def summarize(queue: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in open_entries(queue):
        counts[e["reason"]] = counts.get(e["reason"], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
