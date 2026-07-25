"""The deterministic merge engine.

**Python decides what happens. The model only supplies a label.**

Every decision has exactly one handler, every handler is additive, and none of
them can write the curated registry — `data/results.json` is read-only to this
module by construction (it is never opened for writing anywhere in it).

The safe mutations, and nothing else:
  * create or update a candidate
  * attach a source to a candidate
  * append an evidence event
  * record an alias
  * refresh `lastSeenAt`
  * create a review-queue entry
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from scripts.automation.ids import candidate_id as make_candidate_id
from scripts.automation.matching import MatchOutcome
from scripts.automation.models import utc_now_iso
from scripts.automation.policy import (
    may_become_candidate,
    meets_confidence,
)
from scripts.automation.review import ReviewEntry, upsert


class Claim(BaseModel):
    """One assertion about a problem, as reported by a source."""

    model_config = {"extra": "forbid"}

    claimType: str
    resultType: str
    modelName: Optional[str] = None
    organization: Optional[str] = None
    claimedAt: Optional[str] = None
    summary: Optional[str] = None
    observationId: str
    sourceUrl: Optional[str] = None
    recordedAt: str


class Candidate(BaseModel):
    """A proposed result. Never presented as verified, never auto-promoted."""

    model_config = {"extra": "forbid"}

    id: str
    canonicalName: str
    aliases: list[str] = Field(default_factory=list)
    family: Optional[str] = None
    mathematicalField: Optional[str] = None
    externalIds: dict[str, list[str]] = Field(default_factory=dict)

    problemRef: Optional[str] = None      # curated results.json id, when matched
    status: str = "pending"               # pending | promoted | rejected — human-set

    claims: list[Claim] = Field(default_factory=list)
    observationIds: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    firstSeenAt: str
    lastSeenAt: str


class MergeReport(BaseModel):
    candidatesCreated: int = 0
    candidatesUpdated: int = 0
    claimsAdded: int = 0
    sourcesAttached: int = 0
    reviewsCreated: int = 0
    decisions: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


def _claim_from(obs: dict, now: str) -> Claim:
    ex = obs.get("extraction") or {}
    return Claim(
        claimType=ex.get("claimType") or "unrelated",
        resultType=ex.get("resultType") or "unknown",
        modelName=ex.get("modelName"),
        organization=ex.get("claimingOrganization"),
        claimedAt=ex.get("claimedAt"),
        summary=ex.get("summary"),
        observationId=obs["id"],
        sourceUrl=obs.get("url"),
        recordedAt=now,
    )


def _same_claim(a: Claim, b: Claim) -> bool:
    """Two claims are the same assertion if they say the same thing about the
    same result, regardless of who posted it."""
    return (a.claimType, a.resultType, (a.modelName or "").lower()) == (
        b.claimType, b.resultType, (b.modelName or "").lower()
    )


def _upsert_candidate(
    candidates: list[dict], obs: dict, outcome: MatchOutcome, now: str
) -> tuple[list[dict], str, bool, bool, bool]:
    """Create or extend a candidate. Returns
    (candidates, candidate_id, created, claim_added, source_attached)."""
    ex = obs.get("extraction") or {}
    name = ex.get("canonicalProblemName") or obs.get("url") or obs["id"]
    ext = obs.get("externalIds") or {}
    cid = make_candidate_id(name, ext)

    by_id = {c["id"]: dict(c) for c in candidates}
    claim = _claim_from(obs, now)
    created = claim_added = source_attached = False

    if cid not in by_id:
        cand = Candidate(
            id=cid,
            canonicalName=name,
            aliases=sorted({a for a in (ex.get("problemAliases") or []) if a}),
            family=ex.get("problemFamily"),
            mathematicalField=ex.get("mathematicalField"),
            externalIds=ext,
            problemRef=outcome.matched_id,
            claims=[claim],
            observationIds=[obs["id"]],
            sources=[obs["url"]] if obs.get("url") else [],
            firstSeenAt=now,
            lastSeenAt=now,
        )
        by_id[cid] = cand.model_dump(mode="json")
        created = claim_added = True
        source_attached = bool(obs.get("url"))
    else:
        cur = by_id[cid]
        cur["lastSeenAt"] = now
        if obs["id"] not in cur.get("observationIds", []):
            cur["observationIds"] = sorted(set(cur.get("observationIds", [])) | {obs["id"]})
        if obs.get("url") and obs["url"] not in cur.get("sources", []):
            cur["sources"] = sorted(set(cur.get("sources", [])) | {obs["url"]})
            source_attached = True
        existing = [Claim(**c) for c in cur.get("claims", [])]
        if not any(_same_claim(existing_claim, claim) for existing_claim in existing):
            cur["claims"] = cur.get("claims", []) + [claim.model_dump(mode="json")]
            claim_added = True
        # identifiers and aliases only ever grow
        merged = dict(cur.get("externalIds") or {})
        for k, v in ext.items():
            merged[k] = sorted(set(merged.get(k, [])) | set(v))
        cur["externalIds"] = merged
        cur["aliases"] = sorted(
            set(cur.get("aliases", [])) | {a for a in (ex.get("problemAliases") or []) if a}
        )
        if outcome.matched_id and not cur.get("problemRef"):
            cur["problemRef"] = outcome.matched_id
        by_id[cid] = cur

    ordered = sorted(by_id.values(), key=lambda c: (c.get("firstSeenAt", ""), c["id"]))
    return ordered, cid, created, claim_added, source_attached


# --------------------------------------------------------------------------
# one handler per decision
# --------------------------------------------------------------------------

def apply_decision(
    decision: str,
    obs: dict,
    outcome: MatchOutcome,
    candidates: list[dict],
    review_queue: list[dict],
    *,
    judge: dict | None = None,
    now: str | None = None,
    policy: dict | None = None,
) -> tuple[list[dict], list[dict], MergeReport]:
    """Apply one decision. Never raises on model input; never writes the registry."""
    now = now or utc_now_iso()
    report = MergeReport()
    report.decisions[decision] = 1
    judge = judge or {}
    ex = obs.get("extraction") or {}
    title = ex.get("canonicalProblemName") or obs.get("url") or obs["id"]

    def review(reason: str, detail: str, **kw) -> None:
        nonlocal review_queue
        entry = ReviewEntry.create(
            reason,  # type: ignore[arg-type]
            title=title,
            detail=detail,
            observation_id=obs.get("id"),
            source_url=obs.get("url"),
            shortlist=[c.to_dict() for c in outcome.shortlist],
            decision=decision,
            judge_confidence=judge.get("confidence"),
            conflicting_fields=judge.get("conflictingFields") or [],
            now=now,
            **kw,
        )
        review_queue, created = upsert(review_queue, entry)
        if created:
            report.reviewsCreated += 1

    # -- decisions that never touch candidates -----------------------------

    if decision == "same_source_duplicate":
        report.notes.append("already known source; nothing to do")
        return candidates, review_queue, report

    if decision == "same_problem_conflicting_claim":
        # Both readings are preserved. Neither overwrites the other, and no
        # curated record moves.
        review("conflicting_claim",
               f"This post contradicts what is recorded for {outcome.matched_id or 'a matched problem'}. "
               "Both claims are preserved; nothing was overwritten.",
               problem_ref=outcome.matched_id)
        return candidates, review_queue, report

    if decision == "related_problem":
        review("related_problem",
               "Connected to an existing problem but not the same one — recorded, not merged.",
               problem_ref=outcome.matched_id)
        return candidates, review_queue, report

    if decision == "insufficient_information":
        review("insufficient_information",
               "The post does not give enough to identify the problem.")
        return candidates, review_queue, report

    # -- decisions that may create or extend a candidate --------------------

    if decision in ("same_problem_same_claim", "same_problem_new_claim", "distinct_problem"):
        ok_conf, why_conf = meets_confidence(obs, policy)
        if not ok_conf:
            review("low_confidence", why_conf)
            return candidates, review_queue, report

        ok_corr, why_corr = may_become_candidate(obs, policy)
        if not ok_corr:
            # The corroboration gate. This is the common path for X, by design.
            review("no_corroboration", why_corr, problem_ref=outcome.matched_id)
            return candidates, review_queue, report

        candidates, cid, created, claim_added, src = _upsert_candidate(
            candidates, obs, outcome, now
        )
        report.candidatesCreated += int(created)
        report.candidatesUpdated += int(not created)
        report.claimsAdded += int(claim_added)
        report.sourcesAttached += int(src)
        report.notes.append(f"{decision}: candidate {cid} ({why_corr})")
        return candidates, review_queue, report

    # -- anything unrecognised is a question, not a default -----------------
    review("ambiguous_identity", f"unhandled decision {decision!r} — routed to review")
    return candidates, review_queue, report


def decide(outcome: MatchOutcome, judge: dict | None = None) -> str:
    """Turn a match outcome (plus an optional judge verdict) into a decision.

    Deterministic outcomes decide themselves. The judge is consulted only where
    matching already said it could not tell.
    """
    if outcome.conflict:
        return "insufficient_information"

    if outcome.method in ("identifier", "alias") and outcome.matched_id:
        return "same_problem_new_claim"

    if outcome.method == "lexical" and outcome.matched_id and not outcome.needs_judge:
        return "same_problem_new_claim"

    if outcome.method == "none":
        return "distinct_problem"

    if outcome.needs_judge:
        if not judge:
            return "insufficient_information"     # judge failed → never guess
        if judge.get("requiresHumanReview"):
            return judge.get("decision") or "insufficient_information"
        return judge.get("decision") or "insufficient_information"

    return "insufficient_information"
