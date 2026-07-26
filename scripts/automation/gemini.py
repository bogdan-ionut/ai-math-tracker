"""Gemini client for structured extraction and relationship judging.

Kept behind a `StructuredModel` protocol so the pipeline never depends on the
vendor, mirroring the Twitter client. The API key is read from the environment
and is never logged, never persisted, and never included in an exception message.

Requests are paced for the same reason the Twitter client is: a burst of calls
against a rate-limited endpoint fails intermittently, and intermittent failure is
worse than slow success because it silently drops observations.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Protocol

import httpx

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(RuntimeError):
    """API or transport failure. Never contains the API key."""


class SchemaViolation(GeminiError):
    """The model returned JSON that does not satisfy the requested schema."""


class StructuredModel(Protocol):
    """What the pipeline needs from a structured-output model."""

    def generate_json(self, prompt: str, schema: dict, *, temperature: float = 0.0) -> dict:
        ...


def _quota_reason(resp) -> str | None:
    """Pull the machine-readable quota id out of a 429, and nothing else.

    Gemini distinguishes a per-minute rate limit from an exhausted daily
    allowance, and the two need opposite responses: wait, versus stop. Only
    structured metadata is read — never the message body, which can echo the
    request content back into logs.
    """
    try:
        payload = resp.json()
    except Exception:
        return None
    for detail in (payload.get("error") or {}).get("details") or []:
        for violation in detail.get("violations") or []:
            qid = violation.get("quotaId") or violation.get("quotaMetric")
            if qid:
                return str(qid)
    return None


class GeminiClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "gemini-3.6-flash",
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff: float = 2.0,
        min_interval: float = 4.0,
        max_interval: float = 20.0,
        base_url: str = BASE_URL,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise GeminiError(
                "GEMINI_API_KEY is not set. In CI it comes from repository secrets; "
                "locally, export it only in your shell — never commit it."
            )
        self._key = key
        self.model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff = backoff
        self._min_interval = min_interval
        # Adaptive. The old client escalated its delay *within* one call's
        # retries and then reset to the floor for the next observation, so a
        # sustained rate limit produced a storm: 121 calls for 50 observations,
        # 32 of them failing on HTTP 429. TwitterAPI.io taught this exact lesson
        # in Sprint 1.5 — pace, do not merely retry — and it was never carried
        # over to this client.
        self._interval = min_interval
        self._max_interval = max_interval
        self.throttled_count = 0
        self.last_quota_reason: str | None = None
        self._last_call_at = 0.0
        self._base_url = base_url.rstrip("/")
        self.call_count = 0

    # -- internals ---------------------------------------------------------

    def _pace(self) -> None:
        if self._interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call_at
        if self._last_call_at and elapsed < self._interval:
            time.sleep(self._interval - elapsed)
        self._last_call_at = time.monotonic()

    def _throttled(self) -> None:
        """Slow down for *every subsequent call*, not just this one's retries."""
        self._interval = min(self._interval * 2, self._max_interval)
        self.throttled_count += 1

    def _went_through(self) -> None:
        """Ease back toward the floor, slowly enough not to re-trip the limit."""
        self._interval = max(self._min_interval, self._interval * 0.9)

    def _post(self, payload: dict) -> dict:
        url = f"{self._base_url}/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self._key, "Content-Type": "application/json"}
        last: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                self._pace()
                self.call_count += 1
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    self._went_through()
                    return resp.json()
                if resp.status_code in (402, 403):
                    raise GeminiError(
                        f"HTTP {resp.status_code} — Gemini quota or permission problem; "
                        "retrying will not help"
                    )
                if resp.status_code in (429, 500, 502, 503, 504):
                    if resp.status_code == 429:
                        self._throttled()
                        reason = _quota_reason(resp)
                        if reason:
                            self.last_quota_reason = reason
                        if reason and "PerDay" in reason:
                            # A daily quota does not recover by waiting a few
                            # seconds. Retrying is pure waste, and worse, it
                            # looks like a pacing problem for the rest of the
                            # run when it is nothing of the kind.
                            raise GeminiError(
                                f"HTTP 429 — daily quota exhausted ({reason}); "
                                "retrying will not help today"
                            )
                    last = GeminiError(
                        f"HTTP {resp.status_code} from generateContent"
                        + (f" ({self.last_quota_reason})" if resp.status_code == 429
                           and self.last_quota_reason else "")
                    )
                    if attempt < self._max_retries:
                        retry_after = resp.headers.get("retry-after")
                        if retry_after and retry_after.isdigit():
                            delay = float(retry_after)
                        elif resp.status_code == 429:
                            delay = max(self._backoff, self._interval) * (2 ** attempt)
                        else:
                            delay = self._backoff * attempt
                        time.sleep(min(delay, 30.0))
                        continue
                    raise last
                # 4xx: not retryable. Surface the status but never the body, which
                # can echo request content.
                raise GeminiError(f"HTTP {resp.status_code} from generateContent")
            except httpx.HTTPError as exc:
                last = GeminiError(f"transport error: {type(exc).__name__}")
                if attempt < self._max_retries:
                    time.sleep(self._backoff * attempt)
                    continue
                raise last from None
        raise last or GeminiError("unknown failure")

    # -- public ------------------------------------------------------------

    def generate_json(self, prompt: str, schema: dict, *, temperature: float = 0.0) -> dict:
        """Return parsed JSON constrained to ``schema``.

        Raises SchemaViolation if the model returns something that is not JSON —
        the caller must treat that as a failed extraction, never as an empty one.
        """
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": temperature,
            },
        }
        body = self._post(payload)

        try:
            candidates = body["candidates"]
            if not candidates:
                raise SchemaViolation("model returned no candidates")
            parts = candidates[0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise SchemaViolation(f"unexpected response envelope: {type(exc).__name__}") from None

        if not text.strip():
            raise SchemaViolation("model returned empty text")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SchemaViolation(f"model output is not valid JSON: {exc.msg}") from None
        if not isinstance(parsed, dict):
            raise SchemaViolation("model output is not a JSON object")
        return parsed

    def ping(self) -> dict:
        """Cheap liveness check for the smoke test. Returns counts only."""
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}, "model": {"type": "string"}},
            "required": ["ok"],
        }
        out = self.generate_json(
            'Reply with {"ok": true, "model": "<the model answering>"} and nothing else.',
            schema,
        )
        return {"reachable": True, "model": self.model, "returned": out,
                "apiCalls": self.call_count}


class StubModel:
    """Offline structured model for tests and dry runs. Never touches the network."""

    def __init__(self, responses: list[dict] | dict | None = None,
                 error: Exception | None = None) -> None:
        self._responses = responses if isinstance(responses, list) else ([responses] if responses else [])
        self._error = error
        self.call_count = 0
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, schema: dict, *, temperature: float = 0.0) -> dict:
        self.call_count += 1
        self.prompts.append(prompt)
        if self._error:
            raise self._error
        if not self._responses:
            return {}
        idx = min(self.call_count - 1, len(self._responses) - 1)
        return self._responses[idx]
