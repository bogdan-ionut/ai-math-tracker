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

from dataclasses import dataclass, field as dc_field
from typing import Literal, Optional

from pydantic import BaseModel, Field

from scripts.automation.ids import candidate_id as make_candidate_id
from scripts.automation.matching import MatchOutcome
from scripts.automation.models import utc_now_iso
from scripts.automation.policy import (
    load_policy,
    may_become_candidate,
    meets_confidence,
)
from scripts.automation.review import ReviewEntry, upsert


JudgeStatus = Literal["not_needed", "ok", "failed", "unavailable", "budget_exhausted"]


@dataclass
class Resolution:
    """What the pipeline concluded, and how it got there.

    Replaces the old `decide() -> str`. A bare string could not express the two
    distinctions that matter:

      * **deferred** — we never asked the judge (no key, no budget). That is an
        operational fact about us, not a conclusion about the post, so the
        observation must be left alone and retried, never filed as though the
        model had said it could not tell.
      * **forced_review** — a decision was reached but must not be acted on
        (the model flagged it, or the registry itself is inconsistent).
    """

    decision: str
    matched_id: Optional[str] = None
    deferred: bool = False
    forced_review: Optional[str] = None
    judge: Optional[dict] = None
    notes: list[str] = dc_field(default_factory=list)


def _validated_match(judge: dict, outcome: MatchOutcome) -> tuple[Optional[str], list[str]]:
    """Take the judge's chosen id, but only if we actually offered it.

    `build_judge_payload` shows the model exactly the shortlist, so anything
    else is invented. An invented id would be written to `problemRef` and then
    treated downstream as a hard link to a curated record.
    """
    claimed = (judge or {}).get("matchedProblemId")
    if not claimed:
        return None, []
    offered = {c.record_id for c in outcome.shortlist}
    if claimed in offered:
        return claimed, []
    return None, [f"judge returned {claimed!r}, which is not in the shortlist it was shown"]


def resolve(
    outcome: MatchOutcome,
    judge: dict | None = None,
    *,
    judge_status: JudgeStatus = "not_needed",
    policy: dict | None = None,
) -> Resolution:
    """Turn a match outcome plus an optional judge verdict into a resolution.

    Deterministic outcomes resolve themselves; the judge is consulted only where
    matching already said it could not tell.
    """
    policy = policy if policy is not None else load_policy()

    # A registry collision is a bug in curated data, not an ambiguity about the
    # post. Say so, and carry the colliding ids to the curator.
    if outcome.conflict:
        return Resolution("insufficient_information", None,
                          forced_review="registry_conflict", notes=list(outcome.notes))

    if outcome.method == "identifier" and outcome.matched_id:
        return Resolution("same_problem_new_claim", outcome.matched_id)

    if outcome.method in ("alias", "lexical") and outcome.matched_id and not outcome.needs_judge:
        if outcome.conflicting_ids:
            # Matched on a *name* while this observation's explicit identifiers
            # disagree with other records. Erdős #728 and #782 look alike and are
            # not the same problem, so a name winning here is exactly the case a
            # human should see rather than a merge we perform quietly.
            return Resolution(
                "same_problem_new_claim", outcome.matched_id,
                forced_review="identifier_conflict",
                notes=[
                    f"matched {outcome.matched_id!r} by {outcome.method}, but this "
                    f"observation's identifiers disagree with "
                    f"{', '.join(outcome.conflicting_ids)}"
                ],
            )
        return Resolution("same_problem_new_claim", outcome.matched_id)

    if outcome.method == "none":
        return Resolution("distinct_problem", None)

    if outcome.needs_judge:
        if judge_status in ("unavailable", "budget_exhausted"):
            # Never asked. Leave the observation exactly as it was.
            return Resolution("deferred", None, deferred=True,
                              notes=[f"judge not consulted ({judge_status})"])
        if judge_status == "failed" or not judge:
            return Resolution("insufficient_information", None,
                              forced_review="judge_failed",
                              notes=["the judge call failed; nothing was inferred"])

        matched, notes = _validated_match(judge, outcome)
        decision = judge.get("decision") or "insufficient_information"
        floor = float(policy.get("minJudgeConfidence", 0.7))
        confidence = float(judge.get("confidence") or 0.0)

        if notes:                                   # invented id
            return Resolution(decision, None, forced_review="judge_uncertain",
                              judge=judge, notes=notes)
        if judge.get("requiresHumanReview"):
            return Resolution(decision, matched, forced_review="judge_uncertain",
                              judge=judge,
                              notes=["the judge asked for human review"])
        if confidence < floor:
            return Resolution(decision, matched, forced_review="judge_uncertain",
                              judge=judge,
                              notes=[f"judge confidence {confidence:.2f} below {floor:.2f}"])
        return Resolution(decision, matched, judge=judge)

    return Resolution("insufficient_information", None)


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
    candidates: list[dict], obs: dict, matched_id: str | None, now: str
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
            problemRef=matched_id,
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
        if matched_id and not cur.get("problemRef"):
            cur["problemRef"] = matched_id
        by_id[cid] = cur

    ordered = sorted(by_id.values(), key=lambda c: (c.get("firstSeenAt", ""), c["id"]))
    return ordered, cid, created, claim_added, source_attached


# --------------------------------------------------------------------------
# one handler per decision
# --------------------------------------------------------------------------

def apply_decision(
    resolution: Resolution,
    obs: dict,
    outcome: MatchOutcome,
    candidates: list[dict],
    review_queue: list[dict],
    *,
    now: str | None = None,
    policy: dict | None = None,
) -> tuple[list[dict], list[dict], MergeReport]:
    """Apply one resolution. Never raises on model input; never writes the registry."""
    now = now or utc_now_iso()
    report = MergeReport()
    decision = resolution.decision
    report.decisions[decision] = 1
    judge = resolution.judge or {}
    ex = obs.get("extraction") or {}
    title = ex.get("canonicalProblemName") or obs.get("url") or obs["id"]

    def review(reason: str, detail: str, problem_ref: str | None = None) -> None:
        nonlocal review_queue
        # Matcher and resolver notes explain *why*; without them the curator sees
        # a verdict with no reasoning.
        full = " ".join([detail, *resolution.notes, *outcome.notes]).strip()
        entry = ReviewEntry.create(
            reason,  # type: ignore[arg-type]
            title=title,
            detail=full,
            observation_id=obs.get("id"),
            problem_ref=problem_ref if problem_ref is not None else resolution.matched_id,
            source_url=obs.get("url"),
            shortlist=[c.to_dict() for c in outcome.shortlist],
            decision=decision,
            judge_confidence=judge.get("confidence"),
            conflicting_fields=judge.get("conflictingFields") or [],
            now=now,
        )
        review_queue, created = upsert(review_queue, entry)
        if created:
            report.reviewsCreated += 1

    # -- never asked the judge: change nothing at all ----------------------

    if resolution.deferred:
        report.notes.append(
            "deferred — the judge was not consulted, so this is retried next run"
        )
        return candidates, review_queue, report

    # -- a decision was reached but must not be acted on -------------------

    if resolution.forced_review:
        reasons = {
            "registry_conflict":
                "One identifier matches more than one curated record. This is a bug in "
                "data/results.json, not an ambiguity about the post — the registry needs "
                "fixing.",
            "judge_failed":
                "The judge call did not return a usable verdict. Nothing was inferred.",
            "judge_uncertain":
                f"The judge proposed {decision!r} but it must not be applied unreviewed.",
            "identifier_conflict":
                "Matched by name while explicit identifiers disagree. Near-miss problem "
                "numbers look alike; confirm before this is treated as the same problem.",
        }
        review(resolution.forced_review,
               reasons.get(resolution.forced_review, "Routed to review."))
        return candidates, review_queue, report

    # -- decisions that never touch candidates -----------------------------

    if decision == "same_source_duplicate":
        report.notes.append("already known source; nothing to do")
        return candidates, review_queue, report

    if decision == "same_problem_conflicting_claim":
        # Both readings are preserved. Neither overwrites the other, and no
        # curated record moves.
        target = resolution.matched_id
        review("conflicting_claim",
               f"This post contradicts what is recorded for "
               f"{target or 'an unidentified problem'}. "
               "Both claims are preserved; nothing was overwritten.")
        return candidates, review_queue, report

    if decision == "related_problem":
        review("related_problem",
               f"Connected to {resolution.matched_id or 'an existing problem'} but not the "
               "same one — recorded, not merged.")
        return candidates, review_queue, report

    if decision == "insufficient_information":
        review("insufficient_information",
               "Not enough information to identify the problem.")
        return candidates, review_queue, report

    # -- decisions that may create or extend a candidate --------------------

    if decision in ("same_problem_same_claim", "same_problem_new_claim", "distinct_problem"):
        ok_conf, why_conf = meets_confidence(obs, policy)
        if not ok_conf:
            review("low_confidence", why_conf)
            return candidates, review_queue, report

        ok_corr, why_corr = may_become_candidate(obs, policy)
        if not ok_corr:
            # The external-reference gate. This is the common path for X, by design.
            review("no_corroboration", why_corr)
            return candidates, review_queue, report

        candidates, cid, created, claim_added, src = _upsert_candidate(
            candidates, obs, resolution.matched_id, now
        )
        report.candidatesCreated += int(created)
        report.candidatesUpdated += int(not created)
        report.claimsAdded += int(claim_added)
        report.sourcesAttached += int(src)
        report.notes.append(f"{decision}: candidate {cid} ({why_corr})")
        return candidates, review_queue, report

    # -- anything unrecognised is a question, not a default -----------------
    review("ambiguous_identity", f"Unhandled decision {decision!r} — routed to review.")
    return candidates, review_queue, report
