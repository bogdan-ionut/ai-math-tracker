"""Sprint 5.5 — the plan run, offline.

The scheduled dry run skipped extraction and the pipeline entirely (R1): it
called TwitterAPI.io and stopped. Everything downstream — extraction, matching,
the judge, the merge guardrails — had only ever been exercised against fixtures
and stub models, and the gate to enabling live writes was going to be evidence
that had never been collected.

`run_plan` runs the ordinary live code into a temporary copy of the store, so
the planned run and the real run are the same code path. The promise it makes
is narrow and absolute: **the repository does not move.** These tests are about
that promise, including the case where it is broken — a guardrail that reports
success when it has failed is worse than none.
"""
from __future__ import annotations

import json

import pytest

from scripts.automation import run_plan


class TestTheRepositoryIsNotTouched:
    def test_a_clean_run_reports_untouched(self):
        """Fingerprint the real store, change nothing, fingerprint again."""
        report = run_plan._finish(
            before=run_plan.fingerprint(run_plan.REAL_DATA),
            sandbox=run_plan.REAL_DATA, stages={},
        )
        assert report["repositoryUntouched"] is True
        assert report["repositoryFilesTouched"] == []
        assert report["registryUntouched"] is True

    def test_a_changed_file_is_reported_not_swallowed(self, monkeypatch):
        """The check must measure, not assume. If the sandbox leaks, say so."""
        monkeypatch.setattr(run_plan, "fingerprint",
                            lambda d: {"observations.json": "AFTER",
                                       "data/results.json": "reg"})
        report = run_plan._finish(
            before={"observations.json": "BEFORE", "data/results.json": "reg"},
            sandbox=run_plan.REAL_DATA, stages={},
        )
        assert report["repositoryUntouched"] is False
        assert report["repositoryFilesTouched"] == ["observations.json"]

    def test_a_touched_registry_is_called_out_separately(self, monkeypatch):
        monkeypatch.setattr(run_plan, "fingerprint",
                            lambda d: {"data/results.json": "MUTATED"})
        report = run_plan._finish(before={"data/results.json": "reg"},
                                  sandbox=run_plan.REAL_DATA, stages={})
        assert report["registryUntouched"] is False

    def test_the_registry_is_always_fingerprinted(self):
        """Even though it lives outside data/automation and no stage should ever
        open it — which is exactly why it is checked."""
        assert "data/results.json" in run_plan.fingerprint(run_plan.REAL_DATA)

    def test_every_store_file_is_fingerprinted(self):
        fp = run_plan.fingerprint(run_plan.REAL_DATA)
        for name in run_plan.TRACKED:
            assert name in fp


class TestTheDiffIsHonest:
    def _sandbox(self, tmp_path, rows):
        (tmp_path / "candidates.json").write_text(json.dumps(rows))
        return tmp_path

    def test_added_records_are_listed_by_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(run_plan, "REAL_DATA", tmp_path / "real")
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "candidates.json").write_text(json.dumps([{"id": "c1"}]))
        sandbox = self._sandbox(tmp_path, [{"id": "c1"}, {"id": "c2"}])
        delta = run_plan.diff_stores(sandbox)["candidates.json"]
        assert delta["added"] == ["c2"] and delta["removed"] == []
        assert (delta["recordsBefore"], delta["recordsAfter"]) == (1, 2)

    def test_an_unchanged_file_is_not_reported_as_a_change(self, tmp_path, monkeypatch):
        monkeypatch.setattr(run_plan, "REAL_DATA", tmp_path / "real")
        (tmp_path / "real").mkdir()
        rows = json.dumps([{"id": "c1"}])
        (tmp_path / "real" / "candidates.json").write_text(rows)
        (tmp_path / "candidates.json").write_text(rows)
        assert "candidates.json" not in run_plan.diff_stores(tmp_path)

    def test_removals_are_surfaced(self, tmp_path, monkeypatch):
        """Nothing should ever remove a record. If a plan run says it would,
        that is the most important line in the report."""
        monkeypatch.setattr(run_plan, "REAL_DATA", tmp_path / "real")
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "candidates.json").write_text(
            json.dumps([{"id": "c1"}, {"id": "c2"}]))
        (tmp_path / "candidates.json").write_text(json.dumps([{"id": "c1"}]))
        assert run_plan.diff_stores(tmp_path)["candidates.json"]["removed"] == ["c2"]


class TestTheExitCode:
    def _report(self, **over):
        base = {"ok": True, "repositoryUntouched": True, "registryUntouched": True,
                "stages": {}, "wouldChange": {}, "repositoryFilesTouched": [],
                "aborted": None, "mode": "plan"}
        base.update(over)
        return base

    @pytest.mark.parametrize("over,expected", [
        ({}, 0),
        ({"repositoryUntouched": False, "repositoryFilesTouched": ["x"]}, 2),
        ({"registryUntouched": False}, 2),
        ({"ok": False, "aborted": "ingest failed"}, 1),
    ])
    def test_a_leak_fails_the_run_whatever_else_happened(
        self, over, expected, monkeypatch, tmp_path
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(run_plan, "run", lambda **_: self._report(**over))
        monkeypatch.setattr("sys.argv", ["run_plan"])
        assert run_plan.main() == expected

    def test_the_report_is_always_written(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(run_plan, "run", lambda **_: self._report())
        monkeypatch.setattr("sys.argv", ["run_plan"])
        run_plan.main()
        assert json.loads((tmp_path / "plan_run.json").read_text())["ok"] is True


class TestPrintingNeverCrashes:
    """The report is what a human reads before flipping the live-write switch;
    it must survive a partial run."""

    def test_an_aborted_run_still_prints(self, capsys):
        run_plan._print({
            "stages": {"ingest": {"ok": False}}, "wouldChange": {},
            "repositoryUntouched": True, "registryUntouched": True,
            "repositoryFilesTouched": [],
        })
        assert "guardrails" in capsys.readouterr().out

    def test_a_leak_is_printed_as_an_error_annotation(self, capsys):
        run_plan._print({
            "stages": {}, "wouldChange": {}, "repositoryUntouched": False,
            "registryUntouched": False, "repositoryFilesTouched": ["observations.json"],
        })
        assert "::error::" in capsys.readouterr().out
