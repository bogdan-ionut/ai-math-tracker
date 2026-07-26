"""Tests for the query taxonomy, builder and calibration.

These lock in the calibration result so a future edit to the taxonomy cannot
silently reduce recall or let obvious noise through.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.automation.calibrate import calibrate
from scripts.automation.query_builder import (
    MAX_QUERY_CHARS,
    build_queries,
    load_taxonomy,
    query_matches,
    which_queries_match,
)

ROOT = Path(__file__).resolve().parents[2]
GOLD = json.loads((ROOT / "tests" / "automation" / "fixtures" / "gold_set.json").read_text())


@pytest.fixture(scope="module")
def queries():
    return build_queries()


class TestBuilder:
    def test_every_enabled_family_builds(self, queries):
        tax = load_taxonomy()
        enabled = {f["id"] for f in tax["families"] if f.get("enabled", True)}
        # A family may ship as several shards (K10 OR-term cap), so it is the
        # family, not the query id, that must be present.
        assert enabled <= {q.family for q in queries}

    def test_ids_are_unique(self, queries):
        ids = [q.id for q in queries]
        assert len(ids) == len(set(ids))

    def test_queries_respect_length_limit(self, queries):
        for q in queries:
            assert len(q.query) <= MAX_QUERY_CHARS, f"{q.id} is {len(q.query)} chars"

    def test_only_verified_operators_are_used(self, queries):
        """Guards against reintroducing an operator the probe did not confirm."""
        verified_prefixes = ("lang:", "-filter:retweets", "url:", "from:", "since:", "until:")
        for q in queries:
            for tok in q.query.split():
                if ":" in tok and not tok.startswith("("):
                    clean = tok.lstrip("-(").rstrip(")")
                    if "://" in clean or clean.startswith(('"', "'")):
                        continue
                    assert tok.startswith(verified_prefixes) or ":" not in clean.split('"')[0], (
                        f"{q.id} uses unverified operator {tok!r}"
                    )

    def test_retweets_excluded_at_source(self, queries):
        # verified supported; saves quota before dedup has to do the work
        assert all("-filter:retweets" in q.query for q in queries)

    def test_unicode_terms_survive_building(self, queries):
        shards = [q for q in queries if q.family == "problem-registries"]
        assert shards
        # The registry names live in the group that is never split, so every
        # shard must carry them — losing them from one would silently narrow it.
        for s in shards:
            assert "Erdős" in s.query and "Erdos" in s.query

    def test_tiers_carry_caps(self, queries):
        for q in queries:
            assert q.max_results > 0
            assert q.tier in (1, 2, 3)

    def test_broad_recall_is_capped_hardest(self, queries):
        broad = next(q for q in queries if q.id == "broad-recall")
        others = [q.max_results for q in queries if q.tier == 1]
        assert broad.max_results < min(others)

    def test_negative_terms_only_on_broad_query(self, queries):
        for q in queries:
            if q.id == "broad-recall":
                assert q.negatives, "the broad net needs its noise guard"
            else:
                assert not q.negatives, f"{q.id} should not exclude terms — precision comes from AND"


class TestMatching:
    def test_from_is_a_hard_constraint(self, queries):
        acct = next(q for q in queries if q.id == "account-octonion")
        text = "a counterexample to a conjecture, proof in Lean"
        assert query_matches(acct, text, author="octonion")
        assert not query_matches(acct, text, author="someone_else")
        assert not query_matches(acct, text, author=None)

    def test_quoted_phrase_requires_the_phrase(self, queries):
        fv = [x for x in queries if x.family == "formal-verification"]
        assert any(query_matches(q, "the result was verified in Lean by GPT") for q in fv)
        assert not any(
            query_matches(q, "verified the lean startup methodology with AI") for q in fv
        )

    def test_whole_word_matching(self, queries):
        """'AI' must not match inside 'said' or 'certain'."""
        q = next(x for x in queries if x.id == "broad-recall")
        assert not query_matches(q, "he said the conjecture was certain to be plain")

    def test_negatives_suppress(self, queries):
        q = next(x for x in queries if x.id == "broad-recall")
        assert not query_matches(q, "AI conjecture about proof of work airdrop")


class TestCalibration:
    def test_full_recall_on_gold_set(self, queries):
        rep = calibrate(queries, GOLD)
        assert rep["recall"]["caught"] == rep["recall"]["total"], (
            f"blind spots: {rep['missedPositives']}"
        )

    def test_noise_stays_bounded(self, queries):
        rep = calibrate(queries, GOLD)
        # Some noise is intentional — recall first, the classifier filters later.
        # This is a ratchet: it must not get worse without a deliberate decision.
        assert rep["noise"]["rate"] <= 0.4, rep["falsePositiveDetail"]

    def test_dispute_signal_is_covered(self, queries):
        """The gap Sprint 1 shipped: only success claims were searched."""
        for pos in GOLD["positives"]:
            if "dispute" in pos["id"]:
                hits = which_queries_match(pos["text"], queries, pos.get("author"))
                assert hits, f"{pos['id']} is not discoverable"

    def test_verbatim_examples_are_caught(self, queries):
        """The two posts we have real captured text for must both be found."""
        for pos in GOLD["positives"]:
            if pos.get("verbatim"):
                hits = which_queries_match(pos["text"], queries, pos.get("author"))
                assert hits, f"real post {pos['id']} would be missed"

    def test_no_single_query_carries_everything(self, queries):
        """If one query caught every positive, the others are dead weight."""
        rep = calibrate(queries, GOLD)
        top = max(r["positives"] for r in rep["perQuery"])
        assert top < rep["recall"]["total"], "the set has collapsed to one query"


class TestTrustedAccounts:
    def test_only_probe_verified_accounts_are_enabled(self):
        tax = load_taxonomy()
        for acc in tax["trustedAccounts"]["accounts"]:
            if acc.get("enabled"):
                assert acc.get("verifiedOn"), (
                    f"@{acc['username']} is enabled without probe verification — "
                    "handles must never be enabled from memory"
                )

    def test_unverified_accounts_are_kept_but_disabled(self):
        tax = load_taxonomy()
        unverified = [a for a in tax["trustedAccounts"]["accounts"] if not a.get("verifiedOn")]
        assert unverified, "the record of what was considered should not be deleted"
        assert all(not a.get("enabled") for a in unverified)

    def test_no_account_query_is_a_bare_handle(self, queries):
        for q in queries:
            if q.id.startswith("account-"):
                assert "(" in q.query, f"{q.id} must combine from: with topic terms"


class TestGoldSet:
    def test_verbatim_entries_carry_a_source(self):
        for pos in GOLD["positives"]:
            if pos.get("verbatim"):
                assert pos.get("source", "").startswith("http"), (
                    f"{pos['id']} claims to be verbatim but cites no source"
                )

    def test_reconstructed_entries_are_labelled(self):
        """Reconstructions must never be mistakable for real quotations."""
        for pos in GOLD["positives"]:
            assert "verbatim" in pos, f"{pos['id']} does not declare whether it is real"

    def test_positives_reference_real_records(self):
        results = json.loads((ROOT / "data" / "results.json").read_text())
        ids = {r["id"] for r in results}
        for pos in GOLD["positives"]:
            ref = pos.get("relatedRecord")
            if ref:
                assert ref in ids, f"{pos['id']} references unknown record {ref}"
