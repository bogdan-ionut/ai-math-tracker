"""TwitterAPI.io client.

Kept behind a small interface (`SearchClient`) so the rest of the pipeline never
depends on this vendor. TwitterAPI.io is a third-party scraper of X, not the
official API — availability and terms are a live risk, and swapping it out
should not touch anything downstream (ARCHITECTURE_ASSESSMENT.md §2.11).

The API key is read from the environment and is never logged, never written to
disk, and never included in an exception message.
"""
from __future__ import annotations

import os
import time
from typing import Iterable, Protocol

import httpx

BASE_URL = "https://api.twitterapi.io"
SEARCH_PATH = "/twitter/tweet/advanced_search"


class SearchClient(Protocol):
    """What the pipeline needs from a source. Implemented by the real client and
    by the fixture client used in tests."""

    def search(self, query: str, query_type: str = "Latest", max_pages: int = 1) -> list[dict]:
        ...


class TwitterApiError(RuntimeError):
    """Network or API-level failure. Never contains the API key."""


class TwitterApiClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
        backoff: float = 2.0,
        min_interval: float = 1.2,
        base_url: str = BASE_URL,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("TWITTERAPI_IO_KEY", "")
        if not key:
            raise TwitterApiError(
                "TWITTERAPI_IO_KEY is not set. In CI it comes from repository secrets; "
                "locally, export it only in your shell — never commit it."
            )
        self._key = key
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff = backoff
        self._base_url = base_url.rstrip("/")
        # TwitterAPI.io rate-limits aggressively: a burst of back-to-back calls
        # returns 429 on alternating requests (measured 2026-07-25, probe run
        # 30155008096 — 37 rapid calls, ~40% rejected). Retrying alone is not
        # enough; requests must be *paced*.
        self._min_interval = min_interval
        self._last_call_at = 0.0
        self.call_count = 0

    def _pace(self) -> None:
        """Block until at least ``min_interval`` has passed since the last call."""
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call_at
        if self._last_call_at and elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_at = time.monotonic()

    # -- internals ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._key, "Accept": "application/json"}

    def _get(self, params: dict[str, str]) -> dict:
        """One GET with retry/backoff. Raises TwitterApiError with no secret in it."""
        url = f"{self._base_url}{SEARCH_PATH}"
        last: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                self._pace()
                self.call_count += 1
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.get(url, params=params, headers=self._headers())
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 402:
                    # Out of credit. Retrying cannot help and burns the retry
                    # budget on every remaining query in the run.
                    raise TwitterApiError(
                        "HTTP 402 — TwitterAPI.io account is out of credit; "
                        "top up at twitterapi.io before the next run"
                    )
                if resp.status_code in (429, 500, 502, 503, 504):
                    # transient — back off and retry
                    last = TwitterApiError(f"HTTP {resp.status_code} from search endpoint")
                    if attempt < self._max_retries:
                        retry_after = resp.headers.get("retry-after")
                        if retry_after and retry_after.isdigit():
                            delay = float(retry_after)
                        elif resp.status_code == 429:
                            delay = max(self._backoff, self._min_interval) * (2 ** attempt)
                        else:
                            delay = self._backoff * attempt
                        time.sleep(min(delay, 30.0))
                        continue
                    raise last
                # 4xx other than rate-limit: not retryable
                raise TwitterApiError(f"HTTP {resp.status_code} from search endpoint")
            except httpx.HTTPError as exc:
                last = TwitterApiError(f"transport error: {type(exc).__name__}")
                if attempt < self._max_retries:
                    time.sleep(self._backoff * attempt)
                    continue
                raise last from None
        raise last or TwitterApiError("unknown failure")

    # -- public ------------------------------------------------------------

    def search(self, query: str, query_type: str = "Latest", max_pages: int = 1) -> list[dict]:
        """Return raw tweet dicts for ``query``, following at most ``max_pages``."""
        tweets: list[dict] = []
        cursor = ""
        for _ in range(max(1, max_pages)):
            params = {"query": query, "queryType": query_type}
            if cursor:
                params["cursor"] = cursor
            payload = self._get(params)
            page = payload.get("tweets") or []
            tweets.extend(t for t in page if isinstance(t, dict))
            if not payload.get("has_next_page"):
                break
            cursor = payload.get("next_cursor") or ""
            if not cursor:
                break
        return tweets

    def ping(self) -> dict:
        """Cheap connectivity check used by the smoke test.

        Returns only non-sensitive counts — never the payload, never the key.
        """
        tweets = self.search("AlphaProof", query_type="Latest", max_pages=1)
        sample = tweets[0] if tweets else {}
        return {
            "ok": True,
            "tweetsReturned": len(tweets),
            "apiCalls": self.call_count,
            "sampleHasId": bool(sample.get("id")),
            "sampleFields": sorted(sample.keys())[:12],
        }


class FixtureSearchClient:
    """Offline client used by tests and `--dry-run`. Never touches the network."""

    def __init__(self, tweets_by_query: dict[str, list[dict]] | None = None,
                 default: Iterable[dict] | None = None) -> None:
        self._by_query = tweets_by_query or {}
        self._default = list(default or [])
        self.call_count = 0

    def search(self, query: str, query_type: str = "Latest", max_pages: int = 1) -> list[dict]:
        self.call_count += 1
        return list(self._by_query.get(query, self._default))
