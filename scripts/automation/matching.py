"""Entity resolution: decide which curated problem an observation is about.

Order matters, and it is strict:

    1. deterministic identifier match  → certain, judge is NEVER called
    2. alias match                     → certain, judge is NEVER called
    3. lexical similarity              → shortlist only
    4. conflicting identifiers         → hard stop, never merged
    5. nothing plausible               → distinct / insufficient information

The judge (an LLM) only ever sees case 3. That is the whole point: a model is
allowed to disambiguate, never to override an identifier. A shortlist is capped
so the judge prompt stays small and cheap.

No embeddings — 40 curated records (ARCHITECTURE_ASSESSMENT §2.4).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from rapidfuzz import fuzz

from scripts.automation.identifiers import ExternalIds, normalize_title

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "data" / "results.json"

Decision = Literal[
    "same_source_duplicate",
    "same_problem_same_claim",
    "same_problem_new_claim",
    "same_problem_conflicting_claim",
    "related_problem",
    "distinct_problem",
    "insufficient_information",
]

MatchMethod = Literal["identifier", "alias", "lexical", "none", "conflict"]

# A lexical score this high is treated as a shortlist entry, not a match.
LEXICAL_FLOOR = 72
# Above this, and clearly ahead of the runner-up, we accept without the judge.
LEXICAL_CERTAIN = 92
LEXICAL_MARGIN = 12


@dataclass
class Candidate:
    """One possible existing problem an observation might be about."""

    record_id: str
    title: str
    score: float
    method: MatchMethod
    reason: str

    def to_dict(self) -> dict:
        return {"recordId": self.record_id, "title": self.title,
                "score": round(self.score, 1), "method": self.method, "reason": self.reason}


@dataclass
class MatchOutcome:
    """What matching concluded, and whether the judge is needed."""

    method: MatchMethod
    matched_id: Optional[str] = None
    shortlist: list[Candidate] = field(default_factory=list)
    needs_judge: bool = False
    conflict: bool = False
    conflicting_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # R5. Whether `matched_id` names a curated record or an existing candidate.
    # Matching only ever searched the registry, so the second post about a
    # genuinely *new* problem could not see the candidate the first one created
    # — it was reported as `distinct_problem` and the two never converged. The
    # distinction matters downstream: matching a curated record links to
    # published work, matching a candidate merely groups two rumours.
    matched_kind: str = "registry"

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "matchedProblemId": self.matched_id,
            "shortlist": [c.to_dict() for c in self.shortlist],
            "needsJudge": self.needs_judge,
            "conflict": self.conflict,
            "conflictingIds": self.conflicting_ids,
            "notes": self.notes,
        }


def load_registry(path: Path | None = None) -> list[dict]:
    return json.loads((path or RESULTS).read_text(encoding="utf-8"))


def _ids_of(rec: dict) -> ExternalIds:
    raw = rec.get("externalIds") or {}
    return ExternalIds(
        arxiv=list(raw.get("arxiv") or []),
        doi=list(raw.get("doi") or []),
        oeis=list(raw.get("oeis") or []),
        erdos=list(raw.get("erdos") or []),
        github=list(raw.get("github") or []),
        lean=list(raw.get("lean") or []),
    )


def _obs_ids(obs: dict) -> ExternalIds:
    raw = obs.get("externalIds") or {}
    return ExternalIds(
        arxiv=list(raw.get("arxiv") or []),
        doi=list(raw.get("doi") or []),
        oeis=list(raw.get("oeis") or []),
        erdos=list(raw.get("erdos") or []),
        github=list(raw.get("github") or []),
        lean=list(raw.get("lean") or []),
    )


def _candidate_names(obs: dict) -> list[str]:
    """Names the observation offers for the problem it is about."""
    ex = obs.get("extraction") or {}
    names = [ex.get("canonicalProblemName")] + list(ex.get("problemAliases") or [])
    return [n for n in names if n]


def _as_records(candidates: list[dict]) -> list[dict]:
    """Present candidates in the shape the matcher already understands.

    Deliberately reusing the registry path rather than writing a second matcher:
    a candidate that matched by one set of rules and a record that matched by
    another would be a source of exactly the inconsistencies this stage exists
    to prevent.
    """
    return [
        {
            "id": c["id"],
            "title": c.get("canonicalName") or c["id"],
            "aliases": list(c.get("aliases") or []),
            "externalIds": dict(c.get("externalIds") or {}),
        }
        for c in candidates
    ]


def match_observation(
    obs: dict, registry: list[dict] | None = None, shortlist_size: int = 5,
    candidates: list[dict] | None = None,
) -> MatchOutcome:
    """Match against the curated registry first, then the candidate store.

    Registry first and unconditionally: a curated record is stronger evidence
    than a proposal we made ourselves, so a candidate must never win over one.
    The candidate store is only consulted when the registry had nothing to say.
    """
    registry = registry if registry is not None else load_registry()

    if candidates:
        primary = _match_against(obs, registry, shortlist_size)
        if primary.method != "none" or primary.conflict:
            return primary
        secondary = _match_against(obs, _as_records(candidates), shortlist_size)
        if secondary.method == "none":
            # Keep the registry's notes: they explain what was searched.
            return primary
        secondary.matched_kind = "candidate"
        secondary.notes = secondary.notes + [
            "matched an existing candidate, not a curated record — this groups "
            "two unverified reports, it does not confirm either"
        ]
        return secondary

    return _match_against(obs, registry, shortlist_size)


def _match_against(
    obs: dict, registry: list[dict], shortlist_size: int = 5
) -> MatchOutcome:
    obs_ids = _obs_ids(obs)
    notes: list[str] = []

    # --- 1. deterministic identifiers -------------------------------------
    id_hits: list[Candidate] = []
    conflicts: set[str] = set()
    for rec in registry:
        rec_ids = _ids_of(rec)
        if obs_ids.overlaps(rec_ids):
            shared = [
                f"{k}:{v}"
                for k, vs in obs_ids.to_dict().items()
                for v in vs
                if v in (rec_ids.to_dict().get(k) or [])
            ]
            id_hits.append(Candidate(rec["id"], rec["title"], 100.0, "identifier",
                                     f"shares {', '.join(shared)}"))
        elif obs_ids.conflicts_with(rec_ids):
            # Hard stop for this record. An explicit identifier disagreement
            # (Erdős #999 vs #728) must never be overridden by a name
            # resemblance, so the record is removed from every later phase —
            # not merely noted.
            conflicts.add(rec["id"])

    if len(id_hits) == 1:
        return MatchOutcome("identifier", id_hits[0].record_id, id_hits[0:1],
                            needs_judge=False, conflicting_ids=sorted(conflicts),
                            notes=[f"deterministic identifier match: {id_hits[0].reason}"])
    if len(id_hits) > 1:
        # Two records claiming the same identifier is a data problem, not a
        # question for a model.
        return MatchOutcome("conflict", None, id_hits[:shortlist_size],
                            needs_judge=False, conflict=True,
                            notes=["identifier matches more than one curated record — "
                                   "the registry needs fixing, not a judgement"])

    # --- 2. alias ----------------------------------------------------------
    names = _candidate_names(obs)
    norm_names = {normalize_title(n) for n in names if normalize_title(n)}
    alias_hits: list[Candidate] = []
    for rec in registry:
        if rec["id"] in conflicts:
            continue
        rec_norms = {normalize_title(a) for a in (rec.get("aliases") or [])}
        rec_norms.add(normalize_title(rec.get("title") or ""))
        overlap = norm_names & {r for r in rec_norms if r}
        if overlap:
            alias_hits.append(Candidate(rec["id"], rec["title"], 99.0, "alias",
                                        f"alias match on {sorted(overlap)[0]!r}"))

    if len(alias_hits) == 1:
        return MatchOutcome("alias", alias_hits[0].record_id, alias_hits[0:1],
                            needs_judge=False, conflicting_ids=sorted(conflicts),
                            notes=[alias_hits[0].reason])

    # --- 3. lexical shortlist ---------------------------------------------
    scored: list[Candidate] = []
    for rec in registry:
        if rec["id"] in conflicts:
            continue
        best = 0.0
        why = ""
        targets = [rec.get("title") or ""] + list(rec.get("aliases") or [])
        for name in names:
            for t in targets:
                s = fuzz.token_set_ratio(normalize_title(name), normalize_title(t))
                if s > best:
                    best, why = s, f"{name!r} ≈ {t!r}"
        if best >= LEXICAL_FLOOR:
            scored.append(Candidate(rec["id"], rec["title"], best, "lexical", why))

    scored.sort(key=lambda c: -c.score)
    shortlist = (alias_hits + scored)[:shortlist_size]

    if conflicts:
        notes.append(f"{len(conflicts)} record(s) carry a conflicting identifier and were "
                     "excluded from matching entirely")

    if not shortlist:
        return MatchOutcome("none", None, [], needs_judge=False, notes=notes or
                            ["no identifier, alias or lexical candidate"])

    # A single, clearly-ahead, very strong lexical hit does not need a model.
    if (len(scored) >= 1 and scored[0].score >= LEXICAL_CERTAIN and not alias_hits
            and (len(scored) == 1 or scored[0].score - scored[1].score >= LEXICAL_MARGIN)):
        return MatchOutcome("lexical", scored[0].record_id, shortlist, needs_judge=False,
                            conflicting_ids=sorted(conflicts),
                            notes=notes + [f"unambiguous lexical match ({scored[0].score:.0f})"])

    return MatchOutcome("lexical", None, shortlist, needs_judge=True,
                        conflicting_ids=sorted(conflicts), notes=notes)


def build_judge_payload(obs: dict, outcome: MatchOutcome, registry: list[dict]) -> dict:
    """Exactly what the judge is allowed to see. Small, and no engagement data."""
    by_id = {r["id"]: r for r in registry}
    ex = obs.get("extraction") or {}
    return {
        "observation": {
            "id": obs.get("id"),
            "url": obs.get("url"),
            "author": obs.get("author"),
            "postedAt": obs.get("sourceCreatedAt"),
            "text": obs.get("text"),
            "claimType": ex.get("claimType"),
            "resultType": ex.get("resultType"),
            "problemName": ex.get("canonicalProblemName"),
            "aliases": ex.get("problemAliases"),
            "modelName": ex.get("modelName"),
            "organization": ex.get("claimingOrganization"),
            "externalIdentifiers": obs.get("externalIds") or {},
        },
        "candidates": [
            {
                "id": c.record_id,
                "title": by_id.get(c.record_id, {}).get("title"),
                "description": by_id.get(c.record_id, {}).get("description"),
                "family": by_id.get(c.record_id, {}).get("family"),
                "status": by_id.get(c.record_id, {}).get("status"),
                "model": by_id.get(c.record_id, {}).get("model"),
                "claimedAt": by_id.get(c.record_id, {}).get("claimedAt"),
                "externalIdentifiers": by_id.get(c.record_id, {}).get("externalIds") or {},
                "matchMethod": c.method,
                "matchScore": round(c.score, 1),
            }
            for c in outcome.shortlist
        ],
    }


def judge_response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": list(Decision.__args__)},
            "matchedProblemId": {"type": "string"},
            "confidence": {"type": "number"},
            "reasons": {"type": "array", "items": {"type": "string"}},
            "conflictingFields": {"type": "array", "items": {"type": "string"}},
            "requiresHumanReview": {"type": "boolean"},
        },
        "required": ["decision", "confidence", "requiresHumanReview"],
    }
