"""Sprint 3 tests: entity matching and the judge boundary. No network, no keys."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.automation.matching import (
    LEXICAL_FLOOR,
    build_judge_payload,
    judge_response_schema,
    load_registry,
    match_observation,
)

ROOT = Path(__file__).resolve().parents[2]


def rec(rid, title, *, aliases=None, ext=None, **extra) -> dict:
    base = {
        "id": rid, "title": title, "description": f"{title} description",
        "family": "Erdős", "status": "reported", "model": "GPT",
        "claimedAt": "2026-01-01",
        "aliases": aliases if aliases is not None else [title],
        "externalIds": ext or {},
    }
    base.update(extra)
    return base


def obs(*, name=None, aliases=None, ext=None, text="some text") -> dict:
    return {
        "id": "obs_x", "url": "https://x.com/a/status/1", "author": "a",
        "sourceCreatedAt": "Thu Jul 23 14:00:00 +0000 2026", "text": text,
        "externalIds": ext or {},
        "extraction": {
            "canonicalProblemName": name,
            "problemAliases": aliases or [],
            "claimType": "new_result", "resultType": "proof",
            "modelName": "GPT-5.6", "claimingOrganization": "OpenAI",
        },
    }


REGISTRY = [
    rec("erdos-728", "Erdős #728", aliases=["Erdős #728", "Erdos #728", "Erdős problem 728"],
        ext={"erdos": ["728"]}),
    rec("erdos-782", "Erdős #782", aliases=["Erdős #782", "Erdos #782"], ext={"erdos": ["782"]}),
    rec("jacobian-conjecture-1939", "Jacobian conjecture (1939)",
        aliases=["Jacobian conjecture (1939)", "Jacobian conjecture"], ext={}),
    rec("cycle-double-cover", "Cycle Double Cover conjecture",
        aliases=["Cycle Double Cover conjecture"], ext={"github": ["openai/cdc-lean"]}),
]


# ---------------------------------------------------------------- deterministic

class TestIdentifierMatching:
    def test_exact_identifier_matches_without_judge(self):
        out = match_observation(obs(ext={"erdos": ["728"]}), REGISTRY)
        assert out.method == "identifier"
        assert out.matched_id == "erdos-728"
        assert out.needs_judge is False, "a certain match must never cost a model call"

    def test_github_identifier_matches(self):
        out = match_observation(obs(ext={"github": ["openai/cdc-lean"]}), REGISTRY)
        assert out.matched_id == "cycle-double-cover" and not out.needs_judge

    def test_different_numbers_never_merge(self):
        """728 vs 782 — the classic near-miss."""
        out = match_observation(obs(name="Erdős #782", ext={"erdos": ["782"]}), REGISTRY)
        assert out.matched_id == "erdos-782"

    def test_conflicting_identifier_excludes_the_record(self):
        out = match_observation(obs(name="Erdős problem", ext={"erdos": ["999"]}), REGISTRY)
        assert out.matched_id is None
        assert any("conflicting identifier" in n for n in out.notes)

    def test_identifier_on_two_records_is_a_data_problem_not_a_judgement(self):
        broken = REGISTRY + [rec("dupe", "Duplicate", ext={"erdos": ["728"]})]
        out = match_observation(obs(ext={"erdos": ["728"]}), broken)
        assert out.conflict is True
        assert out.needs_judge is False, "a broken registry is not a question for a model"
        assert "registry needs fixing" in " ".join(out.notes)


# ---------------------------------------------------------------- alias

class TestAliasMatching:
    def test_alias_matches_without_judge(self):
        out = match_observation(obs(name="Erdos #728"), REGISTRY)
        assert out.method == "alias" and out.matched_id == "erdos-728"
        assert out.needs_judge is False

    def test_alias_is_diacritic_insensitive(self):
        assert match_observation(obs(name="erdos problem 728"), REGISTRY).matched_id == "erdos-728"

    def test_alias_from_extraction_aliases_list(self):
        out = match_observation(obs(name=None, aliases=["Jacobian conjecture"]), REGISTRY)
        assert out.matched_id == "jacobian-conjecture-1939"


# ---------------------------------------------------------------- lexical

class TestLexicalShortlist:
    def test_close_name_produces_shortlist_for_the_judge(self):
        out = match_observation(obs(name="the Cycle Double Cover problem"), REGISTRY)
        assert out.shortlist
        assert out.matched_id is None or out.needs_judge is False

    def test_unrelated_name_matches_nothing(self):
        out = match_observation(obs(name="Navier-Stokes existence and smoothness"), REGISTRY)
        assert out.method == "none" and not out.shortlist and not out.needs_judge

    def test_shortlist_is_capped(self):
        many = [rec(f"r{i}", f"Erdős problem about primes {i}") for i in range(20)]
        out = match_observation(obs(name="Erdős problem about primes"), many, shortlist_size=5)
        assert len(out.shortlist) <= 5

    def test_shortlist_is_ordered_best_first(self):
        out = match_observation(obs(name="Jacobian conjecture"), REGISTRY + [
            rec("jac-weak", "Jacobian conjecture weak form")])
        scores = [c.score for c in out.shortlist]
        assert scores == sorted(scores, reverse=True)

    def test_floor_keeps_junk_out(self):
        out = match_observation(obs(name="completely unrelated topic xyz"), REGISTRY)
        assert all(c.score >= LEXICAL_FLOOR for c in out.shortlist)


# ---------------------------------------------------------------- judge boundary

class TestJudgeBoundary:
    def test_judge_never_called_when_identifier_matched(self):
        for ext in ({"erdos": ["728"]}, {"github": ["openai/cdc-lean"]}):
            assert match_observation(obs(ext=ext), REGISTRY).needs_judge is False

    def test_judge_never_called_when_alias_matched(self):
        assert match_observation(obs(name="Erdos #728"), REGISTRY).needs_judge is False

    def test_judge_never_called_when_nothing_matches(self):
        assert match_observation(obs(name="Riemann hypothesis"), REGISTRY).needs_judge is False

    def test_judge_called_only_for_ambiguous_lexical(self):
        out = match_observation(
            obs(name="Erdős problem"),
            [rec("a", "Erdős problem 12"), rec("b", "Erdős problem 13")],
        )
        assert out.needs_judge is True and len(out.shortlist) == 2


# ---------------------------------------------------------------- judge payload

class TestJudgePayload:
    def test_payload_excludes_editorial_fields(self):
        registry = [rec("erdos-728", "Erdős #728", impact=5, assessment="huge",
                        auditNotes="secret", confidence=0.9)]
        out = match_observation(obs(name="Erdős problem"), registry)
        payload = build_judge_payload(obs(name="Erdős problem"), out, registry)
        blob = json.dumps(payload)
        for banned in ("impact", "assessment", "auditNotes"):
            assert banned not in blob, f"{banned} must not reach the judge"

    def test_payload_excludes_engagement(self):
        out = match_observation(obs(name="Erdős problem"), REGISTRY)
        blob = json.dumps(build_judge_payload(obs(name="Erdős problem"), out, REGISTRY))
        for banned in ("like", "retweet", "view", "engagement"):
            assert banned not in blob.lower()

    def test_payload_carries_ids_and_identifiers(self):
        o = obs(name="Erdős problem", ext={"erdos": ["728"]})
        out = match_observation(o, REGISTRY)
        payload = build_judge_payload(o, out, REGISTRY)
        assert payload["observation"]["externalIdentifiers"] == {"erdos": ["728"]}
        for c in payload["candidates"]:
            assert c["id"] and "externalIdentifiers" in c

    def test_schema_has_all_seven_decisions(self):
        enum = judge_response_schema()["properties"]["decision"]["enum"]
        assert set(enum) == {
            "same_source_duplicate", "same_problem_same_claim", "same_problem_new_claim",
            "same_problem_conflicting_claim", "related_problem", "distinct_problem",
            "insufficient_information",
        }

    def test_schema_requires_review_flag(self):
        assert "requiresHumanReview" in judge_response_schema()["required"]


# ---------------------------------------------------------------- real registry

class TestAgainstRealRegistry:
    @pytest.fixture(scope="class")
    def registry(self):
        return load_registry()

    def test_every_record_has_matching_aids(self, registry):
        for r in registry:
            assert "aliases" in r and "externalIds" in r, f"{r['id']} not backfilled"

    def test_no_identifier_maps_to_two_records(self, registry):
        seen: dict[str, str] = {}
        for r in registry:
            for kind, values in (r.get("externalIds") or {}).items():
                for v in values:
                    key = f"{kind}:{v}"
                    assert key not in seen, (
                        f"{key} claimed by both {seen[key]} and {r['id']} — "
                        "deterministic matching would be ambiguous"
                    )
                    seen[key] = r["id"]

    def test_real_erdos_observation_resolves_deterministically(self, registry):
        out = match_observation(obs(name="Erdős #728", ext={"erdos": ["728"]}), registry)
        assert out.method == "identifier" and out.needs_judge is False

    def test_real_lean_repo_resolves(self, registry):
        out = match_observation(obs(ext={"github": ["openai/cdc-lean"]}), registry)
        assert out.matched_id == "cycle-double-cover"

    def test_unknown_problem_does_not_match_anything(self, registry):
        out = match_observation(obs(name="Collatz conjecture"), registry)
        assert out.matched_id is None
