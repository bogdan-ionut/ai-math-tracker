"""Sprint 6.5 — the curator's workbench (R8).

Automation has been filling a review queue and a candidate store for several
sprints with no way to act on either except editing JSON by hand. A queue nobody
can work is a queue nobody works.

The tests that matter here are about what `promote` must **not** do. The single
strongest guarantee this project makes is that `data/results.json` is never
written by automation, and a promotion is the one operation whose entire purpose
is to change it. So it goes through a draft pull request, and the proposal
arrives with every judgement empty — a proposal pre-filled with an impact score
and an assessment would be inviting a rubber stamp.
"""
from __future__ import annotations

import json

import pytest

from scripts.automation import curate, store
from scripts.automation.policy import never_auto_write

NOW = "2026-07-26T00:00:00+00:00"


def cand(**over):
    base = {
        "id": "cand_arxiv_2607-1", "canonicalName": "Unit distance problem",
        "aliases": ["udp"], "family": "Combinatorics",
        "externalIds": {"arxiv": ["2607.1"]},
        "claims": [{"claimType": "new_result", "resultType": "proof",
                    "modelName": "GPT-5.6", "organization": "OpenAI",
                    "claimedAt": "2026-07-20", "summary": "Settled the bound.",
                    "observationId": "obs_1", "recordedAt": NOW}],
        "observationIds": ["obs_1"], "sources": ["https://x.com/a/status/1"],
        "status": "pending", "firstSeenAt": NOW, "lastSeenAt": NOW,
    }
    base.update(over)
    return base


class TestAProposalLeavesTheJudgementsEmpty:
    """Every field in neverAutoWriteFields is a judgement, not a fact."""

    @pytest.mark.parametrize("field", sorted(never_auto_write() - {"status"}))
    def test_no_protected_field_is_filled(self, field):
        assert curate.propose_record(cand(), []) [field] is None

    def test_status_enters_at_the_weakest_tier(self):
        record = curate.propose_record(cand(), [])
        assert record["status"] == curate.INITIAL_STATUS == "provisional"

    def test_a_proposal_is_never_audited(self):
        """The claim the whole site rests on."""
        record = curate.propose_record(cand(), [])
        assert record["status"] != "audited" and record["auditedAt"] is None

    def test_the_curator_is_told_what_they_still_owe(self):
        owed = curate.unresolved_fields(curate.propose_record(cand(), []))
        for field in ("status", "confidence", "impact", "assessment"):
            assert field in owed

    def test_observed_facts_are_carried_through(self):
        record = curate.propose_record(cand(), [])
        assert record["model"] == "GPT-5.6" and record["lab"] == "OpenAI"
        assert record["externalIds"] == {"arxiv": ["2607.1"]}
        assert record["sources"] == ["https://x.com/a/status/1"]
        assert record["claimedAt"] == "2026-07-20"

    def test_an_erdos_candidate_proposes_the_conventional_id(self):
        record = curate.propose_record(cand(externalIds={"erdos": ["728"]}), [])
        assert record["id"] == "erdos-728" and record["erdosNumber"] == "#728"

    def test_a_nameless_candidate_still_gets_a_usable_id(self):
        record = curate.propose_record(
            cand(externalIds={}, canonicalName="A very long name " * 8), [])
        assert record["id"] and " " not in record["id"] and len(record["id"]) <= 48


class TestPromoteNeverWritesTheRegistryDirectly:
    def test_a_dry_run_touches_nothing(self, monkeypatch):
        before = curate.REGISTRY.read_bytes()
        monkeypatch.setattr(curate, "_find", lambda i: ("candidate", cand()))
        monkeypatch.setattr(curate, "_observations_for", lambda c: [])
        plan = curate.promote("cand_arxiv_2607-1", dry_run=True)
        assert plan["dryRun"] is True and "opened" not in plan
        assert curate.REGISTRY.read_bytes() == before

    def test_a_dry_run_runs_no_git_command(self, monkeypatch):
        called = []
        monkeypatch.setattr(curate, "_git", lambda *a, **k: called.append(a) or "")
        monkeypatch.setattr(curate, "_find", lambda i: ("candidate", cand()))
        monkeypatch.setattr(curate, "_observations_for", lambda c: [])
        curate.promote("cand_arxiv_2607-1", dry_run=True)
        assert called == []

    def test_promoting_a_review_entry_is_refused(self, monkeypatch):
        monkeypatch.setattr(curate, "_find", lambda i: ("review", {"id": i}))
        with pytest.raises(curate.CurateError, match="not a candidate"):
            curate.promote("rev_1")

    def test_an_unknown_id_is_refused(self, monkeypatch):
        monkeypatch.setattr(store, "DATA_DIR", curate.ROOT / "nonexistent")
        with pytest.raises(curate.CurateError, match="no candidate or review entry"):
            curate.promote("cand_nope", dry_run=True)

    def test_a_dirty_tree_blocks_a_real_promotion(self, monkeypatch):
        monkeypatch.setattr(curate, "_find", lambda i: ("candidate", cand()))
        monkeypatch.setattr(curate, "_observations_for", lambda c: [])
        monkeypatch.setattr(curate, "_git",
                            lambda *a, **k: "M data/results.json" if a[0] == "status" else "")
        with pytest.raises(curate.CurateError, match="uncommitted changes"):
            curate.promote("cand_arxiv_2607-1")


class TestThePullRequestSaysWhatIsMissing:
    def test_the_body_lists_every_owed_judgement(self):
        c = cand()
        record = curate.propose_record(c, [])
        body = curate.pr_body(c, record, [])
        for field in curate.unresolved_fields(record):
            assert f"`{field}`" in body

    def test_the_body_states_the_audited_bar(self):
        c = cand()
        body = curate.pr_body(c, curate.propose_record(c, []), [])
        assert "announcement is not a confirmation" in body

    def test_a_duplicate_is_flagged_at_the_top(self, monkeypatch):
        monkeypatch.setattr(curate, "_duplicate_of", lambda r: "erdos-1044")
        c = cand()
        body = curate.pr_body(c, curate.propose_record(c, []), [])
        assert body.startswith("> **Possible duplicate of `erdos-1044`**")

    def test_the_evidence_tier_is_reported(self):
        c = cand()
        obs = [{"externalIds": {"github": ["a/b"]}}]
        assert "**referenced**" in curate.pr_body(c, curate.propose_record(c, obs), obs)

    def test_a_real_duplicate_in_the_registry_is_detected(self):
        registry = json.loads(curate.REGISTRY.read_text())
        existing = registry[0]
        record = curate.propose_record(
            cand(externalIds=existing.get("externalIds") or {"erdos": ["1044"]}), [])
        assert curate._duplicate_of(record) is not None


class TestDismissTouchesOnlyTheQueue:
    def test_an_entry_is_resolved_with_a_reason(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        store.write_json(store.review_queue_path(),
                         [{"id": "rev_1", "reason": "no_corroboration", "status": "open"}])
        out = curate.dismiss("rev_1", why="already tracked as erdos-728")
        assert out["status"] == "resolved"
        rows = store.read_json(store.review_queue_path(), [])
        assert rows[0]["status"] == "resolved"
        assert rows[0]["resolution"] == "already tracked as erdos-728"

    def test_resolving_twice_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        store.write_json(store.review_queue_path(),
                         [{"id": "rev_1", "status": "resolved"}])
        with pytest.raises(curate.CurateError, match="already resolved"):
            curate.dismiss("rev_1", why="x")

    def test_dismissing_never_touches_the_registry(self, tmp_path, monkeypatch):
        before = curate.REGISTRY.read_bytes()
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        store.write_json(store.review_queue_path(), [{"id": "rev_1", "status": "open"}])
        curate.dismiss("rev_1", why="x")
        assert curate.REGISTRY.read_bytes() == before


class TestTheCommandsRun:
    @pytest.mark.parametrize("argv", [["queue"], ["candidates"]])
    def test_listing_an_empty_store_is_not_an_error(self, argv, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        assert curate.main(argv) == 0

    def test_show_on_a_missing_id_exits_nonzero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        assert curate.main(["show", "nope"]) == 1
        assert "error:" in capsys.readouterr().err
