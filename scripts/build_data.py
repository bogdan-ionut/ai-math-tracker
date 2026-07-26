"""Validate the curated dataset and emit the static JSON the app reads.

Flow:  data/results.json  ->  Pydantic validation + dedup + metrics
       ->  public/data/conjectures.json
       ->  public/data/summary.json
       ->  public/data/metadata.json  (+ schema.json)

Run:   python scripts/build_data.py
The GitHub Actions deploy workflow runs this before `vite build`.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import ValidationError, TypeAdapter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import MathematicalResult, Summary  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "results.json"
OUT = ROOT / "public" / "data"

LAB_ORDER = ["oa", "dm", "cg", "ax", "an", "xa", "pk"]

# Rough family -> a canonical model-family label, for the "distinct systems" count.
MODEL_FAMILY_KEYS = [
    "GPT-5.2", "GPT-5.4", "GPT-5.5", "GPT-5.6 Pro", "GPT-5.6 Sol", "GPT-5.6",
    "internal", "Codex", "Aristotle", "Aletheia", "AlphaProof", "AxiomProver",
    "Fable", "MathDyad", "Devin", "Grok",
]


def die(msg: str) -> None:
    print(f"\033[31mERROR\033[0m {msg}", file=sys.stderr)
    sys.exit(1)


def load() -> list[MathematicalResult]:
    if not SRC.exists():
        die(f"missing {SRC}")
    raw = json.loads(SRC.read_text())
    adapter = TypeAdapter(list[MathematicalResult])
    try:
        records = adapter.validate_python(raw)
    except ValidationError as exc:
        die(f"schema validation failed:\n{exc}")
    return records  # type: ignore[return-value]


def check_invariants(records: list[MathematicalResult]) -> None:
    seen: dict[str, str] = {}
    for r in records:
        if r.id in seen:
            die(f"duplicate id '{r.id}'")
        seen[r.id] = r.title
    # Every audited result must have at least one source OR an artifact.
    missing = [
        r.id
        for r in records
        if r.status == "audited"
        and not r.sources
        and not r.paper_url
        and not r.lean_artifact_url
        and not r.artifact_url
    ]
    if missing:
        # Warn, don't fail: sourcing is being backfilled. Keep it visible.
        print(
            f"\033[33mWARN\033[0m {len(missing)} audited results lack a source URL: "
            f"{', '.join(missing[:8])}{'…' if len(missing) > 8 else ''}"
        )


def model_families(records: list[MathematicalResult]) -> int:
    fams: set[str] = set()
    for r in records:
        for key in MODEL_FAMILY_KEYS:
            if key.lower() in r.model.lower():
                fams.add(key)
    return len(fams)


def source_coverage(records: list[MathematicalResult]) -> dict:
    """How much of the registry actually points at anything.

    Reported per status, and in *records* rather than problems, because a batch
    of 44 problems carries one source URL or none — counting it as 44 sourced
    problems would restate the very overstatement this figure exists to expose.
    """
    out: dict[str, dict[str, int]] = {}
    for r in records:
        bucket = out.setdefault(r.status, {"withSource": 0, "withoutSource": 0})
        bucket["withSource" if r.sources else "withoutSource"] += 1
    totals = {
        "recordsWithSource": sum(1 for r in records if r.sources),
        "recordsWithoutSource": sum(1 for r in records if not r.sources),
        "byStatus": out,
    }
    totals["auditedWithoutSource"] = out.get("audited", {}).get("withoutSource", 0)
    totals["auditedTotal"] = sum(out.get("audited", {}).values())
    return totals


def audit_dating(records: list[MathematicalResult]) -> dict:
    """Whether `auditedAt` is telling us anything `claimedAt` did not.

    The split between the two is described throughout this project as what keeps
    it honest — an announcement is not a confirmation. If every audit is dated
    the day of the claim, that sentence is decoration, and the site should be
    the first to say so rather than the last.
    """
    audited = [r for r in records if r.status == "audited"]
    same = [r for r in audited if r.audited_at and r.audited_at == r.claimed_at]
    lagged = [r for r in audited if r.audited_at and r.audited_at != r.claimed_at]
    return {
        "auditedRecords": len(audited),
        "sameDayAsClaim": len(same),
        "laterThanClaim": len(lagged),
        "missingAuditDate": sum(1 for r in audited if not r.audited_at),
        # The one number that decides whether the methodology text is true.
        "splitIsInformative": bool(lagged),
    }


def build_summary(records: list[MathematicalResult]) -> Summary:
    # Disputed results are recorded but never counted in the headline total.
    total = sum(r.count for r in records if r.status != "disputed")
    by_status: dict[str, int] = defaultdict(int)
    by_lab: dict[str, int] = defaultdict(int)
    by_lab_aud: dict[str, int] = defaultdict(int)
    by_day: dict[date, int] = defaultdict(int)
    erdos: set[str] = set()

    for r in records:
        by_status[r.status] += r.count
        by_lab[r.lab_key] += r.count
        if r.status == "audited":
            by_lab_aud[r.lab_key] += r.count
        if not (r.status == "disputed"):
            by_day[r.claimed_at] += r.count
        # distinct Erdős problems (incl. the unit-distance #90) + batch members
        if r.family == "Erdős":
            if r.members:
                for m in r.members:
                    erdos.add(m)
            elif r.erdos_number:
                erdos.add(r.erdos_number)
        if "Unit-distance" in r.description:
            erdos.add("#90")

    largest_day_date = max(by_day, key=lambda d: by_day[d])
    dates = [r.claimed_at for r in records]

    by_impact: dict[str, int] = defaultdict(int)
    for r in records:
        if r.impact is not None:
            by_impact[str(r.impact)] += 1
    landmarks = [r.id for r in records if r.impact == 5]

    return Summary(
        generatedAt=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        rangeStart=min(dates),
        rangeEnd=max(dates),
        total=total,
        byStatus=dict(by_status),
        byLab={k: by_lab.get(k, 0) for k in LAB_ORDER},
        byLabAudited={k: by_lab_aud.get(k, 0) for k in LAB_ORDER},
        erdosCount=len(erdos),
        largestDay={"date": largest_day_date.isoformat(), "count": by_day[largest_day_date]},
        oldestYearsOpen=max((r.years_open or 0) for r in records),
        modelFamilies=model_families(records),
        assessed=sum(1 for r in records if r.impact is not None),
        byImpact=dict(by_impact),
        landmarks=landmarks,
        source_coverage=source_coverage(records),
        audit_dating=audit_dating(records),
    )


# --------------------------------------------------------------------------
# Sprint 7 — automated signals, kept strictly apart from the tracker
# --------------------------------------------------------------------------

CANDIDATES = ROOT / "data" / "automation" / "candidates.json"

# What a signal is allowed to say on the site. An allowlist rather than a
# blocklist: a field added to the candidate model later must be chosen for
# publication deliberately, not inherited by default.
SIGNAL_FIELDS = (
    "id", "canonicalName", "family", "externalIds", "sources",
    "firstSeenAt", "lastSeenAt", "problemRef",
)

# Tiers, mirroring scripts/automation/policy.py. Duplicated on purpose: this
# script must not import the automation package, so that nothing in the build
# path can reach code that writes stores.
EVIDENCE_TIERS = {"published": ("doi", "arxiv"),
                  "registered": ("erdos", "oeis"),
                  "referenced": ("github", "lean")}


def _tier(external: dict) -> str:
    for tier, kinds in EVIDENCE_TIERS.items():
        if any(external.get(k) for k in kinds):
            return tier
    return "none"


def build_signals() -> list[dict]:
    """Publish pending candidates as *signals* — never as results.

    These are unverified reports that automation grouped. They are emitted to a
    separate file, counted in no metric, and rendered in a separate section, so
    that nothing the pipeline proposes can ever be mistaken for something the
    tracker stands behind. A candidate becomes a result only through the draft
    pull request that `scripts/automation/curate.py promote` opens.
    """
    if not CANDIDATES.exists():
        return []
    try:
        rows = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []

    signals = []
    for c in rows:
        if not isinstance(c, dict) or c.get("status", "pending") != "pending":
            continue
        out = {k: c.get(k) for k in SIGNAL_FIELDS}
        claims = [x for x in (c.get("claims") or []) if isinstance(x, dict)]
        first = claims[0] if claims else {}
        out["claimCount"] = len(claims)
        out["observationCount"] = len(c.get("observationIds") or [])
        out["modelName"] = first.get("modelName")
        out["organization"] = first.get("organization")
        out["resultType"] = first.get("resultType")
        out["claimedAt"] = first.get("claimedAt")
        out["evidenceTier"] = _tier(c.get("externalIds") or {})
        # Deliberately absent: summary text, impact, assessment, confidence.
        # The first is model-written prose about someone else's post; the rest
        # are editorial judgements that no automated record is entitled to.
        signals.append(out)
    signals.sort(key=lambda s: (s.get("lastSeenAt") or "", s["id"]), reverse=True)
    return signals


def main() -> None:
    records = load()
    check_invariants(records)
    records.sort(key=lambda r: (r.claimed_at, r.id))

    OUT.mkdir(parents=True, exist_ok=True)
    conj = [r.to_public() for r in records]
    (OUT / "conjectures.json").write_text(json.dumps(conj, indent=2, ensure_ascii=False))

    summary = build_summary(records)
    (OUT / "summary.json").write_text(
        json.dumps(summary.model_dump(by_alias=True, mode="json"), indent=2, ensure_ascii=False)
    )

    (OUT / "metadata.json").write_text(
        json.dumps(
            {
                "generatedAt": summary.generated_at,
                "records": len(records),
                "total": summary.total,
                "schemaVersion": 1,
            },
            indent=2,
        )
    )

    signals = build_signals()
    (OUT / "signals.json").write_text(
        json.dumps(
            {
                "generatedAt": summary.generated_at,
                "count": len(signals),
                "disclaimer": (
                    "Unverified automated signals. These are not tracker results: "
                    "nothing here has been audited, assessed, or counted in any "
                    "figure on this site."
                ),
                "signals": signals,
            },
            indent=2, ensure_ascii=False,
        )
    )

    (OUT / "schema.json").write_text(
        json.dumps(MathematicalResult.model_json_schema(by_alias=True), indent=2)
    )

    print(
        f"\033[32mOK\033[0m {len(records)} records -> {summary.total} problems "
        f"({summary.by_status}) | Erdős {summary.erdos_count} | "
        f"{summary.model_families} model families | {len(signals)} unverified signals"
    )


if __name__ == "__main__":
    main()
