"""K10 — the 512-character query limit, and the sharding that works around it.

TwitterAPI.io returns HTTP 200 with an empty tweet list for any query longer
than 512 characters. Measured exactly: a length sweep holding the term set
broad returned 20 results at every length through 512 and nothing from 513 on,
monotonically.

Six of fourteen queries were empty in production for weeks because of it. The
failure is indistinguishable from "nobody posted about this today", which is
why it survived two live runs and an external review, and why it needs a test
to stay found.

The first reading of the data was that the cap was on OR-term *count*; a live
run over 21 sharded queries falsified it — 34 terms returning results and 32
returning none — while length separated all 16 observations cleanly. So there
is a test below asserting that term count is not what we gate on: the wrong
model was plausible enough to ship once.

The sharding must also be lossless. Dropping terms until a query fits is the
same class of silent narrowing as the bug.
"""
from __future__ import annotations

import pytest

from scripts.automation.query_builder import (
    API_MAX_QUERY_CHARS,
    MAX_QUERY_CHARS,
    BuiltQuery,
    build_queries,
    count_or_terms,
    query_matches,
    split_for_length,
)


@pytest.fixture(scope="module")
def queries():
    return build_queries()


class TestTheLimitIsRespected:
    def test_no_shipped_query_can_hit_the_silent_zero(self, queries):
        over = [(q.id, len(q.query)) for q in queries if len(q.query) > MAX_QUERY_CHARS]
        assert not over, f"these will silently return nothing: {over}"

    def test_the_ship_cap_stays_under_the_measured_limit(self):
        assert MAX_QUERY_CHARS < API_MAX_QUERY_CHARS == 512, (
            "the cap we ship is a margin below a measured boundary"
        )

    def test_nothing_ships_that_could_not_be_made_to_fit(self, queries):
        assert not [q.id for q in queries if q.over_cap]

    def test_term_count_is_not_the_gate(self, queries):
        """The falsified model. A query may carry many terms if they are short;
        what matters is the assembled length. Asserting it keeps the wrong fix
        from quietly returning."""
        assert max(count_or_terms(q.query) for q in queries) > 20
        assert all(len(q.query) <= MAX_QUERY_CHARS for q in queries)


class TestShardingIsLossless:
    """`(A) AND (b1 OR b2)` ≡ `[(A) AND b1] OR [(A) AND b2]`."""

    def _long(self, n=60):
        terms = [f"term{i:03d}" for i in range(n)]
        return BuiltQuery(
            id="fam", family="fam", tier=1,
            query=f"(x OR y) ({' OR '.join(terms)}) lang:en",
            purpose="p", max_results=20, expected_precision="high",
            groups=[["x", "y"], terms],
        )

    def test_the_split_group_is_partitioned_not_truncated(self):
        shards = split_for_length(self._long())
        rebuilt = [t for s in shards for t in s.groups[1]]
        assert rebuilt == [f"term{i:03d}" for i in range(60)], (
            "terms were dropped or duplicated"
        )

    def test_untouched_groups_appear_in_every_shard(self):
        for s in split_for_length(self._long()):
            assert s.groups[0] == ["x", "y"]

    def test_every_shard_fits(self):
        for s in split_for_length(self._long()):
            assert len(s.query) <= MAX_QUERY_CHARS

    def test_packing_is_greedy_not_wasteful(self):
        """Chunks pack against real assembled length. Shards left well under the
        cap would mean more paid calls than the limit requires."""
        shards = split_for_length(self._long())
        assert len(shards) > 1
        for s in shards[:-1]:
            assert len(s.query) > MAX_QUERY_CHARS * 0.85

    def test_the_longest_group_is_the_one_split(self):
        big = [f"aaaaaaaa{i:03d}" for i in range(40)]
        bq = BuiltQuery(
            id="f", family="f", tier=1,
            query=f"({' OR '.join(big)}) (b0 OR b1 OR b2)",
            purpose="", max_results=20, expected_precision="high",
            groups=[big, ["b0", "b1", "b2"]],
        )
        for s in split_for_length(bq):
            assert s.groups[1] == ["b0", "b1", "b2"], "the short group was split instead"

    def test_a_query_already_under_the_cap_is_untouched(self, queries):
        small = next(q for q in queries if q.id == "arxiv-linked")
        assert split_for_length(small) == [small]
        assert small.shard_of is None and "#" not in small.id

    def test_operators_and_negatives_survive_on_every_shard(self):
        terms = [f"term{i:03d}" for i in range(60)]
        bq = BuiltQuery(
            id="f", family="f", tier=3,
            query=f"({' OR '.join(terms)}) lang:en -filter:retweets -airdrop",
            purpose="", max_results=20, expected_precision="low",
            groups=[terms], negatives=["airdrop"],
        )
        shards = split_for_length(bq)
        assert len(shards) > 1
        for s in shards:
            assert "lang:en" in s.query and "-filter:retweets" in s.query
            assert "-airdrop" in s.query and s.negatives == ["airdrop"]

    def test_a_term_too_long_to_fit_is_flagged_never_dropped(self):
        huge = "x" * (MAX_QUERY_CHARS + 50)
        bq = BuiltQuery(
            id="f", family="f", tier=1, query=f"({huge}) (b0)",
            purpose="", max_results=20, expected_precision="high",
            groups=[[huge], ["b0"]],
        )
        shards = split_for_length(bq)
        assert any(s.over_cap for s in shards), "an unfittable query must be flagged"
        assert all(huge in s.query for s in shards), "a term was dropped to fit"


class TestRecallIsPreserved:
    """Sharding changes how we ask, never what the query set finds."""

    TEXTS = [
        "GPT-5.6 proved a conjecture that was open for decades",
        "we verified in Lean a machine-generated proof of the theorem",
        "AlphaProof settled an open problem, preprint on arXiv",
        "this Erdős problem was resolved by an AI-assisted search",
        "the proof is wrong — Gemini's counterexample was already known",
    ]

    @pytest.mark.parametrize("text", TEXTS)
    def test_a_family_that_matched_whole_still_matches_sharded(self, text, queries):
        for fam in {q.family for q in queries}:
            shards = [q for q in queries if q.family == fam]
            if len(shards) == 1:
                continue
            whole = BuiltQuery(
                id=fam, family=fam, tier=shards[0].tier, query=shards[0].query,
                purpose="", max_results=20, expected_precision="high",
                negatives=shards[0].negatives,
                groups=[[t for s in shards for t in s.groups[i]]
                        for i in range(len(shards[0].groups))],
            )
            if query_matches(whole, text):
                assert any(query_matches(s, text) for s in shards), (
                    f"{fam} matched as one query but no shard does — recall lost"
                )

    def test_shard_ids_are_unique_and_keep_their_family(self, queries):
        assert len({q.id for q in queries}) == len(queries)
        for q in queries:
            assert q.shard_of in (None, q.family)
