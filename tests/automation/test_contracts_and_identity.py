"""Sprint 5.4 — data contracts, cost, and identity.

**R4.** Every model here sets `extra = "forbid"`, which buys nothing unless
something validates. Nothing did — the workflow checked only that these files
were parseable JSON — so six fields the extraction stage wrote and two the
pipeline wrote had never been declared, and the mismatch was invisible for
weeks. Wiring validation in surfaced all eight immediately, and a test fixture
that was never a valid `Observation` at all.

**R3.** `review` was not a resolved state, so a curator's queue re-billed Gemini
for the same post every day it sat there. A failed extraction was retried
forever, so one permanently malformed post cost a call per run in perpetuity.

**R15+ / D36.** `candidate_id` was derived from whatever identifiers the
observation happened to carry, so the day an arXiv id arrived, the same problem
acquired a second id and a second record — one problem, three ids across three
days. An id is now assigned once and kept for life.

**R10.** Third-party post text was committed in full, indefinitely, to a public
repository.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.automation import store
from scripts.automation.extraction import (
    EXCERPT_CHARS,
    RETRY_BACKOFF_HOURS,
    _record_failure,
    cache_key,
    needs_extraction,
    redact_resolved,
)
from scripts.automation.merge import _upsert_candidate
from scripts.automation.models import Observation

PV, MODEL = "v1", "gemini-3.6-flash"
T0 = datetime(2026, 7, 26, tzinfo=timezone.utc)


def valid_obs(**over) -> dict:
    base = {
        "id": "obs_1", "sourceType": "twitter", "sourceNativeId": "1",
        "url": "https://x.com/a/status/1", "collectedAt": "2026-07-26T00:00:00+00:00",
        "lastSeenAt": "2026-07-26T00:00:00+00:00",
    }
    base.update(over)
    return base


# ============================================================== R4

class TestPersistedFilesMatchTheirModel:
    def test_an_undeclared_field_is_rejected(self, tmp_path):
        p = tmp_path / "o.json"
        p.write_text(json.dumps([valid_obs(typoField=1)]))
        with pytest.raises(store.ContractError, match="typoField"):
            store.read_records(p, Observation)

    def test_a_wrong_type_is_rejected(self, tmp_path):
        p = tmp_path / "o.json"
        p.write_text(json.dumps([valid_obs(extractionAttempts="lots")]))
        with pytest.raises(store.ContractError, match="extractionAttempts"):
            store.read_records(p, Observation)

    def test_an_unknown_enum_value_is_rejected(self, tmp_path):
        p = tmp_path / "o.json"
        p.write_text(json.dumps([valid_obs(sourceType="mastodon")]))
        with pytest.raises(store.ContractError, match="sourceType"):
            store.read_records(p, Observation)

    def test_a_non_list_payload_is_rejected(self, tmp_path):
        p = tmp_path / "o.json"
        p.write_text(json.dumps({"id": "obs_1"}))
        with pytest.raises(store.ContractError, match="expected a list"):
            store.read_records(p, Observation)

    def test_a_breach_never_reaches_disk(self, tmp_path):
        """Validating on write catches the bug in the run that caused it."""
        p = tmp_path / "o.json"
        with pytest.raises(store.ContractError):
            store.write_records(p, Observation, [valid_obs(nonsense=True)])
        assert not p.exists(), "an invalid payload was written anyway"

    def test_the_message_names_the_file_the_field_and_the_direction(self, tmp_path):
        p = tmp_path / "o.json"
        p.write_text(json.dumps([valid_obs(typoField=1)]))
        with pytest.raises(store.ContractError) as exc:
            store.read_records(p, Observation)
        text = str(exc.value)
        assert "o.json" in text and "on read" in text and "typoField" in text

    @pytest.mark.parametrize("field", [
        "extractionCacheKey", "extractionWarnings", "extractionAttempts",
        "lastAttemptAt", "nextRetryAt", "failureType", "matchMethod", "decision",
    ])
    def test_every_field_the_code_writes_is_declared(self, field):
        """The eight that were persisted for weeks without being declared."""
        assert field in Observation.model_fields

    def test_a_corrupt_file_is_still_distinguished_from_a_contract_breach(self, tmp_path):
        p = tmp_path / "o.json"
        p.write_text("{not json")
        with pytest.raises(store.CorruptStoreError):
            store.read_records(p, Observation)


# ============================================================== R3

class TestWeStopPayingForSettledQuestions:
    def _resolved(self, status):
        obs = valid_obs(status=status, text="t", textSha256="a" * 64)
        obs["extractionCacheKey"] = cache_key(obs, PV, MODEL)
        return obs

    def test_a_reviewed_observation_is_not_re_extracted(self):
        assert needs_extraction(self._resolved("review"), PV, MODEL, False) is False

    @pytest.mark.parametrize("status", ["irrelevant", "extracted", "matched", "merged"])
    def test_other_resolved_states_are_unchanged(self, status):
        assert needs_extraction(self._resolved(status), PV, MODEL, False) is False

    def test_but_edited_text_revives_it(self):
        obs = dict(self._resolved("review"), text="edited", textSha256="b" * 64)
        assert needs_extraction(obs, PV, MODEL, False) is True

    def test_a_new_observation_is_always_extracted(self):
        assert needs_extraction(valid_obs(status="new"), PV, MODEL, False) is True

    def test_force_overrides_everything(self):
        assert needs_extraction(self._resolved("review"), PV, MODEL, True) is True


class TestFailedExtractionsBackOff:
    def test_a_failure_is_not_retried_immediately(self):
        obs = _record_failure(valid_obs(text="x", textSha256="a" * 64),
                              "boom", PV, MODEL, now=T0)
        assert needs_extraction(obs, PV, MODEL, False, now=T0) is False
        assert needs_extraction(obs, PV, MODEL, False,
                                now=T0 + timedelta(hours=2)) is True

    def test_the_wait_grows(self):
        obs = valid_obs(text="x", textSha256="a" * 64)
        waits = []
        now = T0
        for _ in RETRY_BACKOFF_HOURS:
            obs = _record_failure(obs, "boom", PV, MODEL, now=now)
            nxt = datetime.fromisoformat(obs["nextRetryAt"])
            waits.append((nxt - now).total_seconds())
            now = nxt
        assert waits == sorted(waits) and waits[0] < waits[-1]

    def test_it_eventually_gives_up(self):
        obs = valid_obs(text="x", textSha256="a" * 64)
        now = T0
        for _ in range(len(RETRY_BACKOFF_HOURS) + 1):
            obs = _record_failure(obs, "boom", PV, MODEL, now=now)
            now += timedelta(days=30)
        assert obs["failureType"] == "permanent"
        assert needs_extraction(obs, PV, MODEL, False, now=now) is False, (
            "a permanently malformed post must not cost a call a day forever"
        )

    def test_giving_up_is_not_forever_if_the_input_changes(self):
        obs = valid_obs(text="x", textSha256="a" * 64)
        now = T0
        for _ in range(len(RETRY_BACKOFF_HOURS) + 1):
            obs = _record_failure(obs, "boom", PV, MODEL, now=now)
            now += timedelta(days=30)
        assert needs_extraction(obs, "v2", MODEL, False, now=now) is True

    def test_a_run_of_failures_costs_far_fewer_calls_than_runs(self):
        obs = valid_obs(text="x", textSha256="a" * 64)
        calls = 0
        for half_day in range(12):          # six days, two runs a day
            t = T0 + timedelta(hours=12 * half_day)
            if needs_extraction(obs, PV, MODEL, False, now=t):
                calls += 1
                obs = _record_failure(obs, "boom", PV, MODEL, now=t)
        assert calls <= 5, f"{calls} calls over 12 runs — backoff is not working"


# ============================================================== R15+ / D36

class TestCandidateIdentityIsStableForLife:
    def _obs(self, oid, ext, name="Erdős problem on unit distances"):
        return valid_obs(
            id=oid, sourceNativeId=oid, url=f"https://x.com/a/status/{oid}",
            externalIds=ext,
            extraction={"canonicalProblemName": name, "problemAliases": [],
                        "claimType": "new_result", "resultType": "proof",
                        "modelName": "GPT-5.6", "summary": "s"},
        )

    def test_an_arriving_identifier_does_not_change_the_id(self):
        cands, first, *_ = _upsert_candidate([], self._obs("o1", {}), None, "2026-07-24")
        cands, second, *_ = _upsert_candidate(
            cands, self._obs("o2", {"arxiv": ["2607.16356"]}), None, "2026-07-25")
        assert second == first, "the id moved when an identifier arrived"

    def test_one_problem_stays_one_candidate(self):
        cands = []
        for day, ext in enumerate(({}, {"arxiv": ["2607.1"]}, {"doi": ["10.1/x"]})):
            cands, _, *_ = _upsert_candidate(
                cands, self._obs(f"o{day}", ext), None, f"2026-07-2{4 + day}")
        assert len(cands) == 1
        assert cands[0]["externalIds"] == {"arxiv": ["2607.1"], "doi": ["10.1/x"]}
        assert cands[0]["observationIds"] == ["o0", "o1", "o2"]

    def test_a_late_identifier_merges_rather_than_renames(self):
        """Two records built under different names, revealed to be one problem."""
        cands, a, *_ = _upsert_candidate(
            [], self._obs("o1", {"arxiv": ["2607.9"]}, name="Unit distance problem"),
            None, "2026-07-24")
        cands, b, *_ = _upsert_candidate(
            cands, self._obs("o2", {"oeis": ["A1"]}, name="Erdős unit distances"),
            None, "2026-07-25")
        assert b != a and len(cands) == 2       # genuinely distinct so far
        cands, c, *_ = _upsert_candidate(
            cands, self._obs("o3", {"arxiv": ["2607.9"], "oeis": ["A1"]},
                             name="Something else entirely"),
            None, "2026-07-26")
        assert len(cands) == 1, "the shared identifiers did not merge them"
        assert c == a, "the surviving id must be the oldest, not a new one"
        assert set(cands[0]["mergedFrom"]) == {b}

    def test_a_merge_loses_nothing(self):
        cands, a, *_ = _upsert_candidate(
            [], self._obs("o1", {"arxiv": ["2607.9"]}, name="Name A"), None, "2026-07-24")
        cands, _, *_ = _upsert_candidate(
            cands, self._obs("o2", {"oeis": ["A1"]}, name="Name B"), None, "2026-07-25")
        cands, _, *_ = _upsert_candidate(
            cands, self._obs("o3", {"arxiv": ["2607.9"], "oeis": ["A1"]}, name="Name A"),
            None, "2026-07-26")
        merged = cands[0]
        assert set(merged["observationIds"]) == {"o1", "o2", "o3"}
        assert merged["externalIds"] == {"arxiv": ["2607.9"], "oeis": ["A1"]}
        assert merged["firstSeenAt"] == "2026-07-24", "the earliest sighting must survive"

    def test_genuinely_different_problems_stay_apart(self):
        cands, a, *_ = _upsert_candidate(
            [], self._obs("o1", {"erdos": ["728"]}, name="Erdős #728"), None, "2026-07-24")
        cands, b, *_ = _upsert_candidate(
            cands, self._obs("o2", {"erdos": ["782"]}, name="Erdős #782"), None, "2026-07-25")
        assert a != b and len(cands) == 2


# ============================================================== R10

class TestTweetTextPolicy:
    def test_resolved_text_becomes_an_excerpt(self):
        long = "x" * 500
        out = redact_resolved([valid_obs(status="extracted", text=long,
                                         textSha256="a" * 64)])
        assert out[0]["text"] is None
        assert len(out[0]["textExcerpt"]) <= EXCERPT_CHARS + 1
        assert out[0]["textSha256"] == "a" * 64, "provenance must survive"

    def test_short_text_is_not_mangled(self):
        out = redact_resolved([valid_obs(status="merged", text="short post")])
        assert out[0]["textExcerpt"] == "short post"

    def test_unresolved_text_is_left_alone(self):
        """It still has to be sent to the model; truncating first would silently
        degrade every extraction."""
        out = redact_resolved([valid_obs(status="new", text="y" * 500)])
        assert out[0]["text"] == "y" * 500 and out[0].get("textExcerpt") is None

    def test_the_url_is_always_kept(self):
        out = redact_resolved([valid_obs(status="extracted", text="z" * 500)])
        assert out[0]["url"] == "https://x.com/a/status/1"

    def test_redaction_survives_the_contract(self, tmp_path):
        out = redact_resolved([valid_obs(status="extracted", text="q" * 500)])
        store.write_records(tmp_path / "o.json", Observation, out)
