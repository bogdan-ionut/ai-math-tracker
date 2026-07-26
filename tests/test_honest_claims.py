"""F1 — the site may not assert what the registry contradicts.

Two sentences on the page were false, and both were the kind a reader has no way
to check for themselves:

  1. The methodology said `claimedAt` and `auditedAt` "are kept separate — an
     announcement is never shown as a confirmation". Every audited record has the
     two dates equal, so the split this project calls its spine carried no
     information at all.
  2. Nothing anywhere mentioned sources, while 12 of 17 audited records — the
     only tier allowed to be green — point at nothing. `build_data.py` warned
     about it on every single run and nothing downstream ever saw the number.

The fix was not to rewrite the sentences. A corrected sentence rots the moment
the data moves. The figures are computed in `build_data.py` and the copy is
rendered from them, so the claim and the evidence cannot drift apart. These tests
hold that line.
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
from schema import MathematicalResult  # noqa: E402

PUBLIC = ROOT / "public" / "data"


@pytest.fixture(scope="module")
def summary():
    subprocess.run([sys.executable, "scripts/build_data.py"], cwd=ROOT, check=True,
                   capture_output=True)
    return json.loads((PUBLIC / "summary.json").read_text())


@pytest.fixture(scope="module")
def registry():
    return json.loads((ROOT / "data" / "results.json").read_text())


def rec(**over):
    base = {
        "id": "rec-a", "title": "Title", "family": "Family", "description": "d",
        "resultType": "proof", "status": "audited", "claimedAt": "2026-01-01",
        "auditedAt": "2026-01-01", "lab": "L", "labKey": "oa", "model": "M",
        "count": 1, "isOpenProblem": True, "sources": [], "confidence": 0.9,
    }
    base.update(over)
    return MathematicalResult(**base)


class TestSourceCoverageIsMeasuredNotAsserted:
    def test_it_matches_the_registry_exactly(self, summary, registry):
        expected = sum(1 for r in registry if not r.get("sources"))
        assert summary["sourceCoverage"]["recordsWithoutSource"] == expected

    def test_the_audited_gap_matches_the_registry(self, summary, registry):
        expected = sum(1 for r in registry
                       if r["status"] == "audited" and not r.get("sources"))
        assert summary["sourceCoverage"]["auditedWithoutSource"] == expected

    def test_every_record_is_in_exactly_one_bucket(self, summary, registry):
        cov = summary["sourceCoverage"]
        assert cov["recordsWithSource"] + cov["recordsWithoutSource"] == len(registry)

    def test_it_counts_records_not_problems(self):
        """A 44-problem batch carries one source URL or none. Counting it as 44
        sourced problems would restate the overstatement this figure exposes."""
        cov = build_data.source_coverage([rec(id="batch", count=44, sources=["https://example.org/a"])])
        assert cov["recordsWithSource"] == 1

    def test_a_fully_sourced_registry_reports_zero(self):
        cov = build_data.source_coverage([rec(sources=["https://example.org/a"]), rec(id="rec-b", sources=["https://example.org/b"])])
        assert cov["recordsWithoutSource"] == 0 and cov["auditedWithoutSource"] == 0


class TestAuditDatingTellsTheTruth:
    def test_the_current_registry_has_no_informative_split(self, summary):
        """Documenting reality, not endorsing it. If curation later dates an
        audit properly this test's expectation flips — and so does the page."""
        d = summary["auditDating"]
        assert d["auditedRecords"] == d["sameDayAsClaim"]
        assert d["splitIsInformative"] is False

    def test_it_matches_the_registry(self, summary, registry):
        audited = [r for r in registry if r["status"] == "audited"]
        same = [r for r in audited if r.get("auditedAt") == r.get("claimedAt")]
        assert summary["auditDating"]["auditedRecords"] == len(audited)
        assert summary["auditDating"]["sameDayAsClaim"] == len(same)

    def test_a_real_lag_makes_the_split_informative(self):
        """The flag must flip the moment one audit is dated after its claim."""
        d = build_data.audit_dating([
            rec(claimedAt="2026-01-01", auditedAt="2026-01-01"),
            rec(id="rec-b", claimedAt="2026-01-01", auditedAt="2026-03-01"),
        ])
        assert d["splitIsInformative"] is True and d["laterThanClaim"] == 1

    def test_unaudited_records_are_not_counted(self):
        d = build_data.audit_dating([rec(status="reported", auditedAt=None)])
        assert d["auditedRecords"] == 0 and d["splitIsInformative"] is False


class TestThePageRendersTheFiguresRatherThanRepeatingThem:
    """The copy is generated from the numbers, so it cannot go stale."""

    @staticmethod
    def _rendered(name: str) -> str:
        """Source with block comments stripped.

        The components document the false sentences they replaced, so a naive
        substring search over the whole file fails on the explanation of the fix.
        What must not contain the old copy is what ships to the browser."""
        import re
        text = (ROOT / "src" / "components" / f"{name}.tsx").read_text()
        return re.sub(r"/\*.*?\*/", "", text, flags=re.S)

    @property
    def METHODOLOGY(self) -> str:
        return self._rendered("MethodologyFooter")

    @property
    def MASTHEAD(self) -> str:
        return self._rendered("Masthead")

    def test_the_false_sentence_is_gone(self):
        assert "never shown as a confirmation" not in self.METHODOLOGY
        assert "are kept separate" not in self.METHODOLOGY

    def test_the_dating_claim_is_conditional_on_the_data(self):
        assert "splitIsInformative" in self.METHODOLOGY, (
            "the claim must be gated on the measurement, not written down"
        )

    def test_no_source_figure_is_hardcoded(self):
        for literal in ("12 of 17", "27 of 40", "12 audited"):
            assert literal not in self.METHODOLOGY
            assert literal not in self.MASTHEAD

    def test_the_masthead_shows_the_gap(self):
        assert "auditedWithoutSource" in self.MASTHEAD

    def test_the_deficiency_is_never_green(self):
        """`accent` is green and green means audited. An unsourced count is a
        deficiency, not an achievement."""
        assert "muted" in self.MASTHEAD
        block = self.MASTHEAD.split("auditedWithoutSource > 0")[1][:300]
        assert "accent" not in block
