"""Gemini pacing — the defect the first real end-to-end run exposed.

The first plan run against real APIs failed **32 of 50 extractions**, every one
of them HTTP 429, and spent 121 calls doing it. The client escalated its delay
*within* a single call's retries and then reset to the floor for the next
observation, so a sustained rate limit produced a storm rather than a slowdown.

TwitterAPI.io taught exactly this lesson in Sprint 1.5 — pace, do not merely
retry — and it had never been carried across to this client. These tests are
that lesson, written down where it applies.
"""
from __future__ import annotations

import pytest

from scripts.automation.gemini import GeminiClient


@pytest.fixture
def client():
    return GeminiClient(api_key="test-key-not-real", min_interval=1.0, max_interval=16.0)


class TestThrottlingPersistsAcrossCalls:
    def test_a_429_slows_down_the_next_call_too(self, client):
        before = client._interval
        client._throttled()
        assert client._interval > before, (
            "the whole defect: the delay reset for the next observation"
        )

    def test_repeated_throttling_backs_off_further(self, client):
        seen = []
        for _ in range(4):
            client._throttled()
            seen.append(client._interval)
        assert seen == sorted(seen) and seen[0] < seen[-1]

    def test_the_interval_is_bounded(self, client):
        for _ in range(50):
            client._throttled()
        assert client._interval == 16.0, "an unbounded interval would stall the run"

    def test_success_eases_back_off(self, client):
        client._throttled()
        raised = client._interval
        for _ in range(10):
            client._went_through()
        assert client._interval < raised

    def test_it_never_eases_below_the_configured_floor(self, client):
        for _ in range(200):
            client._went_through()
        assert client._interval == 1.0

    def test_recovery_is_gradual_not_instant(self, client):
        """Snapping straight back to the floor would re-trip the limit at once."""
        client._throttled()
        raised = client._interval
        client._went_through()
        assert client._interval > raised * 0.5

    def test_throttling_is_counted_for_telemetry(self, client):
        client._throttled()
        client._throttled()
        assert client.throttled_count == 2


class TestDefaults:
    def test_the_default_floor_is_not_the_old_one_second(self):
        """One second is 60 requests a minute — well above the limit we hit."""
        c = GeminiClient(api_key="test-key-not-real")
        assert c._min_interval >= 4.0

    def test_pacing_can_still_be_disabled_for_tests(self):
        c = GeminiClient(api_key="test-key-not-real", min_interval=0)
        c._pace()          # must not sleep or raise
        assert c._interval == 0


class TestQuotaIsNotRateLimiting:
    """A per-minute limit and an exhausted daily allowance both return 429 and
    need opposite responses: wait, versus stop. The third plan run burned its
    whole 720s budget waiting out something that waiting could not fix."""

    class Resp:
        def __init__(self, payload, status=429):
            self._payload, self.status_code, self.headers = payload, status, {}

        def json(self):
            return self._payload

    def _violation(self, quota_id):
        return {"error": {"details": [{"violations": [{"quotaId": quota_id}]}]}}

    def test_the_quota_id_is_extracted(self):
        from scripts.automation.gemini import _quota_reason
        resp = self.Resp(self._violation("GenerateRequestsPerDayPerProject"))
        assert _quota_reason(resp) == "GenerateRequestsPerDayPerProject"

    def test_a_body_without_violations_yields_nothing(self):
        from scripts.automation.gemini import _quota_reason
        assert _quota_reason(self.Resp({"error": {"message": "slow down"}})) is None

    def test_an_unparseable_body_is_not_fatal(self):
        from scripts.automation.gemini import _quota_reason

        class Bad:
            def json(self):
                raise ValueError("not json")
        assert _quota_reason(Bad()) is None

    def test_only_structured_metadata_is_read(self):
        """The message body can echo request content; it must never be logged."""
        from scripts.automation.gemini import _quota_reason
        payload = self._violation("GenerateRequestsPerMinute")
        payload["error"]["message"] = "SECRET PROMPT TEXT"
        assert "SECRET" not in str(_quota_reason(self.Resp(payload)))
