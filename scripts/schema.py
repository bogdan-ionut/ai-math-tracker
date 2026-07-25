"""Canonical data schema for the AI-Math tracker.

This is the single source of truth for what a result record looks like.
Both the Python pipeline (validation) and the frontend (via the emitted
JSON Schema) are held to it. Edit here, run `build_data.py`, and the app
picks up the change.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

ResultType = Literal[
    "proof",
    "refutation",
    "counterexample",
    "improved-bound",
    "formalization",
    "correction",
]

Status = Literal["audited", "reported", "provisional", "disputed"]

# 5 = reshapes a field · 4 = redirects real research · 3 = genuine, specialist
# 2 = narrow/technical · 1 = valid but adds little (rediscovery, correction)
IMPACT_LABELS = {
    5: "Field-shaping",
    4: "Redirects research",
    3: "Genuine advance",
    2: "Narrow / specialist",
    1: "Marginal",
}

LabKey = Literal["oa", "dm", "cg", "ax", "an", "xa", "pk"]


class MathematicalResult(BaseModel):
    """One distinct open problem solved, refuted, or advanced with AI help.

    A single record may stand for a *batch* (count > 1, e.g. the 44 OEIS
    conjectures or the 26-problem "Star Fleet" run); ``members`` lists the
    individual problems when their identities are known.
    """

    model_config = {"extra": "forbid"}

    id: str = Field(min_length=2)
    title: str = Field(min_length=2)
    family: str
    description: str

    result_type: ResultType = Field(alias="resultType")
    status: Status

    # The split that keeps the tracker honest: an announcement is not a
    # confirmation. `audited_at` is only set once there is a paper, a Lean
    # artifact, or expert confirmation.
    claimed_at: date = Field(alias="claimedAt")
    audited_at: Optional[date] = Field(default=None, alias="auditedAt")

    lab: str
    lab_key: LabKey = Field(alias="labKey")
    model: str
    human_collaborators: Optional[list[str]] = Field(
        default=None, alias="humanCollaborators"
    )

    count: int = Field(default=1, ge=1)
    members: Optional[list[str]] = None

    is_open_problem: bool = Field(default=True, alias="isOpenProblem")
    years_open: Optional[int] = Field(default=None, alias="yearsOpen", ge=0)
    erdos_number: Optional[str] = Field(default=None, alias="erdosNumber")

    # Additive matching aids, derived by scripts/backfill_identifiers.py from
    # fields already present. Never written by the automation pipeline.
    aliases: list[str] = Field(default_factory=list)
    external_ids: dict[str, list[str]] = Field(default_factory=dict, alias="externalIds")

    sources: list[HttpUrl] = Field(default_factory=list)
    paper_url: Optional[HttpUrl] = Field(default=None, alias="paperUrl")
    artifact_url: Optional[HttpUrl] = Field(default=None, alias="artifactUrl")
    lean_artifact_url: Optional[HttpUrl] = Field(default=None, alias="leanArtifactUrl")

    confidence: float = Field(ge=0.0, le=1.0)
    audit_notes: Optional[str] = Field(default=None, alias="auditNotes")
    superseded_by: Optional[str] = Field(default=None, alias="supersededBy")

    # --- Impact assessment -------------------------------------------------
    # Deliberately nullable: a result is only scored once someone has actually
    # judged it. An unscored result renders as "not yet assessed" rather than
    # being silently treated as low-impact.
    impact: Optional[int] = Field(default=None, ge=1, le=5)
    assessment: Optional[str] = None
    resolution: Optional[str] = None  # human-facing label: "Proof" / "Counterexample"
    resolution_note: Optional[str] = Field(default=None, alias="resolutionNote")
    provenance_note: Optional[str] = Field(default=None, alias="provenanceNote")

    @field_validator("members")
    @classmethod
    def _members_match_count(cls, v, info):  # noqa: ANN001
        return v

    @model_validator(mode="after")
    def _consistency(self) -> "MathematicalResult":
        # Invariant 1: an audited result must carry the proof of audit.
        if self.status == "audited" and self.audited_at is None:
            raise ValueError(f"{self.id}: audited result has no auditedAt date")
        # Invariant 2: if members are listed, they should account for the count.
        if self.members is not None and len(self.members) != self.count:
            raise ValueError(
                f"{self.id}: {len(self.members)} members but count={self.count}"
            )
        # Invariant 3: a disputed result should say why.
        if self.status == "disputed" and not (self.audit_notes or self.superseded_by):
            raise ValueError(f"{self.id}: disputed result needs auditNotes/supersededBy")
        # Invariant 4: a score without a justification is just a number.
        if self.impact is not None and not self.assessment:
            raise ValueError(f"{self.id}: impact score requires an assessment")
        return self

    def to_public(self) -> dict:
        """camelCase dict for the frontend."""
        return self.model_dump(by_alias=True, mode="json", exclude_none=False)


class Summary(BaseModel):
    """Precomputed roll-ups the dashboard reads instead of recomputing."""

    generated_at: str = Field(alias="generatedAt")
    range_start: date = Field(alias="rangeStart")
    range_end: date = Field(alias="rangeEnd")
    total: int
    by_status: dict[str, int] = Field(alias="byStatus")
    by_lab: dict[str, int] = Field(alias="byLab")
    by_lab_audited: dict[str, int] = Field(alias="byLabAudited")
    erdos_count: int = Field(alias="erdosCount")
    largest_day: dict = Field(alias="largestDay")
    oldest_years_open: int = Field(alias="oldestYearsOpen")
    model_families: int = Field(alias="modelFamilies")
    assessed: int
    by_impact: dict[str, int] = Field(alias="byImpact")
    landmarks: list[str]  # ids of the impact-5 results

    model_config = {"populate_by_name": True}
