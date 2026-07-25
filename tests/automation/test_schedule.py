"""Sprint 5 tests: meaningful-change detection and workflow safety.

The workflow itself cannot be executed here, so it is asserted structurally —
the properties that make the topology safe (acyclic, least-privilege, no secret
echo) are checked against the YAML.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import yaml  # type: ignore[import-untyped]

from scripts.automation.changes import VOLATILE_KEYS, _strip_volatile, assess

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
DISCOVER = WORKFLOWS / "discover.yml"
DEPLOY = WORKFLOWS / "deploy-pages.yml"


def load_wf(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- volatility

class TestVolatileStripping:
    def test_timestamps_are_ignored(self):
        a = {"lastRunAt": "2026-07-25T00:00:00Z", "count": 3}
        b = {"lastRunAt": "2026-07-26T09:33:00Z", "count": 3}
        assert _strip_volatile(a) == _strip_volatile(b)

    def test_real_change_survives(self):
        a = {"lastRunAt": "x", "count": 3}
        b = {"lastRunAt": "y", "count": 4}
        assert _strip_volatile(a) != _strip_volatile(b)

    def test_nested_timestamps_ignored(self):
        a = {"perQuery": [{"queryId": "q", "runAt": "t1", "returned": 5}]}
        b = {"perQuery": [{"queryId": "q", "runAt": "t2", "returned": 5}]}
        assert _strip_volatile(a) == _strip_volatile(b)

    def test_nested_real_change_survives(self):
        a = {"perQuery": [{"queryId": "q", "runAt": "t", "returned": 5}]}
        b = {"perQuery": [{"queryId": "q", "runAt": "t", "returned": 9}]}
        assert _strip_volatile(a) != _strip_volatile(b)

    def test_lastseen_is_volatile_but_content_is_not(self):
        """An observation seen again is not news; an observation that gained a
        link is."""
        a = {"id": "o1", "lastSeenAt": "t1", "links": ["a"]}
        b = {"id": "o1", "lastSeenAt": "t2", "links": ["a"]}
        c = {"id": "o1", "lastSeenAt": "t2", "links": ["a", "b"]}
        assert _strip_volatile(a) == _strip_volatile(b)
        assert _strip_volatile(a) != _strip_volatile(c)

    def test_volatile_key_set_is_explicit(self):
        assert {"lastRunAt", "runAt", "lastSeenAt"} <= VOLATILE_KEYS

    def test_key_order_does_not_matter(self):
        assert _strip_volatile({"a": 1, "b": 2}) == _strip_volatile({"b": 2, "a": 1})


@pytest.fixture()
def repo(tmp_path):
    """A throwaway git repo shaped like this one.

    These tests used to run against the live working tree, which only passed
    because the `unexpected` check was unreachable — any uncommitted edit would
    have broken them. Now that the check works, the logic needs a controlled
    repository rather than whatever the developer happens to have open.
    """
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True,
                       capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "data" / "automation").mkdir(parents=True)
    (tmp_path / "data" / "results.json").write_text('[{"id": "a"}]\n')
    for name in ("observations.json", "candidates.json", "review_queue.json"):
        (tmp_path / "data" / "automation" / name).write_text("[]\n")
    (tmp_path / "data" / "automation" / "processing_state.json").write_text(
        '{"lastRunAt": "2026-07-25T00:00:00+00:00", "counters": {"runs": 1}}\n')
    git("add", "-A")
    git("commit", "-q", "-m", "seed")
    return tmp_path


class TestAssessInRepo:
    def test_clean_tree_reports_nothing_to_commit(self, repo):
        rep = assess(repo)
        assert rep["shouldCommit"] is False
        assert rep["unexpected"] == []

    def test_assess_shape(self, repo):
        rep = assess(repo)
        for key in ("changed", "substantive", "incidental", "unexpected",
                    "shouldCommit", "reason"):
            assert key in rep

    def test_substantive_change_triggers_a_commit(self, repo):
        (repo / "data" / "automation" / "candidates.json").write_text(
            '[{"id": "cand_1", "canonicalName": "X"}]\n')
        rep = assess(repo)
        assert rep["shouldCommit"] is True
        assert "data/automation/candidates.json" in rep["substantive"]

    def test_timestamp_only_change_does_not_trigger_a_commit(self, repo):
        (repo / "data" / "automation" / "processing_state.json").write_text(
            '{"lastRunAt": "2026-07-26T09:00:00+00:00", "counters": {"runs": 1}}\n')
        rep = assess(repo)
        assert rep["shouldCommit"] is False
        assert rep["unexpected"] == []

    def test_counter_change_alone_still_does_not_commit(self, repo):
        """Counters move without anything substantive happening."""
        (repo / "data" / "automation" / "processing_state.json").write_text(
            '{"lastRunAt": "2026-07-26T09:00:00+00:00", "counters": {"runs": 2}}\n')
        assert assess(repo)["shouldCommit"] is False

    def test_touching_the_curated_registry_is_flagged(self, repo):
        """The check this whole function exists for. It was unreachable before:
        git status was scoped to data/automation, then filtered for paths NOT
        under data/automation, so the list could never be non-empty."""
        (repo / "data" / "results.json").write_text('[{"id": "a", "impact": 5}]\n')
        rep = assess(repo)
        assert "data/results.json" in rep["unexpected"]

    def test_stray_source_edit_is_flagged(self, repo):
        (repo / "rogue.py").write_text("print('hi')\n")
        assert "rogue.py" in assess(repo)["unexpected"]

    def test_run_artifacts_at_root_are_not_flagged(self, repo):
        """A run writes these and uploads them; they are not evidence of a
        run touching something it should not."""
        for name in ("ingest.json", "extract.json", "pipeline.json"):
            (repo / name).write_text("{}\n")
        assert assess(repo)["unexpected"] == []

    def test_new_automation_file_is_substantive(self, repo):
        (repo / "data" / "automation" / "aliases.json").write_text('{"byAlias": {}}\n')
        rep = assess(repo)
        assert rep["shouldCommit"] is True


# ---------------------------------------------------------------- workflow topology

class TestWorkflowTopology:
    @pytest.fixture(scope="class")
    def discover(self):
        return load_wf(DISCOVER)

    @pytest.fixture(scope="class")
    def deploy(self):
        return load_wf(DEPLOY)

    def test_discover_runs_on_schedule_and_manually(self, discover):
        on = discover[True] if True in discover else discover["on"]
        assert "schedule" in on and "workflow_dispatch" in on

    def test_cron_is_off_the_hour(self, discover):
        on = discover[True] if True in discover else discover["on"]
        minute = on["schedule"][0]["cron"].split()[0]
        assert minute != "0", "on-the-hour crons are delayed by GitHub under load"

    def test_cron_matches_config(self, discover):
        on = discover[True] if True in discover else discover["on"]
        cfg = json.loads((ROOT / "config" / "automation.json").read_text())
        assert on["schedule"][0]["cron"] == cfg["schedule"]["cronUtc"]

    def test_only_collector_can_write(self, discover, deploy):
        assert discover["permissions"]["contents"] == "write"
        assert deploy["permissions"]["contents"] == "read"

    def test_deploy_has_no_commit_step(self, deploy):
        """This is what makes the graph acyclic — no [skip ci] guard needed."""
        blob = DEPLOY.read_text()
        assert "git commit" not in blob and "git push" not in blob

    def test_discover_does_not_cancel_itself(self, discover):
        assert discover["concurrency"]["cancel-in-progress"] is False, (
            "cancelling a half-written data run risks a torn state"
        )

    def test_discover_has_a_timeout(self, discover):
        assert discover["jobs"]["discover"]["timeout-minutes"] <= 60

    def test_secrets_are_never_echoed(self):
        blob = DISCOVER.read_text()
        # the value may be referenced, but never printed
        assert "echo ${{ secrets" not in blob
        assert "echo $TWITTERAPI_IO_KEY" not in blob
        assert "echo $GEMINI_API_KEY" not in blob
        # length is fine to print; the value is not
        assert "${#TWITTERAPI_IO_KEY}" in blob

    def test_only_automation_data_is_committed(self):
        blob = DISCOVER.read_text()
        assert "git add data/automation" in blob
        assert "git add ." not in blob and "git add -A" not in blob

    def test_curated_registry_is_never_added(self):
        blob = DISCOVER.read_text()
        assert "data/results.json" not in blob.split("Validate generated data")[0]

    def test_status_doc_is_not_written_by_cron(self):
        """CURRENT_STATUS.md is human-owned — see assessment §2.7."""
        assert "CURRENT_STATUS" not in DISCOVER.read_text()

    def test_dry_run_defaults_to_true_for_manual_runs(self, discover):
        on = discover[True] if True in discover else discover["on"]
        assert on["workflow_dispatch"]["inputs"]["dry_run"]["default"] is True

    def test_schedule_starts_in_dry_run(self):
        """Deliberate: observe for a few days before writing anything."""
        cfg = json.loads((ROOT / "config" / "automation.json").read_text())
        assert cfg["schedule"]["dryRunOnSchedule"] is True, (
            "flip this only after reading the telemetry"
        )

    def test_automation_can_be_disabled_from_config(self, discover):
        blob = DISCOVER.read_text()
        assert "schedule']['enabled'" in blob or 'schedule"]["enabled"' in blob

    def test_run_report_is_uploaded(self, discover):
        steps = discover["jobs"]["discover"]["steps"]
        assert any("upload-artifact" in str(s.get("uses", "")) for s in steps)


class TestWorkflowInventory:
    def test_expected_workflows_exist(self):
        names = {p.name for p in WORKFLOWS.glob("*.yml")}
        assert {"discover.yml", "deploy-pages.yml", "smoke-twitter.yml",
                "smoke-gemini.yml", "probe-twitter-syntax.yml"} <= names

    def test_no_other_workflow_writes_contents(self):
        for path in WORKFLOWS.glob("*.yml"):
            if path.name == "discover.yml":
                continue
            wf = load_wf(path)
            perms = wf.get("permissions") or {}
            assert perms.get("contents", "read") == "read", (
                f"{path.name} should not have write access"
            )


class TestTerminalFailures:
    """402 means out of credit. Retrying cannot help, and retrying it for every
    remaining query turns one problem into fourteen."""

    def test_twitter_402_is_not_retried(self, monkeypatch):
        import httpx
        from scripts.automation.twitter import TwitterApiClient, TwitterApiError

        calls = {"n": 0}

        class Resp:
            status_code = 402
            headers: dict = {}

        def fake(self, url, params, headers):
            calls["n"] += 1
            return Resp()

        monkeypatch.setattr(httpx.Client, "get", fake)
        c = TwitterApiClient(api_key="k", max_retries=3, backoff=0, min_interval=0)
        with pytest.raises(TwitterApiError) as e:
            c.search("anything")
        assert calls["n"] == 1, "402 must not be retried"
        assert "out of credit" in str(e.value)

    def test_gemini_402_is_not_retried(self, monkeypatch):
        import httpx
        from scripts.automation.gemini import GeminiClient, GeminiError

        calls = {"n": 0}

        class Resp:
            status_code = 402
            headers: dict = {}

        def fake(self, url, json, headers):  # noqa: A002
            calls["n"] += 1
            return Resp()

        monkeypatch.setattr(httpx.Client, "post", fake)
        c = GeminiClient(api_key="k", max_retries=3, backoff=0, min_interval=0)
        with pytest.raises(GeminiError):
            c.generate_json("p", {})
        assert calls["n"] == 1


class TestCiWorkflow:
    """CI is what turns the suite from documentation into protection."""

    @pytest.fixture(scope="class")
    def ci(self):
        return load_wf(WORKFLOWS / "ci.yml")

    def test_runs_on_push_and_pull_request(self, ci):
        on = ci[True] if True in ci else ci["on"]
        assert "push" in on and "pull_request" in on

    def test_runs_pytest(self):
        assert "pytest" in (WORKFLOWS / "ci.yml").read_text()

    def test_needs_no_secrets(self, ci):
        """The suite must stay runnable by a contributor with no keys."""
        blob = (WORKFLOWS / "ci.yml").read_text()
        assert "secrets." not in blob, "CI must not depend on repository secrets"

    def test_is_read_only(self, ci):
        assert ci["permissions"]["contents"] == "read"

    def test_asserts_build_does_not_touch_the_registry(self):
        assert "data/results.json" in (WORKFLOWS / "ci.yml").read_text()

    def test_has_a_guardrail_job(self, ci):
        assert "guardrails" in ci["jobs"]


class TestPushSafety:
    def test_push_rebases_before_retrying(self):
        blob = DISCOVER.read_text()
        assert "pull --rebase" in blob, (
            "a human push between checkout and push would otherwise lose the run"
        )

    def test_push_is_bounded(self):
        blob = DISCOVER.read_text()
        assert "for attempt in" in blob and "exit 1" in blob

    def test_push_failure_is_loud(self):
        assert "could not push after 3 attempts" in DISCOVER.read_text()
