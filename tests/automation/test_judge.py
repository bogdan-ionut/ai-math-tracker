"""Sprint 5.2 — the judge path, end to end.

These tests exist because the judge path had *no* end-to-end coverage. The
helper in test_merge.py defaults to `method="identifier", matched="erdos-728"`,
so every test took the deterministic branch and four defects survived a 232-test
suite:

  A1  the judge's matchedProblemId was never read
  A2  requiresHumanReview was read into two identical branches
  A3  "we did not ask the judge" was recorded as "the judge could not tell"
  A4  a registry identifier collision was erased into insufficient_information

Every test below fails against the pre-5.2 code.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.automation.matching import Candidate as MatchCandidate
from scripts.automation.matching import MatchOutcome
from scripts.automation.merge import apply_decision, resolve
from scripts.automation.review import summarize

ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-07-25T12:00:00+00:00"


def obs(*, oid="obs_j", ext=None, conf=0.9, name="Erdős problem about primes"):
    return {
        "id": oid, "url": "https://x.com/a/status/9", "author": "a",
        "sourceCreatedAt": "Thu Jul 23 14:00:00 +0000 2026", "text": "a post",
        "externalIds": ext if ext is not None else {"erdos": ["728"]},
        "extractionConfidence": conf,
        "extraction": {
            "canonicalProblemName": name, "problemAliases": [], "problemFamily": "Erdős",
            "claimType": "new_result", "resultType": "proof", "modelName": "GPT-5.6",
            "claimingOrganization": "OpenAI", "claimedAt": "2026-07-23", "summary": "s",
        },
    }


def ambiguous(*ids: str) -> MatchOutcome:
    """The only shape that reaches the judge: lexical, unresolved, shortlisted."""
    return MatchOutcome(
        "lexical", None,
        [MatchCandidate(i, f"Title {i}", 80.0, "lexical", "close name") for i in ids],
        needs_judge=True,
    )


def verdict(decision="same_problem_new_claim", *, matched="erdos-728",
            confidence=0.95, review=False, conflicting=None):
    v = {"decision": decision, "confidence": confidence, "requiresHumanReview": review}
    if matched is not None:
        v["matchedProblemId"] = matched
    if conflicting:
        v["conflictingFields"] = conflicting
    return v


# ================================================================ A1

class TestJudgeIdentityIsUsed:
    """The judge is asked exactly one question. Its answer must survive."""

    def test_matched_id_is_taken_from_the_verdict(self):
        r = resolve(ambiguous("erdos-728", "erdos-782"), verdict(matched="erdos-728"),
                    judge_status="ok")
        assert r.matched_id == "erdos-728", "the judge's answer was discarded"

    def test_candidate_records_the_judged_problem(self):
        r = resolve(ambiguous("erdos-728", "erdos-782"), verdict(matched="erdos-728"),
                    judge_status="ok")
        cands, _, rep = apply_decision(r, obs(), ambiguous("erdos-728"), [], [], now=NOW)
        assert rep.candidatesCreated == 1
        assert cands[0]["problemRef"] == "erdos-728", (
            "a judge-resolved candidate must not be created unlinked"
        )

    def test_conflicting_claim_names_the_contradicted_record(self):
        """Reachable only through the judge, so it always lost the link before."""
        out = ambiguous("erdos-728", "erdos-782")
        r = resolve(out, verdict("same_problem_conflicting_claim", matched="erdos-728",
                                 conflicting=["resultType"]), judge_status="ok")
        _, queue, _ = apply_decision(r, obs(), out, [], [], now=NOW)
        entry = queue[0]
        assert entry["reason"] == "conflicting_claim"
        assert entry["problemRef"] == "erdos-728"
        assert "a matched problem" not in entry["detail"], (
            "the curator must be told which record, not that there was one"
        )

    def test_related_problem_names_the_related_record(self):
        out = ambiguous("erdos-728")
        r = resolve(out, verdict("related_problem", matched="erdos-728"), judge_status="ok")
        _, queue, _ = apply_decision(r, obs(), out, [], [], now=NOW)
        assert queue[0]["problemRef"] == "erdos-728"

    # --- the model must not be able to invent an id ---------------------

    def test_id_outside_the_shortlist_is_rejected(self):
        """The judge only ever sees the shortlist; anything else is invented."""
        r = resolve(ambiguous("erdos-728", "erdos-782"),
                    verdict(matched="jacobian-conjecture-1939"), judge_status="ok")
        assert r.matched_id is None
        assert r.forced_review == "judge_uncertain"
        assert any("not in the shortlist" in n for n in r.notes)

    def test_invented_id_never_reaches_a_candidate(self):
        out = ambiguous("erdos-728")
        r = resolve(out, verdict(matched="totally-made-up"), judge_status="ok")
        cands, queue, rep = apply_decision(r, obs(), out, [], [], now=NOW)
        assert cands == [] and rep.candidatesCreated == 0
        assert queue[0]["reason"] == "judge_uncertain"

    def test_missing_matched_id_is_tolerated(self):
        """The schema does not require it; distinct_problem legitimately omits it."""
        out = ambiguous("erdos-728")
        r = resolve(out, verdict("distinct_problem", matched=None), judge_status="ok")
        assert r.decision == "distinct_problem" and r.matched_id is None
        assert r.forced_review is None


# ================================================================ A2

class TestRequiresHumanReviewIsHonoured:
    def test_flag_routes_to_review_instead_of_a_candidate(self):
        out = ambiguous("erdos-728")
        r = resolve(out, verdict(review=True), judge_status="ok")
        cands, queue, rep = apply_decision(r, obs(), out, [], [], now=NOW)
        assert rep.candidatesCreated == 0, (
            "a verdict the model itself flagged as unsafe must not create a candidate"
        )
        assert queue[0]["reason"] == "judge_uncertain"

    def test_low_judge_confidence_routes_to_review(self):
        out = ambiguous("erdos-728")
        r = resolve(out, verdict(confidence=0.2), judge_status="ok")
        assert r.forced_review == "judge_uncertain"

    def test_high_confidence_without_the_flag_proceeds(self):
        out = ambiguous("erdos-728")
        r = resolve(out, verdict(confidence=0.95, review=False), judge_status="ok")
        assert r.forced_review is None

    def test_the_decision_is_preserved_on_the_review_entry(self):
        """A curator should see what the judge thought, even when overridden."""
        out = ambiguous("erdos-728")
        r = resolve(out, verdict("same_problem_conflicting_claim", review=True),
                    judge_status="ok")
        _, queue, _ = apply_decision(r, obs(), out, [], [], now=NOW)
        assert queue[0]["decision"] == "same_problem_conflicting_claim"
        assert queue[0]["judgeConfidence"] == 0.95


# ================================================================ A3

class TestUnavailabilityIsNotUncertainty:
    @pytest.mark.parametrize("status", ["unavailable", "budget_exhausted"])
    def test_not_asking_defers_rather_than_concluding(self, status):
        r = resolve(ambiguous("erdos-728"), None, judge_status=status)
        assert r.deferred is True, (
            "no key or no budget is an operational fact, not a conclusion about the post"
        )

    @pytest.mark.parametrize("status", ["unavailable", "budget_exhausted"])
    def test_deferred_mutates_nothing(self, status):
        out = ambiguous("erdos-728")
        r = resolve(out, None, judge_status=status)
        cands, queue, rep = apply_decision(r, obs(), out, [], [], now=NOW)
        assert cands == [] and queue == []
        assert rep.reviewsCreated == 0, "a deferred observation must not fill the queue"

    def test_judge_error_is_recorded_as_such(self):
        r = resolve(ambiguous("erdos-728"), None, judge_status="failed")
        assert r.deferred is False
        assert r.forced_review == "judge_failed"

    def test_judge_error_creates_no_candidate(self):
        out = ambiguous("erdos-728")
        r = resolve(out, None, judge_status="failed")
        cands, queue, _ = apply_decision(r, obs(), out, [], [], now=NOW)
        assert cands == [] and queue[0]["reason"] == "judge_failed"

    def test_a_real_cannot_tell_verdict_is_terminal(self):
        out = ambiguous("erdos-728")
        r = resolve(out, verdict("insufficient_information", matched=None), judge_status="ok")
        assert r.deferred is False
        _, queue, _ = apply_decision(r, obs(), out, [], [], now=NOW)
        assert queue[0]["reason"] == "insufficient_information"


# ================================================================ A4

class TestRegistryConflictSurfaces:
    def test_collision_is_reported_as_a_registry_bug(self):
        out = MatchOutcome(
            "conflict", None,
            [MatchCandidate("erdos-728", "Erdős #728", 100.0, "identifier", "shares erdos:728"),
             MatchCandidate("dupe", "Duplicate", 100.0, "identifier", "shares erdos:728")],
            needs_judge=False, conflict=True,
            notes=["identifier matches more than one curated record"],
        )
        r = resolve(out, None, judge_status="not_needed")
        assert r.forced_review == "registry_conflict"
        _, queue, _ = apply_decision(r, obs(), out, [], [], now=NOW)
        entry = queue[0]
        assert entry["reason"] == "registry_conflict"
        assert "erdos-728" in str(entry["shortlist"]) and "dupe" in str(entry["shortlist"])

    def test_collision_never_asks_the_judge(self):
        out = MatchOutcome("conflict", None, [], needs_judge=False, conflict=True,
                           notes=["collision"])
        assert resolve(out, None, judge_status="not_needed").deferred is False

    def test_matcher_notes_reach_the_curator(self):
        out = MatchOutcome("conflict", None, [], needs_judge=False, conflict=True,
                           notes=["identifier matches more than one curated record"])
        r = resolve(out, None, judge_status="not_needed")
        _, queue, _ = apply_decision(r, obs(), out, [], [], now=NOW)
        assert "more than one curated record" in queue[0]["detail"]


# ================================================================ A5

class TestNoDeadReviewReasons:
    def test_every_declared_reason_has_an_emitter(self):
        """Invariant D39. A reason nobody emits makes the queue look more
        discriminating than it is."""
        import inspect

        from scripts.automation import merge
        from scripts.automation.review import ReviewReason

        declared = set(ReviewReason.__args__)
        source = inspect.getsource(merge)
        emitted = {r for r in declared if f'"{r}"' in source}
        missing = declared - emitted - {"attempted_protected_write"}
        assert not missing, f"declared but never emitted: {sorted(missing)}"


# ================================================================ determinism preserved

class TestDeterministicPathUnchanged:
    """5.2 must not weaken what already worked."""

    def test_identifier_match_still_skips_the_judge(self):
        out = MatchOutcome("identifier", "erdos-728",
                           [MatchCandidate("erdos-728", "E", 100.0, "identifier", "id")],
                           needs_judge=False)
        r = resolve(out, None, judge_status="not_needed")
        assert r.decision == "same_problem_new_claim" and r.matched_id == "erdos-728"
        assert not r.deferred and r.forced_review is None

    def test_no_match_is_still_distinct(self):
        out = MatchOutcome("none", None, [], needs_judge=False)
        assert resolve(out, None, judge_status="not_needed").decision == "distinct_problem"

    def test_registry_still_untouched_across_the_judge_path(self):
        results = ROOT / "data" / "results.json"
        before = results.read_bytes()
        out = ambiguous("erdos-728", "erdos-782")
        for v, st in ((verdict(), "ok"), (verdict(review=True), "ok"),
                      (None, "failed"), (None, "unavailable")):
            r = resolve(out, v, judge_status=st)
            apply_decision(r, obs(), out, [], [], now=NOW)
        assert results.read_bytes() == before

    def test_summarize_still_counts_open_entries(self):
        out = ambiguous("erdos-728")
        r = resolve(out, None, judge_status="failed")
        _, queue, _ = apply_decision(r, obs(), out, [], [], now=NOW)
        assert summarize(queue) == {"judge_failed": 1}
