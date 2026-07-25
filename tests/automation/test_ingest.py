"""Sprint 1 tests. No network, no API keys, no writes outside tmp_path."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.automation import store
from scripts.automation.identifiers import extract_identifiers, normalize_title
from scripts.automation.ids import candidate_id, observation_id, review_id, text_hash
from scripts.automation.ingest import (
    merge_observations,
    normalise_tweet,
    to_observation,
    run,
)
from scripts.automation.twitter import FixtureSearchClient, TwitterApiClient, TwitterApiError
from scripts.automation.urls import canonicalize_url, expand_links

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "fixtures" / "twitter_search.json"

# Fixture tweets are dated; pin a wide window so tests never depend on today.
WIDE = 24 * 365 * 50


@pytest.fixture()
def tweets() -> list[dict]:
    return json.loads(FIXTURE.read_text())["tweets"]


# ---------------------------------------------------------------- URLs

class TestCanonicalUrl:
    def test_strips_tracking_params(self):
        assert canonicalize_url(
            "https://example.com/a?utm_source=x&utm_medium=y&id=7&ref=abc"
        ) == "https://example.com/a?id=7"

    def test_twitter_and_x_converge(self):
        a = canonicalize_url("https://twitter.com/u/status/1?s=20")
        b = canonicalize_url("https://x.com/u/status/1")
        assert a == b == "https://x.com/u/status/1"

    def test_upgrades_scheme_and_drops_fragment(self):
        assert canonicalize_url("http://Example.COM/p#section") == "https://example.com/p"

    def test_doi_host_alias(self):
        assert canonicalize_url("https://dx.doi.org/10.1/x").startswith("https://doi.org/")

    def test_trailing_slash_and_www(self):
        assert canonicalize_url("https://www.example.com/path/") == "https://example.com/path"

    def test_rejects_junk(self):
        assert canonicalize_url("") is None
        assert canonicalize_url(None) is None

    def test_preserves_unknown_query_params(self):
        # dropping a meaningful param would silently merge different resources
        assert "page=3" in canonicalize_url("https://example.com/a?page=3")

    def test_expand_links_prefers_expanded_and_drops_tco(self):
        ents = {"urls": [{"url": "https://t.co/x", "expanded_url": "https://arxiv.org/abs/2607.16356?utm_source=t"}]}
        assert expand_links(ents) == ["https://arxiv.org/abs/2607.16356"]


# ---------------------------------------------------------------- identifiers

class TestIdentifiers:
    def test_arxiv_from_url(self):
        ids = extract_identifiers("see it", ["https://arxiv.org/abs/2607.16356"])
        assert ids.arxiv == ["2607.16356"]

    def test_arxiv_from_text_requires_context(self):
        assert extract_identifiers("arXiv:2604.03789").arxiv == ["2604.03789"]
        # a bare decimal without the word arxiv must NOT be captured
        assert extract_identifiers("the ratio was 2604.03789").arxiv == []

    def test_doi_and_oeis(self):
        ids = extract_identifiers("doi 10.1016/j.jnt.2020.01.001 and A000045")
        assert ids.doi == ["10.1016/j.jnt.2020.01.001"]
        assert ids.oeis == ["A000045"]

    def test_erdos_needs_context(self):
        assert extract_identifiers("Erdős problem #728 solved").erdos == ["728"]
        assert extract_identifiers("issue #728 in our repo").erdos == []

    def test_erdos_from_url(self):
        assert extract_identifiers("", ["https://www.erdosproblems.com/728"]).erdos == ["728"]

    def test_github_and_lean(self):
        ids = extract_identifiers("Lean 4 proof", ["https://github.com/openai/cdc-lean"])
        assert "openai/cdc-lean" in ids.github
        assert "openai/cdc-lean" in ids.lean

    def test_overlap_and_conflict(self):
        a = extract_identifiers("Erdős problem #728")
        b = extract_identifiers("Erdős problem #728 again")
        c = extract_identifiers("Erdős problem #999")
        assert a.overlaps(b) and not a.conflicts_with(b)
        assert a.conflicts_with(c)          # same kind, different value → never merge
        assert not a.conflicts_with(extract_identifiers("no ids here"))

    def test_normalize_title_folds_diacritics(self):
        assert normalize_title("The Erdős Problem #728") == normalize_title("erdos problem #728")


# ---------------------------------------------------------------- ids

class TestStableIds:
    def test_observation_id_is_deterministic(self):
        assert observation_id("twitter", "123") == observation_id("twitter", "123")

    def test_observation_id_differs_by_source(self):
        assert observation_id("twitter", "123") != observation_id("arxiv", "123")

    def test_candidate_id_prefers_external_identifier(self):
        a = candidate_id("Some Name", {"erdos": ["728"]})
        b = candidate_id("A Totally Different Name", {"erdos": ["728"]})
        assert a == b == "cand_erdos_728"

    def test_candidate_id_falls_back_to_name(self):
        assert candidate_id("Jacobian conjecture").startswith("cand_")

    def test_review_id_stable_per_reason(self):
        assert review_id("no_corroboration", "obs_1") == review_id("no_corroboration", "obs_1")
        assert review_id("conflict", "obs_1") != review_id("no_corroboration", "obs_1")

    def test_text_hash(self):
        assert text_hash("abc") == text_hash("abc")
        assert text_hash(None) is None


# ---------------------------------------------------------------- normalisation

class TestNormalisation:
    def test_retweet_attributed_to_original(self, tweets):
        rt = [t for t in tweets if t.get("retweeted_tweet")][0]
        rec = normalise_tweet(rt, "q", "2026-07-25T00:00:00+00:00", True)
        # the RT collapses onto the original tweet id, not its own
        assert rec.tweetId == "2080088344424583261"
        assert rec.isRetweet is True

    def test_links_are_canonicalised(self, tweets):
        rec = normalise_tweet(tweets[0], "q", "2026-07-25T00:00:00+00:00", True)
        assert rec.links == ["https://github.com/cognition/graffiti-lean"]

    def test_engagement_captured_but_isolated(self, tweets):
        rec = normalise_tweet(tweets[0], "q", "2026-07-25T00:00:00+00:00", True)
        assert rec.engagement["likes"] == 1200
        # engagement must never appear on the observation the pipeline reasons over
        obs = to_observation(rec, "2026-07-25T00:00:00+00:00")
        assert "engagement" not in obs.model_dump()

    def test_text_can_be_withheld_but_hash_kept(self, tweets):
        rec = normalise_tweet(tweets[0], "q", "2026-07-25T00:00:00+00:00", store_text=False)
        assert rec.text is None and rec.textSha256

    def test_tweet_without_id_is_dropped(self):
        assert normalise_tweet({"text": "x"}, "q", "now", True) is None

    def test_corroboration_flag(self, tweets):
        now = "2026-07-25T00:00:00+00:00"
        rich = to_observation(normalise_tweet(tweets[1], "q", now, True), now)   # has arXiv
        bare = to_observation(normalise_tweet(tweets[3], "q", now, True), now)   # "just vibes"
        assert rich.has_external_identifier() is True
        assert bare.has_external_identifier() is False


# ---------------------------------------------------------------- merge / idempotency

class TestMerge:
    def _obs(self, tweets, idx, qid="q1"):
        now = "2026-07-25T00:00:00+00:00"
        return to_observation(normalise_tweet(tweets[idx], qid, now, True), now)

    def test_adds_new(self, tweets):
        merged, added, updated = merge_observations([], [self._obs(tweets, 0)], "t")
        assert (added, updated, len(merged)) == (1, 0, 1)

    def test_rerun_adds_nothing(self, tweets):
        obs = self._obs(tweets, 0)
        merged, _, _ = merge_observations([], [obs], "t1")
        merged2, added, _ = merge_observations(merged, [obs], "t1")
        assert added == 0 and len(merged2) == 1

    def test_second_query_appends_query_id(self, tweets):
        merged, _, _ = merge_observations([], [self._obs(tweets, 0, "q1")], "t1")
        merged2, added, updated = merge_observations(merged, [self._obs(tweets, 0, "q2")], "t2")
        assert added == 0 and updated == 1
        assert merged2[0]["matchedQueryIds"] == ["q1", "q2"]

    def test_retweet_does_not_duplicate_original(self, tweets):
        original = self._obs(tweets, 0)
        retweet = self._obs(tweets, 2)
        merged, added, _ = merge_observations([], [original, retweet], "t")
        assert added == 1 and len(merged) == 1

    def test_links_only_grow(self, tweets):
        obs = self._obs(tweets, 0)
        seeded = [{**obs.model_dump(mode="json"), "links": ["https://example.com/old"]}]
        merged, _, _ = merge_observations(seeded, [obs], "t")
        assert "https://example.com/old" in merged[0]["links"]
        assert "https://github.com/cognition/graffiti-lean" in merged[0]["links"]


# ---------------------------------------------------------------- store

class TestStore:
    def test_atomic_roundtrip(self, tmp_path):
        p = tmp_path / "x.json"
        store.write_json(p, [{"a": 1}])
        assert store.read_json(p, None) == [{"a": 1}]
        assert not list(tmp_path.glob("*.tmp"))

    def test_missing_file_returns_default(self, tmp_path):
        assert store.read_json(tmp_path / "nope.json", []) == []

    def test_corrupt_file_raises_rather_than_defaulting(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        with pytest.raises(store.CorruptStoreError):
            store.read_json(p, [])

    def test_empty_file_is_not_treated_as_no_data(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("   ")
        with pytest.raises(store.CorruptStoreError):
            store.read_json(p, [])


# ---------------------------------------------------------------- client

class TestClient:
    def test_missing_key_fails_loudly_without_leaking(self, monkeypatch):
        monkeypatch.delenv("TWITTERAPI_IO_KEY", raising=False)
        with pytest.raises(TwitterApiError) as e:
            TwitterApiClient()
        assert "TWITTERAPI_IO_KEY" in str(e.value)

    def test_key_never_appears_in_repr_or_errors(self):
        c = TwitterApiClient(api_key="SUPERSECRET")
        assert "SUPERSECRET" not in repr(c)
        assert "SUPERSECRET" not in str(c.__dict__.get("_headers", ""))

    def test_fixture_client_is_offline(self, tweets):
        c = FixtureSearchClient(default=tweets)
        assert len(c.search("anything")) == len(tweets)


# ---------------------------------------------------------------- end to end

class TestPipeline:
    def test_dry_run_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        monkeypatch.setattr(store, "RAW_DIR", tmp_path / "raw")
        result = run(dry_run=True, fixtures=FIXTURE, lookback_hours=WIDE)
        assert result["ok"] and result["dryRun"]
        assert "proposedMutations" in result
        assert not list(tmp_path.glob("*.json"))

    def test_full_run_then_rerun_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        monkeypatch.setattr(store, "RAW_DIR", tmp_path / "raw")
        first = run(fixtures=FIXTURE, lookback_hours=WIDE)
        assert first["observationsAdded"] > 0
        second = run(fixtures=FIXTURE, lookback_hours=WIDE)
        assert second["observationsAdded"] == 0
        assert second["observationsTotal"] == first["observationsTotal"]

    def test_empty_api_response_does_not_destroy_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        monkeypatch.setattr(store, "RAW_DIR", tmp_path / "raw")
        run(fixtures=FIXTURE, lookback_hours=WIDE)
        before = store.read_json(store.observations_path(), [])
        empty = tmp_path / "empty_fixture.json"
        empty.write_text(json.dumps({"tweets": []}))
        run(fixtures=empty, lookback_hours=WIDE)
        after = store.read_json(store.observations_path(), [])
        assert len(after) == len(before) > 0

    def test_curated_results_are_never_touched(self, tmp_path, monkeypatch):
        """The whole point: automation must not write the curated registry."""
        results = ROOT / "data" / "results.json"
        before = results.read_bytes()
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        monkeypatch.setattr(store, "RAW_DIR", tmp_path / "raw")
        run(fixtures=FIXTURE, lookback_hours=WIDE)
        assert results.read_bytes() == before

    def test_respects_per_run_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        monkeypatch.setattr(store, "RAW_DIR", tmp_path / "raw")
        r = run(fixtures=FIXTURE, limit=2, lookback_hours=WIDE)
        assert r["processed"] == 2 and r["overflowDeferred"] >= 1


# ---------------------------------------------------------------- config

class TestConfig:
    def test_queries_load_and_include_accounts(self):
        from scripts.automation.query_builder import build_queries

        built = build_queries()
        families = {q.family for q in built}
        assert "explicit-ai-solution" in families
        assert "disputes-and-corrections" in families
        assert any(q.id.startswith("account-") for q in built)

    def test_no_secrets_in_config(self):
        """Config may *name* the env vars it needs; it must not contain a value
        that looks like a credential."""
        import re

        # A credential is long AND high-entropy: mixed case plus digits. A plain
        # kebab-case slug like "disputes-and-corrections" is 24 chars but is not
        # a secret, and flagging it taught nothing.
        cred = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[A-Za-z0-9_\-]{24,}$")

        def walk(node, where):
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, f"{where}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{where}[{i}]")
            elif isinstance(node, str):
                assert not cred.match(node), f"{where} looks like a credential"

        for name in ("automation.json", "twitter_discovery.json"):
            walk(json.loads((ROOT / "config" / name).read_text()), name)

    def test_gemini_model_is_pinned(self):
        cfg = json.loads((ROOT / "config" / "automation.json").read_text())
        assert cfg["extraction"]["model"] == "gemini-3.6-flash"
        assert cfg["judge"]["model"] == "gemini-3.6-flash"

    def test_editorial_fields_are_protected(self):
        cfg = json.loads((ROOT / "config" / "automation.json").read_text())
        never = set(cfg["policy"]["neverAutoWriteFields"])
        assert {"status", "auditedAt", "impact", "assessment"} <= never
