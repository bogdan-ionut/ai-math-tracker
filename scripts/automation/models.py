"""Pydantic models for the automation layer.

These describe the *parallel* data layer only. Nothing here touches
`data/results.json`, whose schema lives in `scripts/schema.py` and stays the
curated source of truth.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

SourceType = Literal["twitter", "arxiv", "erdosproblems", "github", "manual"]

ProcessingStatus = Literal[
    "new",                 # ingested, nothing else done yet
    "extraction_pending",
    "extraction_failed",
    "extracted",
    "matched",
    "merged",
    "review",
    "irrelevant",
]


class RawTweet(BaseModel):
    """Minimal normalised record of one TwitterAPI.io result.

    Deliberately not the full API payload: we keep provenance and the fields
    needed for reprocessing, and a hash of the text so changes are detectable
    even when text storage is disabled. See ARCHITECTURE_ASSESSMENT.md §2.5.
    """

    model_config = {"extra": "forbid"}

    tweetId: str
    url: str
    authorHandle: Optional[str] = None
    authorName: Optional[str] = None
    createdAt: Optional[str] = None
    collectedAt: str
    matchedQueryId: str
    text: Optional[str] = None
    textSha256: Optional[str] = None
    links: list[str] = Field(default_factory=list)
    # engagement is stored for provenance only and MUST NOT influence
    # classification or be passed into any model prompt.
    engagement: dict[str, int] = Field(default_factory=dict)
    isRetweet: bool = False
    isQuote: bool = False
    referencedTweetId: Optional[str] = None
    conversationId: Optional[str] = None


class Observation(BaseModel):
    """A discovered source signal, independent of what it turns out to mean."""

    model_config = {"extra": "forbid"}

    id: str
    sourceType: SourceType
    sourceNativeId: str
    url: str
    author: Optional[str] = None
    sourceCreatedAt: Optional[str] = None
    collectedAt: str
    lastSeenAt: str
    matchedQueryIds: list[str] = Field(default_factory=list)
    text: Optional[str] = None
    textSha256: Optional[str] = None
    links: list[str] = Field(default_factory=list)
    externalIds: dict[str, list[str]] = Field(default_factory=dict)

    status: ProcessingStatus = "new"

    # Populated by later sprints.
    extraction: Optional[dict] = None
    extractionModel: Optional[str] = None
    extractionPromptVersion: Optional[str] = None
    extractionConfidence: Optional[float] = None
    extractionError: Optional[str] = None
    candidateId: Optional[str] = None
    problemRef: Optional[str] = None   # id in data/results.json, once matched

    def has_external_identifier(self) -> bool:
        """Whether anything here corroborates the claim beyond the post itself."""
        return any(v for v in (self.externalIds or {}).values())


class ProcessingState(BaseModel):
    """Machine-owned run state. This — not CURRENT_STATUS.md — is what the
    scheduled workflow writes (ARCHITECTURE_ASSESSMENT.md §2.7)."""

    model_config = {"extra": "forbid"}

    schemaVersion: int = 1
    lastRunAt: Optional[str] = None
    lastRunStatus: Optional[str] = None
    lastSuccessfulRunAt: Optional[str] = None
    cursorByQuery: dict[str, str] = Field(default_factory=dict)
    counters: dict[str, int] = Field(default_factory=dict)
    apiCalls: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    def bump(self, key: str, n: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + n

    def bump_api(self, key: str, n: int = 1) -> None:
        self.apiCalls[key] = self.apiCalls.get(key, 0) + n


def utc_now_iso() -> str:
    from datetime import timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
