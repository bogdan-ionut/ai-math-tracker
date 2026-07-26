"""R2 and R11 — asking for the right window, and sharing the cap honestly.

**R2.** The lookback was applied only after the API had already chosen its 20
newest all-time matches. A query with more than 20 matches over all time could
therefore return 20 stale tweets and contribute nothing, while newer matching
posts existed and were never requested. The window now goes to the server.

The date form is deliberately not used. It is not ignored — it is applied
*wrongly*: a probe asking for 2026-07-19…07-21 returned twenty tweets all dated
07-22. The unix form was exact on the same check.

**R11.** `deduped[:cap]` took the first N in query order, which is not a cap but
a standing preference for whichever families are built first. On a busy day the
last families never got in, and the only trace was a count. Selection is now
round-robin and the surplus is carried to the next run instead of dropped.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.automation.ingest import _combine_with_backlog, select_fairly
from scripts.automation.models import RawTweet
from scripts.automation.query_builder import (
    API_MAX_QUERY_CHARS,
    BUILD_CHAR_BUDGET,
    MAX_QUERY_CHARS,
    TIME_WINDOW_CHARS,
    build_queries,
    with_time_window,
)

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def rec(query_id: str, n: int) -> RawTweet:
    return RawTweet(
        tweetId=f"{query_id}-{n}", url=f"https://x.com/a/status/{query_id}{n}",
        collectedAt="2026-07-25T12:00:00+00:00", matchedQueryId=query_id,
        textSha256="0" * 64,
    )


# ============================================================== R2

class TestTheWindowGoesToTheServer:
    def test_the_window_is_expressed_in_unix_seconds(self):
        q = with_time_window("(a OR b)", NOW - timedelta(hours=30), NOW)
        assert f"since_time:{int((NOW - timedelta(hours=30)).timestamp())}" in q
        assert f"until_time:{int(NOW.timestamp())}" in q

    def test_the_date_form_is_never_used(self):
        """It returned tweets outside the window it was given."""
        q = with_time_window("(a OR b)", NOW - timedelta(hours=30), NOW)
        assert "since:" not in q.replace("since_time:", "")
        assert "until:" not in q.replace("until_time:", "")

    def test_a_thirty_hour_lookback_is_expressed_exactly(self):
        """Day precision would over-fetch by up to 24 hours."""
        start = NOW - timedelta(hours=30)
        q = with_time_window("(a)", start, NOW)
        span = int(NOW.timestamp()) - int(start.timestamp())
        assert span == 30 * 3600
        assert str(span) not in q  # sanity: we send bounds, not a duration

    def test_the_original_query_is_left_intact(self):
        base = '(a OR "two words") lang:en -filter:retweets'
        assert with_time_window(base, NOW - timedelta(hours=1), NOW).startswith(base)


class TestTheWindowFitsInsideTheCharacterLimit:
    """The window is appended after sharding, so its cost must be reserved."""

    def test_the_build_budget_reserves_room_for_the_window(self):
        assert BUILD_CHAR_BUDGET == MAX_QUERY_CHARS - TIME_WINDOW_CHARS
        assert TIME_WINDOW_CHARS >= 44, "measured cost of the two operators"

    def test_no_query_exceeds_the_limit_once_windowed(self):
        """The regression that would silently re-empty the query set."""
        over = []
        for q in build_queries():
            full = with_time_window(q.query, NOW - timedelta(hours=30), NOW)
            if len(full) > API_MAX_QUERY_CHARS:
                over.append((q.id, len(full)))
        assert not over, f"these would return nothing: {over}"

    def test_windowed_queries_still_clear_the_ship_cap(self):
        for q in build_queries():
            full = with_time_window(q.query, NOW - timedelta(hours=30), NOW)
            assert len(full) <= MAX_QUERY_CHARS


# ============================================================== R11

class TestTheCapIsSharedFairly:
    def test_every_query_gets_in_before_any_query_gets_seconds(self):
        records = [rec(q, i) for q in ("a", "b", "c") for i in range(10)]
        taken, _ = select_fairly(records, 3)
        assert {r.matchedQueryId for r in taken} == {"a", "b", "c"}

    def test_a_late_query_is_not_starved_by_an_early_one(self):
        """The exact failure: query order decided who was dropped."""
        records = [rec("first", i) for i in range(40)] + [rec("last", i) for i in range(40)]
        taken, _ = select_fairly(records, 10)
        counts = {q: sum(1 for r in taken if r.matchedQueryId == q)
                  for q in ("first", "last")}
        assert counts == {"first": 5, "last": 5}

    def test_the_cap_is_still_a_cap(self):
        records = [rec(q, i) for q in ("a", "b") for i in range(50)]
        taken, deferred = select_fairly(records, 7)
        assert len(taken) == 7
        assert len(taken) + len(deferred) == len(records)

    def test_newest_first_survives_a_partial_take(self):
        """Order within a query is preserved, so a partial take keeps the head."""
        records = [rec("a", i) for i in range(10)]
        taken, _ = select_fairly(records, 3)
        assert [r.tweetId for r in taken] == ["a-0", "a-1", "a-2"]

    def test_a_query_with_less_than_its_share_does_not_waste_it(self):
        """One record from `small` must not cost `big` four slots."""
        records = [rec("small", 0)] + [rec("big", i) for i in range(20)]
        taken, _ = select_fairly(records, 10)
        assert len(taken) == 10
        assert sum(1 for r in taken if r.matchedQueryId == "big") == 9

    def test_nothing_is_dropped_only_deferred(self):
        records = [rec(q, i) for q in ("a", "b", "c") for i in range(9)]
        taken, deferred = select_fairly(records, 5)
        assert {r.tweetId for r in taken} | {r.tweetId for r in deferred} == {
            r.tweetId for r in records
        }
        assert not ({r.tweetId for r in taken} & {r.tweetId for r in deferred})

    @pytest.mark.parametrize("cap", [0, 1, 5, 100])
    def test_it_never_returns_more_than_the_cap(self, cap):
        records = [rec(q, i) for q in ("a", "b", "c") for i in range(9)]
        taken, deferred = select_fairly(records, cap)
        assert len(taken) <= cap
        assert len(taken) + len(deferred) == 27

    def test_an_empty_run_is_not_an_error(self):
        assert select_fairly([], 10) == ([], [])


class TestTheBacklogDrains:
    """A backlog that grows faster than it drains is a leak, not a feature."""

    def test_the_refetched_copy_is_not_carried_twice(self):
        """The lookback window overlaps deliberately, so almost everything in
        the backlog arrives again on the next run."""
        carried = [rec("a", 0), rec("a", 1)]
        fresh = [rec("a", 0), rec("a", 1), rec("a", 2)]
        pending, used = _combine_with_backlog(carried, fresh, existing=[])
        assert [r.tweetId for r in pending] == ["a-0", "a-1", "a-2"]
        assert used == 2

    def test_already_processed_records_are_dropped(self):
        """What the backlog exists to achieve — once it becomes an observation,
        it must leave."""
        carried = [rec("a", 0), rec("a", 1)]
        existing = [{"sourceNativeId": "a-0"}]
        pending, _ = _combine_with_backlog(carried, [], existing)
        assert [r.tweetId for r in pending] == ["a-1"]

    def test_the_backlog_goes_first(self):
        """Otherwise the oldest waiting records starve behind every fresh run."""
        pending, _ = _combine_with_backlog([rec("z", 9)], [rec("a", 0)], existing=[])
        assert pending[0].tweetId == "z-9"

    def test_consumed_counts_only_what_was_actually_carried(self):
        _, used = _combine_with_backlog([], [rec("a", 0)], existing=[])
        assert used == 0

    def test_a_fully_processed_backlog_empties(self):
        carried = [rec("a", i) for i in range(3)]
        existing = [{"sourceNativeId": f"a-{i}"} for i in range(3)]
        pending, used = _combine_with_backlog(carried, [], existing)
        assert pending == [] and used == 0


class TestTheTierCapIsReachable:
    """Pages hold 20; tier 1 asks for 40. One page could never satisfy it."""

    def test_pages_are_requested_to_cover_the_tier_cap(self):
        from math import ceil

        from scripts.automation.ingest import PAGE_SIZE
        for q in build_queries():
            pages = max(1, ceil(q.max_results / PAGE_SIZE))
            assert pages * PAGE_SIZE >= q.max_results, (
                f"{q.id} caps at {q.max_results} but only {pages} page(s) are fetched"
            )

    def test_a_tier_one_query_needs_more_than_one_page(self):
        tier1 = [q for q in build_queries() if q.tier == 1]
        assert tier1 and max(q.max_results for q in tier1) > 20, (
            "if this stops being true the pagination above is dead weight"
        )
