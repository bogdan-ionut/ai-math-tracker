"""Sprint 2 tests: Gemini extraction. Mocked only — no network, no API key."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from scripts.automation import store
from scripts.automation.extraction import (
    cache_key,
    extract_one,
    load_prompt,
    needs_extraction,
    render_prompt,
    run,
)
from scripts.automation.extraction_schema import (
    ExtractionResult,
    cross_check_identifiers,
    gemini_response_schema,
)
from scripts.automation.gemini import (
    GeminiClient,
    GeminiError,
    SchemaViolation,
    StubModel,
)

ROOT = Path(__file__).resolve().parents[2]
PROMPT = load_prompt("extraction_v1")

GOOD = {
    "isRelevant": True,
    "relevanceReason": "Explicit counterexample claim by a named AI system",
    "canonicalProblemName": "Graffiti Conjecture 154",
    "problemAliases": ["Graffiti 154"],
    "problemFamily": "Graffiti",
    "mathematicalField": "graph theory",
    "claimType": "new_result",
    "resultType": "counterexample",
    "claimingOrganization": "Cognition",
    "claimingPeople": ["Jared Zoneraich"],
    "modelName": "Devin",
    "claimedAt": "2026-07-23",
    "externalIdentifiers": {"github": ["cognition/graffiti-lean"]},
    "sourceUrls": ["https://github.com/cognition/graffiti-lean"],
    "evidenceAvailable": True,
    "summary": "Devin found a counterexample to Graffiti Conjecture 154.",
    "extractionConfidence": 0.9,
    "uncertainties": [],
}


def obs(**over) -> dict:
    base = {
        "id": "obs_test1",
        "sourceType": "twitter",
        "sourceNativeId": "1",
        "url": "https://x.com/imjaredz/status/1",
        "author": "imjaredz",
        "sourceCreatedAt": "Thu Jul 23 14:02:11 +0000 2026",
        "collectedAt": "2026-07-25T00:00:00+00:00",
        "lastSeenAt": "2026-07-25T00:00:00+00:00",
        "matchedQueryIds": ["explicit-ai-solution"],
        "text": "Graffiti Conjecture 154 REFUTED. Devin found the counterexample. "
                "Proven in Lean: https://github.com/cognition/graffiti-lean",
        "textSha256": "abc",
        "links": ["https://github.com/cognition/graffiti-lean"],
        "externalIds": {},
        "status": "new",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------- schema

class TestSchema:
    def test_every_field_is_optional(self):
        """The model must never be forced to invent anything."""
        r = ExtractionResult()
        assert r.isRelevant is False and r.canonicalProblemName is None

    def test_required_fields_in_gemini_schema_are_minimal(self):
        req = set(gemini_response_schema()["required"])
        assert req == {"isRelevant", "claimType", "resultType", "extractionConfidence"}
        # nothing that could be invented is required
        assert not req & {"canonicalProblemName", "externalIdentifiers", "claimedAt", "modelName"}

    def test_confidence_is_clamped(self):
        assert ExtractionResult(extractionConfidence=5).extractionConfidence == 1.0
        assert ExtractionResult(extractionConfidence=-2).extractionConfidence == 0.0

    def test_string_coerced_to_list(self):
        assert ExtractionResult(problemAliases="only one").problemAliases == ["only one"]

    def test_unknown_keys_tolerated(self):
        r = ExtractionResult(**{**GOOD, "somethingNew": 1})
        assert r.isRelevant

    def test_is_actionable(self):
        r = ExtractionResult(**GOOD)
        assert r.is_actionable(0.5)
        assert not r.is_actionable(0.95)
        assert not ExtractionResult(**{**GOOD, "claimType": "commentary"}).is_actionable(0.5)


# ---------------------------------------------------------------- hallucination guard

class TestIdentifierCrossCheck:
    def test_keeps_identifiers_present_in_the_text(self):
        r = ExtractionResult(**GOOD)
        kept, warns = cross_check_identifiers(
            r, "proof in Lean", ["https://github.com/cognition/graffiti-lean"]
        )
        assert "cognition/graffiti-lean" in kept["github"]
        assert not warns

    def test_discards_invented_arxiv_id(self):
        """The critical case: a fabricated id would become a hard match downstream."""
        r = ExtractionResult(**{**GOOD, "externalIdentifiers": {"arxiv": ["2699.99999"]}})
        kept, warns = cross_check_identifiers(r, "no identifiers here at all", [])
        assert "arxiv" not in kept
        assert any("discarded unverifiable" in w for w in warns)

    def test_discards_invented_erdos_number(self):
        r = ExtractionResult(**{**GOOD, "externalIdentifiers": {"erdos": ["999"]}})
        kept, warns = cross_check_identifiers(r, "Erdős problem #728 was solved", [])
        assert kept.get("erdos") == ["728"]          # ours survives, the model's does not
        assert any("999" in w for w in warns)

    def test_recovers_identifiers_the_model_missed(self):
        r = ExtractionResult(**{**GOOD, "externalIdentifiers": {}})
        kept, _ = cross_check_identifiers(r, "see arXiv:2604.03789", [])
        assert kept["arxiv"] == ["2604.03789"]

    def test_model_url_is_folded_onto_our_canonical_form(self):
        """The model may return a URL where our regex produced a slug. Keeping
        both would make one identifier look like two."""
        r = ExtractionResult(**{**GOOD, "externalIdentifiers": {
            "github": ["https://github.com/cognition/graffiti-lean"]}})
        kept, _ = cross_check_identifiers(
            r, "proof in Lean", ["https://github.com/cognition/graffiti-lean"]
        )
        assert kept["github"] == ["cognition/graffiti-lean"]
        assert not any(v.startswith("http") for v in kept["github"])

    def test_arxiv_prefix_folded(self):
        r = ExtractionResult(**{**GOOD, "externalIdentifiers": {"arxiv": ["arXiv:2604.03789"]}})
        kept, _ = cross_check_identifiers(r, "see arXiv:2604.03789", [])
        assert kept["arxiv"] == ["2604.03789"]

    def test_unknown_identifier_kind_is_flagged(self):
        r = ExtractionResult(**{**GOOD, "externalIdentifiers": {"mathscinet": ["MR123"]}})
        _, warns = cross_check_identifiers(r, "text", [])
        assert any("unknown identifier kind" in w for w in warns)


# ---------------------------------------------------------------- prompt

class TestPrompt:
    def test_engagement_metrics_never_reach_the_prompt(self):
        rendered = render_prompt(PROMPT, obs())
        for banned in ("like", "retweet", "view", "follower", "engagement"):
            # allow the word inside "retweeted" only if it never appears — assert hard
            assert banned not in rendered.lower(), f"{banned!r} leaked into the prompt"

    def test_prompt_carries_the_post_text_and_links(self):
        rendered = render_prompt(PROMPT, obs())
        assert "Graffiti Conjecture 154 REFUTED" in rendered
        assert "github.com/cognition/graffiti-lean" in rendered

    def test_prompt_forbids_inventing_identifiers(self):
        assert "Never invent an identifier" in PROMPT

    def test_prompt_distinguishes_claim_from_evidence(self):
        assert "evidence" in PROMPT and "dispute" in PROMPT

    def test_missing_prompt_version_raises(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("does_not_exist_v9")


# ---------------------------------------------------------------- caching

class TestCache:
    def test_key_is_stable(self):
        assert cache_key(obs(), "v1", "m") == cache_key(obs(), "v1", "m")

    def test_key_changes_with_prompt_version(self):
        assert cache_key(obs(), "v1", "m") != cache_key(obs(), "v2", "m")

    def test_key_changes_with_model(self):
        assert cache_key(obs(), "v1", "a") != cache_key(obs(), "v1", "b")

    def test_key_changes_with_text(self):
        assert cache_key(obs(textSha256="x"), "v1", "m") != cache_key(obs(textSha256="y"), "v1", "m")

    def test_extracted_observation_is_not_reprocessed(self):
        o = obs(status="extracted")
        o["extractionCacheKey"] = cache_key(o, "extraction_v1", "gemini-3.6-flash")
        assert not needs_extraction(o, "extraction_v1", "gemini-3.6-flash", force=False)

    def test_model_change_invalidates_cache(self):
        o = obs(status="extracted")
        o["extractionCacheKey"] = cache_key(o, "extraction_v1", "old-model")
        assert needs_extraction(o, "extraction_v1", "gemini-3.6-flash", force=False)

    def test_force_overrides_cache(self):
        o = obs(status="extracted")
        o["extractionCacheKey"] = cache_key(o, "extraction_v1", "gemini-3.6-flash")
        assert needs_extraction(o, "extraction_v1", "gemini-3.6-flash", force=True)

    def test_failed_extraction_is_retried(self):
        assert needs_extraction(obs(status="extraction_failed"), "v1", "m", force=False)


# ---------------------------------------------------------------- extract_one

class TestExtractOne:
    def test_success_path(self):
        out, err = extract_one(StubModel(GOOD), obs(), PROMPT, "extraction_v1", "m")
        assert err is None
        assert out["status"] == "extracted"
        assert out["extraction"]["canonicalProblemName"] == "Graffiti Conjecture 154"
        assert out["externalIds"]["github"] == ["cognition/graffiti-lean"]

    def test_irrelevant_is_marked_not_failed(self):
        stub = StubModel({"isRelevant": False, "claimType": "unrelated",
                          "resultType": "unknown", "extractionConfidence": 0.1})
        out, err = extract_one(stub, obs(), PROMPT, "v1", "m")
        assert err is None and out["status"] == "irrelevant"

    def test_malformed_json_is_a_failure_not_an_empty_result(self):
        stub = StubModel(error=SchemaViolation("model output is not valid JSON"))
        out, err = extract_one(stub, obs(), PROMPT, "v1", "m")
        assert out["status"] == "extraction_failed"
        assert out.get("extraction") is None       # nothing fabricated
        assert "JSON" in err

    def test_api_failure_keeps_the_observation(self):
        stub = StubModel(error=GeminiError("HTTP 503 from generateContent"))
        out, err = extract_one(stub, obs(), PROMPT, "v1", "m")
        assert out["status"] == "extraction_failed"
        assert out["text"] == obs()["text"]        # raw observation preserved
        assert out["id"] == obs()["id"]

    def test_schema_violating_payload_is_rejected(self):
        stub = StubModel({"isRelevant": "definitely", "claimType": "nonsense_value",
                          "resultType": "unknown", "extractionConfidence": 0.5})
        out, err = extract_one(stub, obs(), PROMPT, "v1", "m")
        assert out["status"] == "extraction_failed"
        assert "schema validation failed" in err

    def test_model_identifiers_never_win_over_ours(self):
        stub = StubModel({**GOOD, "externalIdentifiers": {"arxiv": ["9999.11111"]}})
        out, _ = extract_one(stub, obs(), PROMPT, "v1", "m")
        assert "arxiv" not in out["extraction"]["externalIdentifiers"]
        assert out.get("extractionWarnings")


# ---------------------------------------------------------------- client

class TestGeminiClient:
    def test_missing_key_fails_without_leaking(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(GeminiError) as e:
            GeminiClient()
        assert "GEMINI_API_KEY" in str(e.value)

    def test_key_absent_from_repr(self):
        c = GeminiClient(api_key="TOPSECRET123")
        assert "TOPSECRET123" not in repr(c)

    def test_parses_gemini_envelope(self, monkeypatch):
        c = GeminiClient(api_key="k", min_interval=0)
        monkeypatch.setattr(c, "_post", lambda payload: {
            "candidates": [{"content": {"parts": [{"text": json.dumps({"isRelevant": True})}]}}]
        })
        assert c.generate_json("p", {}) == {"isRelevant": True}

    def test_non_json_text_raises_schema_violation(self, monkeypatch):
        c = GeminiClient(api_key="k", min_interval=0)
        monkeypatch.setattr(c, "_post", lambda payload: {
            "candidates": [{"content": {"parts": [{"text": "I'm sorry, I can't do that."}]}}]
        })
        with pytest.raises(SchemaViolation):
            c.generate_json("p", {})

    def test_empty_candidates_raises(self, monkeypatch):
        c = GeminiClient(api_key="k", min_interval=0)
        monkeypatch.setattr(c, "_post", lambda payload: {"candidates": []})
        with pytest.raises(SchemaViolation):
            c.generate_json("p", {})

    def test_retries_then_gives_up_on_5xx(self, monkeypatch):
        c = GeminiClient(api_key="k", max_retries=2, backoff=0, min_interval=0)
        calls = {"n": 0}

        class Resp:
            status_code = 503
            headers: dict = {}

        def fake_post(url, json, headers):  # noqa: A002
            calls["n"] += 1
            return Resp()

        monkeypatch.setattr(httpx.Client, "post", lambda self, url, json, headers: fake_post(url, json, headers))
        with pytest.raises(GeminiError):
            c.generate_json("p", {})
        assert calls["n"] == 2

    def test_timeout_surfaces_as_gemini_error(self, monkeypatch):
        c = GeminiClient(api_key="k", max_retries=1, backoff=0, min_interval=0)

        def boom(self, url, json, headers):  # noqa: A002
            raise httpx.ReadTimeout("too slow")

        monkeypatch.setattr(httpx.Client, "post", boom)
        with pytest.raises(GeminiError) as e:
            c.generate_json("p", {})
        assert "transport error" in str(e.value)

    def test_request_body_contains_schema_and_zero_temperature(self, monkeypatch):
        c = GeminiClient(api_key="k", min_interval=0)
        seen = {}
        monkeypatch.setattr(c, "_post", lambda payload: seen.update(payload) or {
            "candidates": [{"content": {"parts": [{"text": "{}"}]}}]
        })
        c.generate_json("prompt", gemini_response_schema())
        assert seen["generationConfig"]["responseMimeType"] == "application/json"
        assert seen["generationConfig"]["temperature"] == 0.0
        assert "responseSchema" in seen["generationConfig"]


# ---------------------------------------------------------------- pipeline

class TestRun:
    def _seed(self, tmp_path, monkeypatch, observations):
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        monkeypatch.setattr(store, "RAW_DIR", tmp_path / "raw")
        store.write_json(store.observations_path(), observations)

    def test_dry_run_writes_nothing(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch, [obs()])
        before = store.observations_path().read_text()
        r = run(dry_run=True)
        assert r["ok"] and "proposedMutations" in r
        assert store.observations_path().read_text() == before

    def test_second_run_makes_zero_api_calls(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch, [obs()])
        stub1 = StubModel(GOOD)
        run(model_client=stub1)
        assert stub1.call_count == 1
        stub2 = StubModel(GOOD)
        r2 = run(model_client=stub2)
        assert stub2.call_count == 0, "cache did not hold"
        assert r2["processed"] == 0

    def test_cap_defers_rather_than_drops(self, tmp_path, monkeypatch):
        many = [obs(id=f"obs_{i}", sourceNativeId=str(i), textSha256=str(i)) for i in range(5)]
        self._seed(tmp_path, monkeypatch, many)
        r = run(model_client=StubModel(GOOD), limit=2)
        assert r["processed"] == 2 and r["deferredByCap"] == 3
        remaining = store.read_json(store.observations_path(), [])
        assert sum(1 for o in remaining if o["status"] == "new") == 3

    def test_failure_does_not_lose_observations(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch, [obs()])
        r = run(model_client=StubModel(error=GeminiError("HTTP 500")))
        assert r["failed"] == 1
        kept = store.read_json(store.observations_path(), [])
        assert len(kept) == 1 and kept[0]["status"] == "extraction_failed"

    def test_corrupt_store_refuses_to_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        store.observations_path().write_text("{broken")
        r = run(model_client=StubModel(GOOD))
        assert r["ok"] is False and "refusing to run" in r["error"]

    def test_curated_results_untouched(self, tmp_path, monkeypatch):
        results = ROOT / "data" / "results.json"
        before = results.read_bytes()
        self._seed(tmp_path, monkeypatch, [obs()])
        run(model_client=StubModel(GOOD))
        assert results.read_bytes() == before

    def test_model_and_prompt_version_recorded(self, tmp_path, monkeypatch):
        self._seed(tmp_path, monkeypatch, [obs()])
        run(model_client=StubModel(GOOD))
        o = store.read_json(store.observations_path(), [])[0]
        assert o["extractionModel"] == "gemini-3.6-flash"
        assert o["extractionPromptVersion"] == "extraction_v1"
