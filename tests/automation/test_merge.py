"""Sprint 4 tests: the merge engine, the guardrails, and the review queue.

These are the tests the whole project rests on. If any of them fails, the site
can publish something it promises it never publishes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.automation.matching import Candidate as MatchCandidate
from scripts.automation.matching import MatchOutcome
from scripts.automation.merge import apply_decision, decide
from scripts.automation.policy import (
    PolicyViolation,
    assert_no_editorial_write,
    assert_registry_untouched,
    has_corroboration,
    may_become_candidate,
    meets_confidence,
    never_auto_write,
)
from scripts.automation.review import ReviewEntry, open_entries, summarize, upsert

ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-07-25T12:00:00+00:00"


def obs(*, oid="obs_1", ext=None, conf=0.9, name="Erdős #728", url="https://x.com/a/status/1",
        claim="new_result", result="proof", model="GPT-5.6") -> dict:
    return {
        "id": oid, "url": url, "author": "a", "sourceCreatedAt": "Thu Jul 23 14:00:00 +0000 2026",
        "text": "some post", "externalIds": ext if ext is not None else {"erdos": ["728"]},
        "extractionConfidence": conf,
        "extraction": {
            "canonicalProblemName": name, "problemAliases": [], "problemFamily": "Erdős",
            "mathematicalField": "number theory", "claimType": claim, "resultType": result,
            "modelName": model, "claimingOrganization": "OpenAI", "claimedAt": "2026-07-23",
            "summary": "a summary",
        },
    }


def outcome(method="identifier", matched="erdos-728", needs_judge=False, conflict=False):
    return MatchOutcome(
        method, matched,
        [MatchCandidate(matched or "x", "Erdős #728", 100.0, method, "why")] if matched else [],
        needs_judge=needs_judge, conflict=conflict,
    )


# ================================================================ guardrails

class TestFieldAllowlist:
    def test_protected_fields_are_configured(self):
        assert {"status", "auditedAt", "impact", "assessment"} <= never_auto_write()

    def test_unprotected_change_is_allowed(self):
        assert_no_editorial_write({"title": "a"}, {"title": "a", "sources": ["x"]})

    @pytest.mark.parametrize("field,new", [
        ("impact", 5), ("assessment", "very important"), ("auditedAt", "2026-07-25"),
        ("confidence", 0.99), ("auditNotes", "looks fine"), ("provenanceNote", "note"),
    ])
    def test_every_protected_field_is_blocked(self, field, new):
        with pytest.raises(PolicyViolation) as e:
            assert_no_editorial_write({field: None}, {field: new})
        assert field in str(e.value)

    def test_promoting_to_audited_is_blocked(self):
        """The single most important prohibition in the project."""
        with pytest.raises(PolicyViolation) as e:
            assert_no_editorial_write({"status": "provisional"}, {"status": "audited"})
        assert "human decision" in str(e.value)

    def test_impact_plus_assessment_together_still_blocked(self):
        """The schema would accept this pair; the allowlist must not."""
        with pytest.raises(PolicyViolation):
            assert_no_editorial_write(
                {"impact": None, "assessment": None},
                {"impact": 5, "assessment": "justified"},
            )

    def test_registry_diff_is_rejected(self):
        before = [{"id": "a", "title": "A"}]
        with pytest.raises(PolicyViolation) as e:
            assert_registry_untouched(before, [{"id": "a", "title": "A modified"}])
        assert "changed=['a']" in str(e.value)

    def test_registry_deletion_is_rejected(self):
        with pytest.raises(PolicyViolation) as e:
            assert_registry_untouched([{"id": "a"}, {"id": "b"}], [{"id": "a"}])
        assert "removed=['b']" in str(e.value)

    def test_identical_registry_passes(self):
        recs = [{"id": "a", "title": "A"}]
        assert_registry_untouched(recs, json.loads(json.dumps(recs)))


class TestCorroborationGate:
    def test_identifier_corroborates(self):
        ok, why = may_become_candidate(obs(ext={"arxiv": ["2604.03789"]}))
        assert ok and "arxiv" in why

    def test_bare_post_is_gated(self):
        ok, why = may_become_candidate(obs(ext={}))
        assert not ok and "not evidence" in why

    def test_empty_identifier_lists_do_not_count(self):
        assert not has_corroboration(obs(ext={"arxiv": [], "erdos": []}))

    @pytest.mark.parametrize("kind", ["arxiv", "doi", "oeis", "erdos", "github", "lean"])
    def test_each_identifier_kind_corroborates(self, kind):
        assert has_corroboration(obs(ext={kind: ["x"]}))

    def test_gate_can_be_disabled_deliberately(self):
        ok, why = may_become_candidate(obs(ext={}), {"requireCorroborationForCandidate": False})
        assert ok and "disabled" in why

    def test_confidence_floor(self):
        assert meets_confidence(obs(conf=0.9))[0]
        assert not meets_confidence(obs(conf=0.1))[0]


# ================================================================ decisions

class TestDecide:
    def test_identifier_match_decides_itself(self):
        assert decide(outcome("identifier")) == "same_problem_new_claim"

    def test_alias_match_decides_itself(self):
        assert decide(outcome("alias")) == "same_problem_new_claim"

    def test_no_match_is_distinct(self):
        assert decide(outcome("none", matched=None)) == "distinct_problem"

    def test_registry_conflict_never_guesses(self):
        assert decide(outcome("conflict", matched=None, conflict=True)) == "insufficient_information"

    def test_judge_failure_never_guesses(self):
        """A missing judge verdict must not fall through to a merge."""
        assert decide(outcome("lexical", None, needs_judge=True), judge=None) == \
            "insufficient_information"

    def test_judge_verdict_is_used_when_present(self):
        d = decide(outcome("lexical", None, needs_judge=True),
                   judge={"decision": "same_problem_new_claim", "requiresHumanReview": False})
        assert d == "same_problem_new_claim"


# ================================================================ handlers

class TestHandlers:
    def test_new_claim_creates_candidate(self):
        cands, rev, rep = apply_decision("same_problem_new_claim", obs(), outcome(), [], [], now=NOW)
        assert rep.candidatesCreated == 1 and len(cands) == 1
        assert cands[0]["problemRef"] == "erdos-728"
        assert cands[0]["status"] == "pending", "a candidate is never born promoted"

    def test_uncorroborated_goes_to_review_not_candidates(self):
        cands, rev, rep = apply_decision(
            "distinct_problem", obs(ext={}), outcome("none", None), [], [], now=NOW
        )
        assert cands == [] and rep.candidatesCreated == 0
        assert rep.reviewsCreated == 1 and rev[0]["reason"] == "no_corroboration"

    def test_low_confidence_goes_to_review(self):
        _, rev, rep = apply_decision("distinct_problem", obs(conf=0.1), outcome("none", None),
                                     [], [], now=NOW)
        assert rev[0]["reason"] == "low_confidence" and rep.candidatesCreated == 0

    def test_conflicting_claim_preserves_both_and_creates_review(self):
        cands, rev, rep = apply_decision("same_problem_conflicting_claim", obs(), outcome(),
                                         [], [], now=NOW)
        assert cands == [], "a conflict must not silently create or edit anything"
        assert rev[0]["reason"] == "conflicting_claim"
        assert "preserved" in rev[0]["detail"]

    def test_related_problem_does_not_merge(self):
        cands, rev, _ = apply_decision("related_problem", obs(), outcome(), [], [], now=NOW)
        assert cands == [] and rev[0]["reason"] == "related_problem"

    def test_duplicate_source_is_a_no_op(self):
        cands, rev, rep = apply_decision("same_source_duplicate", obs(), outcome(), [], [], now=NOW)
        assert cands == [] and rev == [] and rep.reviewsCreated == 0

    def test_insufficient_information_reviews(self):
        _, rev, _ = apply_decision("insufficient_information", obs(), outcome(), [], [], now=NOW)
        assert rev[0]["reason"] == "insufficient_information"

    def test_unknown_decision_is_reviewed_not_ignored(self):
        _, rev, rep = apply_decision("something_new", obs(), outcome(), [], [], now=NOW)
        assert rep.reviewsCreated == 1 and rev[0]["reason"] == "ambiguous_identity"

    def test_second_observation_extends_rather_than_duplicates(self):
        cands, _, _ = apply_decision("same_problem_new_claim", obs(oid="o1"), outcome(), [], [], now=NOW)
        cands, _, rep = apply_decision(
            "same_problem_new_claim",
            obs(oid="o2", url="https://x.com/b/status/2", model="Gemini"),
            outcome(), cands, [], now=NOW,
        )
        assert len(cands) == 1, "same problem must not create a second candidate"
        assert rep.candidatesUpdated == 1
        assert len(cands[0]["claims"]) == 2 and len(cands[0]["sources"]) == 2

    def test_identical_claim_is_not_duplicated(self):
        cands, _, _ = apply_decision("same_problem_same_claim", obs(oid="o1"), outcome(), [], [], now=NOW)
        cands, _, rep = apply_decision(
            "same_problem_same_claim", obs(oid="o2", url="https://x.com/b/status/2"),
            outcome(), cands, [], now=NOW,
        )
        assert len(cands[0]["claims"]) == 1, "the same assertion twice is still one claim"
        assert rep.sourcesAttached == 1, "but the new source is still attached"


# ================================================================ idempotency

class TestIdempotency:
    def test_rerunning_changes_nothing(self):
        c1, r1, _ = apply_decision("same_problem_new_claim", obs(), outcome(), [], [], now=NOW)
        c2, r2, rep = apply_decision("same_problem_new_claim", obs(), outcome(), c1, r1, now=NOW)
        assert c1 == c2 and r1 == r2
        assert rep.candidatesCreated == 0 and rep.claimsAdded == 0

    def test_review_entries_are_not_duplicated(self):
        _, r1, _ = apply_decision("insufficient_information", obs(), outcome(), [], [], now=NOW)
        _, r2, rep = apply_decision("insufficient_information", obs(), outcome(), [], r1, now=NOW)
        assert len(r2) == 1 and rep.reviewsCreated == 0

    def test_resolved_review_is_not_reopened(self):
        _, r1, _ = apply_decision("insufficient_information", obs(), outcome(), [], [], now=NOW)
        r1[0]["status"] = "resolved"
        _, r2, rep = apply_decision("insufficient_information", obs(), outcome(), [], r1, now=NOW)
        assert r2[0]["status"] == "resolved", "a human already answered this"
        assert rep.reviewsCreated == 0

    def test_different_reason_same_subject_gets_its_own_entry(self):
        _, r1, _ = apply_decision("insufficient_information", obs(), outcome(), [], [], now=NOW)
        _, r2, _ = apply_decision("related_problem", obs(), outcome(), [], r1, now=NOW)
        assert len(r2) == 2


# ================================================================ review queue

class TestReviewQueue:
    def test_stable_ids(self):
        a = ReviewEntry.create("no_corroboration", title="t", detail="d", observation_id="o1")
        b = ReviewEntry.create("no_corroboration", title="t", detail="d2", observation_id="o1")
        assert a.id == b.id

    def test_upsert_keeps_richer_detail(self):
        q, _ = upsert([], ReviewEntry.create("no_corroboration", title="t", detail="short",
                                             observation_id="o1"))
        q, created = upsert(q, ReviewEntry.create("no_corroboration", title="t",
                                                  detail="a much longer explanation",
                                                  observation_id="o1"))
        assert not created and q[0]["detail"] == "a much longer explanation"

    def test_summarize_counts_open_only(self):
        q, _ = upsert([], ReviewEntry.create("no_corroboration", title="t", detail="d",
                                             observation_id="o1"))
        q, _ = upsert(q, ReviewEntry.create("conflicting_claim", title="t2", detail="d",
                                            observation_id="o2"))
        q[0]["status"] = "dismissed"
        assert summarize(q) == {"conflicting_claim": 1}
        assert len(open_entries(q)) == 1


# ================================================================ end to end

class TestRegistryIsUntouchable:
    def test_full_decision_sweep_never_writes_results_json(self):
        """Run every decision and assert the curated file is byte-identical."""
        results = ROOT / "data" / "results.json"
        before = results.read_bytes()

        cands: list[dict] = []
        queue: list[dict] = []
        for decision in (
            "same_source_duplicate", "same_problem_same_claim", "same_problem_new_claim",
            "same_problem_conflicting_claim", "related_problem", "distinct_problem",
            "insufficient_information", "totally_unknown_decision",
        ):
            cands, queue, _ = apply_decision(
                decision, obs(oid=f"obs_{decision}"), outcome(), cands, queue, now=NOW
            )

        assert results.read_bytes() == before

    def test_no_candidate_carries_an_editorial_field(self):
        cands, _, _ = apply_decision("same_problem_new_claim", obs(), outcome(), [], [], now=NOW)
        blob = json.dumps(cands)
        for banned in ("impact", "assessment", "auditNotes", "auditedAt"):
            assert banned not in blob, f"{banned} must never appear on a candidate"

    def test_candidate_status_is_never_audited(self):
        cands, _, _ = apply_decision("same_problem_new_claim", obs(), outcome(), [], [], now=NOW)
        assert all(c["status"] in ("pending", "promoted", "rejected") for c in cands)
        assert all(c["status"] != "audited" for c in cands)


# ================================================================ full pipeline

class TestPipelineEndToEnd:
    """ingest → extract → match → merge, offline, over the real registry."""

    def _prepare(self, tmp_path, monkeypatch):
        from scripts.automation import store as st
        monkeypatch.setattr(st, "DATA_DIR", tmp_path)
        monkeypatch.setattr(st, "RAW_DIR", tmp_path / "raw")
        return st

    def test_corroborated_post_becomes_a_candidate(self, tmp_path, monkeypatch):
        from scripts.automation import pipeline
        st = self._prepare(tmp_path, monkeypatch)
        o = obs(ext={"erdos": ["728"]})
        o["status"] = "extracted"
        st.write_json(st.observations_path(), [o])

        r = pipeline.run(judge_client=None)
        assert r["ok"] and r["candidatesCreated"] == 1
        cand = st.read_json(st.candidates_path(), [])[0]
        assert cand["problemRef"] == "erdos-728" and cand["status"] == "pending"

    def test_uncorroborated_post_becomes_review_not_candidate(self, tmp_path, monkeypatch):
        """The corroboration gate: a name that matches nothing, and no identifier."""
        from scripts.automation import pipeline
        st = self._prepare(tmp_path, monkeypatch)
        # A name with no token overlap with any curated title, so matching
        # returns cleanly "none" and the gate is what decides the outcome.
        o = obs(ext={}, name="Zzyzx Fnord Qwerty")
        o["status"] = "extracted"
        st.write_json(st.observations_path(), [o])

        r = pipeline.run(judge_client=None)
        assert r["decisions"] == {"distinct_problem": 1}
        assert r["candidatesCreated"] == 0
        assert st.read_json(st.candidates_path(), []) == []
        assert r["reviewOpenByReason"].get("no_corroboration") == 1

    def test_ambiguous_and_uncorroborated_is_still_safe(self, tmp_path, monkeypatch):
        """A vague name shares tokens with real titles, so it goes to the judge
        rather than the gate. With no judge available it must still end in
        review — a different reason, the same refusal to guess."""
        from scripts.automation import pipeline
        st = self._prepare(tmp_path, monkeypatch)
        o = obs(ext={}, name="Some Brand New Conjecture Nobody Has Heard Of")
        o["status"] = "extracted"
        st.write_json(st.observations_path(), [o])

        r = pipeline.run(judge_client=None)
        assert r["candidatesCreated"] == 0
        assert st.read_json(st.candidates_path(), []) == []
        assert sum(r["reviewOpenByReason"].values()) == 1

    def test_pipeline_is_idempotent(self, tmp_path, monkeypatch):
        from scripts.automation import pipeline
        st = self._prepare(tmp_path, monkeypatch)
        o = obs(ext={"erdos": ["728"]})
        o["status"] = "extracted"
        st.write_json(st.observations_path(), [o])

        pipeline.run(judge_client=None)
        c1 = st.read_json(st.candidates_path(), [])
        q1 = st.read_json(st.review_queue_path(), [])

        # re-mark as extracted to force a second pass over the same data
        obs2 = st.read_json(st.observations_path(), [])
        for x in obs2:
            x["status"] = "extracted"
        st.write_json(st.observations_path(), obs2)

        pipeline.run(judge_client=None)
        assert st.read_json(st.candidates_path(), []) == c1
        assert st.read_json(st.review_queue_path(), []) == q1

    def test_judge_budget_exhaustion_is_safe(self, tmp_path, monkeypatch):
        """Running out of judge budget must review, never guess."""
        from scripts.automation import pipeline
        st = self._prepare(tmp_path, monkeypatch)
        o = obs(ext={}, name="Erdős problem")     # ambiguous, needs the judge
        o["status"] = "extracted"
        st.write_json(st.observations_path(), [o])

        r = pipeline.run(judge_client=None, limit=0)
        assert r["judgeCalls"] == 0
        assert st.read_json(st.candidates_path(), []) == []

    def test_registry_untouched_by_full_run(self, tmp_path, monkeypatch):
        from scripts.automation import pipeline
        st = self._prepare(tmp_path, monkeypatch)
        results = ROOT / "data" / "results.json"
        before = results.read_bytes()

        o = obs(ext={"erdos": ["728"]})
        o["status"] = "extracted"
        st.write_json(st.observations_path(), [o])
        pipeline.run(judge_client=None)

        assert results.read_bytes() == before

    def test_corrupt_candidates_file_refuses_to_run(self, tmp_path, monkeypatch):
        from scripts.automation import pipeline
        st = self._prepare(tmp_path, monkeypatch)
        st.write_json(st.observations_path(), [])
        st.candidates_path().write_text("{broken")
        r = pipeline.run(judge_client=None)
        assert r["ok"] is False
