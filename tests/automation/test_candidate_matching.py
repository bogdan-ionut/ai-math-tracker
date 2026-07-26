"""Sprint 6 — R5 and R6/D37: matching the candidate store, and evidence tiers.

**R5.** Matching only ever searched the curated registry. The second post about
a genuinely *new* problem could not see the candidate the first post created, so
it was decided `distinct_problem` and the two never converged — the roadmap has
promised since Sprint 0 that "Twitter and arXiv resolve to one candidate", and
the architecture could not deliver it.

Sprint 5.4 made `_upsert_candidate` converge on exact identifier or exact name.
This is the fuzzy tier: "the unit distance problem" and "unit distance problem"
are the same problem, and only the matcher knows that.

The dangerous part is what a candidate match must *not* do. `problemRef` means
"this is the curated problem in data/results.json". Pointing it at one of our own
proposals would claim a link to published work that does not exist.

**R6/D37.** "Corroborated" was a boolean over six identifier kinds, which
overstated what we knew: a bare GitHub link is a reference, not corroboration.
"""
from __future__ import annotations

import pytest

from scripts.automation.matching import match_observation
from scripts.automation.merge import _upsert_candidate, resolve
from scripts.automation.policy import evidence_tier, may_become_candidate

NOW = "2026-07-26T00:00:00+00:00"


def obs(name="the unit distance problem", ext=None):
    return {
        "id": "obs_1", "url": "https://x.com/a/status/1", "externalIds": ext or {},
        "extraction": {"canonicalProblemName": name, "problemAliases": [],
                       "claimType": "new_result", "resultType": "proof",
                       "modelName": "GPT-5.6", "summary": "s"},
    }


def cand(cid="cand_x", name="unit distance problem", ext=None):
    return {"id": cid, "canonicalName": name, "aliases": [],
            "externalIds": ext or {}, "claims": [], "observationIds": [],
            "sources": [], "firstSeenAt": NOW, "lastSeenAt": NOW}


# ============================================================== R5

class TestMatchingSeesTheCandidateStore:
    def test_without_candidates_a_second_report_is_distinct(self):
        """The defect, stated as a test."""
        assert match_observation(obs(), registry=[]).method == "none"

    def test_a_differently_worded_second_report_finds_the_candidate(self):
        out = match_observation(obs(), registry=[], candidates=[cand()])
        assert out.matched_id == "cand_x"
        assert out.matched_kind == "candidate"

    def test_the_curated_registry_always_wins(self):
        """A curated record is stronger evidence than a proposal we made."""
        reg = [{"id": "udp-1946", "title": "Unit distance problem",
                "aliases": [], "externalIds": {}}]
        out = match_observation(obs(), registry=reg, candidates=[cand()])
        assert out.matched_id == "udp-1946" and out.matched_kind == "registry"

    def test_an_unrelated_candidate_is_not_matched(self):
        out = match_observation(obs(), registry=[],
                                candidates=[cand(name="Collatz conjecture")])
        assert out.method == "none"

    def test_a_registry_conflict_is_not_rescued_by_a_candidate(self):
        """A conflicting identifier is a hard stop; it must not be routed around."""
        reg = [{"id": "a", "title": "T", "aliases": [], "externalIds": {"erdos": ["1"]}},
               {"id": "b", "title": "T", "aliases": [], "externalIds": {"erdos": ["1"]}}]
        o = obs(ext={"erdos": ["1"]})
        out = match_observation(o, registry=reg, candidates=[cand()])
        assert out.conflict is True and out.matched_kind == "registry"

    def test_candidates_are_matched_by_the_same_rules_as_records(self):
        """Two matchers would be two sets of bugs."""
        out = match_observation(obs(ext={"arxiv": ["2607.1"]}), registry=[],
                                candidates=[cand(name="something else",
                                                 ext={"arxiv": ["2607.1"]})])
        assert out.method == "identifier" and out.matched_id == "cand_x"


class TestACandidateMatchClaimsNothingAboutTheRegistry:
    def _resolution(self):
        out = match_observation(obs(), registry=[], candidates=[cand()])
        return resolve(out)

    def test_problem_ref_is_not_set_from_a_candidate(self):
        r = self._resolution()
        assert r.matched_id is None, (
            "a candidate id in problemRef would claim a curated link that does not exist"
        )
        assert r.candidate_ref == "cand_x"

    def test_the_observation_joins_that_candidate(self):
        r = self._resolution()
        cands, cid, created, *_ = _upsert_candidate(
            [cand()], obs(), r.matched_id, NOW, join_id=r.candidate_ref)
        assert cid == "cand_x" and created is False
        assert len(cands) == 1
        assert "obs_1" in cands[0]["observationIds"]

    def test_the_joined_candidate_keeps_an_empty_problem_ref(self):
        r = self._resolution()
        cands, *_ = _upsert_candidate([cand()], obs(), r.matched_id, NOW,
                                      join_id=r.candidate_ref)
        assert not cands[0].get("problemRef")

    def test_the_curator_is_told_it_is_only_a_grouping(self):
        out = match_observation(obs(), registry=[], candidates=[cand()])
        assert any("does not confirm" in n for n in out.notes)


# ============================================================== R6 / D37

class TestEvidenceIsTiered:
    @pytest.mark.parametrize("ids,tier", [
        ({"doi": ["10.1/x"]}, "published"),
        ({"arxiv": ["2607.1"]}, "published"),
        ({"erdos": ["728"]}, "registered"),
        ({"oeis": ["A000045"]}, "registered"),
        ({"github": ["a/b"]}, "referenced"),
        ({"lean": ["x"]}, "referenced"),
        ({}, "none"),
    ])
    def test_each_kind_lands_in_its_tier(self, ids, tier):
        assert evidence_tier({"externalIds": ids}) == tier

    def test_the_strongest_reference_decides(self):
        assert evidence_tier(
            {"externalIds": {"github": ["a/b"], "doi": ["10.1/x"]}}) == "published"

    def test_the_reason_names_the_tier_not_just_corroborated(self):
        """A curator reading the queue needs to know whether this is a DOI or
        somebody's repository link."""
        ok, why = may_become_candidate({"externalIds": {"github": ["a/b"]}})
        assert ok is True and "referenced" in why

    def test_a_bare_github_link_is_still_admitted_by_default(self):
        """This changes what we are willing to say, not what we collect."""
        ok, _ = may_become_candidate({"externalIds": {"github": ["a/b"]}})
        assert ok is True

    def test_but_the_bar_can_be_raised(self):
        policy = {"requireCorroborationForCandidate": True,
                  "minimumEvidenceTier": "registered"}
        ok, why = may_become_candidate({"externalIds": {"github": ["a/b"]}}, policy)
        assert ok is False and "below the configured minimum" in why

    def test_raising_the_bar_still_admits_stronger_evidence(self):
        policy = {"requireCorroborationForCandidate": True,
                  "minimumEvidenceTier": "registered"}
        assert may_become_candidate({"externalIds": {"doi": ["10.1/x"]}}, policy)[0]

    def test_no_evidence_is_still_refused(self):
        ok, why = may_become_candidate({"externalIds": {}})
        assert ok is False and "not evidence" in why
