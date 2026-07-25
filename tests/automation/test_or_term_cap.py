"""K10 — the OR-term cap, and the sharding that works around it.

TwitterAPI.io returns HTTP 200 and an empty result list once a query carries 37
or more OR-terms. Measured: every total from 10 to 36 returned 20 results and
37 returned none, monotonically, and the same 37 split evenly across two groups
fails identically — so the cap is on the query total, not on any one group.
That rule reproduces all 14 production queries, `named-systems` at exactly 37
included.

Six of fourteen queries were empty in production for weeks because of it. The
failure is indistinguishable from "nobody posted about this today", which is
why it needed a witness experiment to find and why it needs a test to stay
found.

The sharding must also be *lossless*. Dropping terms until a query fits would
be the same class of silent narrowing as the bug.
"""
from __future__ import annotations

import pytest

from scripts.automation.query_builder import (
    MAX_OR_TERMS,
    BuiltQuery,
    build_queries,
    count_or_terms,
    load_taxonomy,
    query_matches,
    split_for_term_cap,
)

MEASURED_CEILING = 36   # 36 returns results, 37 returns none


@pytest.fixture(scope="module")
def queries():
    return build_queries()


class TestTheCapIsRespected:
    def test_no_shipped_query_can_hit_the_silent_zero(self, queries):
        over = [(q.id, count_or_terms(q.query)) for q in queries
                if count_or_terms(q.query) > MAX_OR_TERMS]
        assert not over, f"these will silently return nothing: {over}"

    def test_the_configured_cap_stays_under_the_measured_ceiling(self):
        assert MAX_OR_TERMS < MEASURED_CEILING, (
            "the cap is a margin below a measured boundary, not the boundary"
        )

    def test_nothing_ships_that_could_not_be_made_to_fit(self, queries):
        assert not [q.id for q in queries if q.over_cap]

    def test_counting_ignores_operators_and_negatives(self):
        q = '(a OR b) (c OR d) lang:en -filter:retweets -airdrop'
        assert count_or_terms(q) == 4


class TestShardingIsLossless:
    """`(A) AND (b1 OR b2)` ≡ `[(A) AND b1] OR [(A) AND b2]`."""

    def _big(self):
        return BuiltQuery(
            id="fam", family="fam", tier=1,
            query="(x OR y) (" + " OR ".join(f"t{i}" for i in range(40)) + ") lang:en",
            purpose="p", max_results=20, expected_precision="high",
            groups=[["x", "y"], [f"t{i}" for i in range(40)]],
        )

    def test_the_split_group_is_partitioned_not_truncated(self):
        shards = split_for_term_cap(self._big())
        rebuilt = [t for s in shards for t in s.groups[1]]
        assert rebuilt == [f"t{i}" for i in range(40)], "terms were dropped or duplicated"

    def test_untouched_groups_appear_in_every_shard(self):
        for s in split_for_term_cap(self._big()):
            assert s.groups[0] == ["x", "y"]

    def test_every_shard_fits(self):
        for s in split_for_term_cap(self._big()):
            assert count_or_terms(s.query) <= MAX_OR_TERMS

    def test_the_largest_group_is_the_one_split(self):
        bq = BuiltQuery(
            id="f", family="f", tier=1,
            query="(" + " OR ".join(f"a{i}" for i in range(30)) + ") (b0 OR b1 OR b2)",
            purpose="", max_results=20, expected_precision="high",
            groups=[[f"a{i}" for i in range(30)], ["b0", "b1", "b2"]],
        )
        for s in split_for_term_cap(bq, cap=20):
            assert s.groups[1] == ["b0", "b1", "b2"], "the small group was split instead"

    def test_a_query_already_under_the_cap_is_untouched(self, queries):
        small = next(q for q in queries if q.id == "arxiv-linked")
        assert split_for_term_cap(small) == [small]
        assert small.shard_of is None

    def test_operators_and_negatives_survive_on_every_shard(self):
        bq = BuiltQuery(
            id="f", family="f", tier=3,
            query="(" + " OR ".join(f"a{i}" for i in range(40)) + ") "
                  "lang:en -filter:retweets -airdrop",
            purpose="", max_results=20, expected_precision="low",
            groups=[[f"a{i}" for i in range(40)]], negatives=["airdrop"],
        )
        shards = split_for_term_cap(bq)
        assert len(shards) > 1
        for s in shards:
            assert "lang:en" in s.query and "-filter:retweets" in s.query
            assert "-airdrop" in s.query and s.negatives == ["airdrop"]

    def test_an_infeasible_split_is_flagged_never_truncated(self):
        """Two groups that cannot both fit must fail loudly, not lose terms."""
        bq = BuiltQuery(
            id="f", family="f", tier=1,
            query="(" + " OR ".join(f"a{i}" for i in range(30)) + ") "
                  "(" + " OR ".join(f"b{i}" for i in range(30)) + ")",
            purpose="", max_results=20, expected_precision="high",
            groups=[[f"a{i}" for i in range(30)], [f"b{i}" for i in range(30)]],
        )
        shards = split_for_term_cap(bq, cap=10)
        assert len(shards) == 1 and shards[0].over_cap is True
        assert count_or_terms(shards[0].query) == 60, "no term may be dropped"


class TestRecallIsPreserved:
    """Sharding must not change *what the query set finds*, only how it asks."""

    TEXTS = [
        "GPT-5.6 proved a conjecture that was open for decades",
        "we verified in Lean a machine-generated proof of the theorem",
        "AlphaProof settled an open problem, preprint on arXiv",
        "this Erdős problem was resolved by an AI-assisted search",
        "the proof is wrong — Gemini's counterexample was already known",
    ]

    @pytest.mark.parametrize("text", TEXTS)
    def test_every_family_that_matched_whole_still_matches_sharded(self, text, queries):
        """Rebuild each family unsharded and require a shard to agree."""
        tax = load_taxonomy()
        for fam in {q.family for q in queries}:
            shards = [q for q in queries if q.family == fam]
            if len(shards) == 1:
                continue
            whole = BuiltQuery(
                id=fam, family=fam, tier=shards[0].tier,
                query=shards[0].query, purpose="", max_results=20,
                expected_precision="high", negatives=shards[0].negatives,
                groups=[sorted({t for s in shards for t in s.groups[i]},
                               key=str)
                        for i in range(len(shards[0].groups))],
            )
            if query_matches(whole, text):
                assert any(query_matches(s, text) for s in shards), (
                    f"{fam} matched as one query but no shard does — recall lost"
                )
        assert tax  # taxonomy loaded

    def test_shard_ids_are_unique_and_keep_their_family(self, queries):
        assert len({q.id for q in queries}) == len(queries)
        for q in queries:
            assert q.shard_of in (None, q.family)
