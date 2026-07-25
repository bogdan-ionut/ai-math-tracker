"""The extraction contract: what we ask Gemini for, and what we accept back.

Every field is optional. The model must never be forced to produce an identifier,
a date or an organisation it did not see — a forced field is an invitation to
invent one, and an invented arXiv id would sail straight through deterministic
matching and merge two unrelated problems.

Two layers of defence:
  1. Gemini is given a response schema, so output is JSON of the right shape.
  2. Pydantic validates it here, and `cross_check_identifiers` compares what the
     model *claimed* against what our own regexes can actually find in the text.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ClaimType = Literal[
    "new_result",            # a claim that something was solved/refuted
    "evidence",              # verification, formalization, independent confirmation
    "dispute",               # wrong, withdrawn, already known, rediscovery
    "publication",           # preprint/repo release
    "commentary",            # discussion, no claim
    "unrelated",
]

ResultKind = Literal[
    "proof", "counterexample", "refutation", "improved_bound",
    "formalization", "correction", "unknown",
]


class ExtractionResult(BaseModel):
    """Structured reading of one observation. Proposal only — never authoritative."""

    model_config = {"extra": "ignore"}   # tolerate extra keys rather than fail the run

    isRelevant: bool = False
    relevanceReason: Optional[str] = None

    canonicalProblemName: Optional[str] = None
    problemAliases: list[str] = Field(default_factory=list)
    problemFamily: Optional[str] = None
    mathematicalField: Optional[str] = None

    claimType: ClaimType = "unrelated"
    resultType: ResultKind = "unknown"

    claimingOrganization: Optional[str] = None
    claimingPeople: list[str] = Field(default_factory=list)
    modelName: Optional[str] = None
    claimedAt: Optional[str] = None

    externalIdentifiers: dict[str, list[str]] = Field(default_factory=dict)
    paperUrl: Optional[str] = None
    artifactUrl: Optional[str] = None
    leanArtifactUrl: Optional[str] = None
    sourceUrls: list[str] = Field(default_factory=list)

    evidenceAvailable: bool = False
    summary: Optional[str] = None
    extractionConfidence: float = 0.0
    uncertainties: list[str] = Field(default_factory=list)

    @field_validator("extractionConfidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator("problemAliases", "claimingPeople", "uncertainties", "sourceUrls",
                     mode="before")
    @classmethod
    def _listify(cls, v):  # noqa: ANN001
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return list(v)

    def is_actionable(self, min_confidence: float) -> bool:
        """Worth passing to matching at all."""
        return (
            self.isRelevant
            and self.claimType not in ("unrelated", "commentary")
            and self.extractionConfidence >= min_confidence
        )


# --------------------------------------------------------------------------
# Gemini response schema (OpenAPI subset — keep it simple, no $ref/anyOf)
# --------------------------------------------------------------------------

def gemini_response_schema() -> dict:
    s = {"type": "string"}
    strs = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "properties": {
            "isRelevant": {"type": "boolean"},
            "relevanceReason": s,
            "canonicalProblemName": s,
            "problemAliases": strs,
            "problemFamily": s,
            "mathematicalField": s,
            "claimType": {"type": "string",
                          "enum": ["new_result", "evidence", "dispute", "publication",
                                   "commentary", "unrelated"]},
            "resultType": {"type": "string",
                           "enum": ["proof", "counterexample", "refutation", "improved_bound",
                                    "formalization", "correction", "unknown"]},
            "claimingOrganization": s,
            "claimingPeople": strs,
            "modelName": s,
            "claimedAt": s,
            "externalIdentifiers": {
                "type": "object",
                "properties": {
                    "arxiv": strs, "doi": strs, "oeis": strs,
                    "erdos": strs, "github": strs, "lean": strs,
                },
            },
            "paperUrl": s,
            "artifactUrl": s,
            "leanArtifactUrl": s,
            "sourceUrls": strs,
            "evidenceAvailable": {"type": "boolean"},
            "summary": s,
            "extractionConfidence": {"type": "number"},
            "uncertainties": strs,
        },
        "required": ["isRelevant", "claimType", "resultType", "extractionConfidence"],
    }


# --------------------------------------------------------------------------
# Hallucination guard
# --------------------------------------------------------------------------

def cross_check_identifiers(
    extracted: ExtractionResult, text: str | None, links: list[str] | None
) -> tuple[dict[str, list[str]], list[str]]:
    """Keep only identifiers we can independently find in the source.

    The model is a *reader*, not a source of truth. Anything it reports that our
    own regexes cannot find in the text or links is discarded and recorded as a
    warning — an invented arXiv id or Erdős number would otherwise be treated as
    a hard deterministic match downstream and merge unrelated problems.
    """
    from scripts.automation.identifiers import extract_identifiers

    truth = extract_identifiers(text, links).to_dict()
    claimed = extracted.externalIdentifiers or {}

    kept: dict[str, list[str]] = {}
    warnings: list[str] = []

    for kind, values in claimed.items():
        if kind not in truth:
            warnings.append(f"model reported unknown identifier kind {kind!r}")
            continue
        real = list(truth.get(kind) or [])
        for v in values or []:
            norm = str(v).strip().lower().removeprefix("arxiv:").removeprefix("#")
            # Find OUR canonical form of whatever the model referred to. The model
            # may hand back a full URL where our regex produced a slug; keeping
            # both would make one identifier look like two and silently weaken
            # deterministic matching. Our form always wins.
            canonical = next(
                (r for r in real
                 if norm == r.lower() or norm in r.lower() or r.lower() in norm),
                None,
            )
            if canonical is not None:
                kept.setdefault(kind, []).append(canonical)
            else:
                warnings.append(f"discarded unverifiable {kind} identifier {v!r}")

    # anything our regexes found but the model missed is still ours to keep
    for kind, values in truth.items():
        if values:
            merged = set(kept.get(kind, [])) | set(values)
            kept[kind] = sorted(merged)

    return {k: sorted(set(v)) for k, v in kept.items() if v}, warnings
