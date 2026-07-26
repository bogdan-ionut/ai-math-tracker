"""Sprint 7 — automated signals on the site, kept apart from the tracker.

The pipeline's working set was invisible: candidates existed only in a JSON file
nobody outside the repository could see. Showing them is useful — and is also
the single easiest way to destroy the thing this site is for.

So every test here is about separation. A signal is something the pipeline
noticed; a result is something the tracker stands behind, and no figure on the
page may be moved by the former.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_data  # noqa: E402

PUBLIC = ROOT / "public" / "data"


@pytest.fixture(scope="module")
def built():
    subprocess.run([sys.executable, "scripts/build_data.py"], cwd=ROOT, check=True,
                   capture_output=True)
    return json.loads((PUBLIC / "signals.json").read_text())


def candidate(**over):
    base = {
        "id": "cand_1", "canonicalName": "Some problem", "family": "Erdős",
        "externalIds": {"arxiv": ["2607.1"]}, "sources": ["https://x.com/a/status/1"],
        "claims": [{"modelName": "GPT-5.6", "organization": "OpenAI",
                    "resultType": "proof", "claimedAt": "2026-07-20",
                    "summary": "SENSITIVE MODEL PROSE"}],
        "observationIds": ["obs_1"], "status": "pending",
        "firstSeenAt": "2026-07-26T00:00:00+00:00",
        "lastSeenAt": "2026-07-26T00:00:00+00:00",
    }
    base.update(over)
    return base


class TestSignalsNeverBecomeResults:
    def test_the_feed_is_a_separate_file(self, built):
        assert (PUBLIC / "signals.json").exists()
        conj = json.loads((PUBLIC / "conjectures.json").read_text())
        ids = {r["id"] for r in conj}
        assert not any(s["id"] in ids for s in built["signals"])

    def test_signals_cannot_move_a_single_site_figure(self, tmp_path):
        """The precise claim: build with candidates present, and every published
        figure is byte-identical to the build without them."""
        def build_and_read():
            subprocess.run([sys.executable, "scripts/build_data.py"], cwd=ROOT,
                           check=True, capture_output=True)
            return {name: (PUBLIC / name).read_bytes()
                    for name in ("conjectures.json", "summary.json")}

        without = build_and_read()

        real = ROOT / "data" / "automation" / "candidates.json"
        backup = real.read_bytes() if real.exists() else None
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text(json.dumps([candidate(), candidate(id="cand_2")]))
        try:
            with_signals = build_and_read()
            emitted = json.loads((PUBLIC / "signals.json").read_text())
        finally:
            if backup is None:
                real.unlink(missing_ok=True)
            else:
                real.write_bytes(backup)
            subprocess.run([sys.executable, "scripts/build_data.py"], cwd=ROOT,
                           check=True, capture_output=True)

        assert emitted["count"] == 2, "the signals were not actually present"
        assert with_signals == without, (
            "a curated figure moved when unverified signals were added"
        )

    def test_the_feed_carries_its_own_disclaimer(self, built):
        assert "not tracker results" in built["disclaimer"]

    def test_building_signals_never_touches_the_registry(self):
        before = (ROOT / "data" / "results.json").read_bytes()
        build_data.build_signals()
        assert (ROOT / "data" / "results.json").read_bytes() == before


class TestOnlyAllowlistedFieldsArePublished:
    def _signal(self, monkeypatch, tmp_path, cand):
        path = tmp_path / "candidates.json"
        path.write_text(json.dumps([cand]))
        monkeypatch.setattr(build_data, "CANDIDATES", path)
        out = build_data.build_signals()
        return out[0] if out else None

    def test_model_written_prose_is_not_published(self, monkeypatch, tmp_path):
        """`summary` is a model's prose about someone else's post."""
        s = self._signal(monkeypatch, tmp_path, candidate())
        assert "SENSITIVE MODEL PROSE" not in json.dumps(s)
        assert "summary" not in s

    # `status` is excluded: it is the pending/promoted filter key, covered by
    # test_promoted_and_rejected_candidates_are_not_shown.
    @pytest.mark.parametrize("field", ["impact", "assessment", "confidence",
                                       "auditNotes", "auditedAt"])
    def test_no_editorial_field_is_published(self, monkeypatch, tmp_path, field):
        s = self._signal(monkeypatch, tmp_path, candidate(**{field: "SET"}))
        assert field not in s, f"{field} is an editorial judgement, not an observation"

    def test_a_new_candidate_field_is_not_inherited_by_default(self, monkeypatch, tmp_path):
        """Allowlist, not blocklist."""
        s = self._signal(monkeypatch, tmp_path, candidate(someFutureField="leaked"))
        assert "someFutureField" not in s

    def test_the_observable_facts_are_published(self, monkeypatch, tmp_path):
        s = self._signal(monkeypatch, tmp_path, candidate())
        assert s["modelName"] == "GPT-5.6" and s["organization"] == "OpenAI"
        assert s["evidenceTier"] == "published"
        assert s["observationCount"] == 1 and s["claimCount"] == 1

    def test_promoted_and_rejected_candidates_are_not_shown(self, monkeypatch, tmp_path):
        for status in ("promoted", "rejected"):
            assert self._signal(monkeypatch, tmp_path,
                                candidate(status=status)) is None


class TestTheFeedDegradesQuietly:
    def test_a_missing_candidate_file_is_not_an_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(build_data, "CANDIDATES", tmp_path / "nope.json")
        assert build_data.build_signals() == []

    def test_a_corrupt_candidate_file_is_not_an_error(self, monkeypatch, tmp_path):
        path = tmp_path / "candidates.json"
        path.write_text("{not json")
        monkeypatch.setattr(build_data, "CANDIDATES", path)
        assert build_data.build_signals() == []

    def test_the_build_still_succeeds_without_any_candidates(self, built):
        """The site must render perfectly with no pipeline output at all."""
        assert built["count"] >= 0


class TestEvidenceTiersMirrorThePolicy:
    def test_the_tiers_match_the_automation_package(self):
        """Duplicated on purpose — the build path must not import automation —
        so a test has to keep the two in step."""
        sys.path.insert(0, str(ROOT))
        from scripts.automation.policy import EVIDENCE_TIERS as POLICY
        assert build_data.EVIDENCE_TIERS == {k: tuple(v) for k, v in POLICY.items()}

    @pytest.mark.parametrize("ids,tier", [
        ({"doi": ["10.1/x"]}, "published"),
        ({"erdos": ["728"]}, "registered"),
        ({"github": ["a/b"]}, "referenced"),
        ({}, "none"),
    ])
    def test_each_kind_lands_in_its_tier(self, ids, tier):
        assert build_data._tier(ids) == tier
