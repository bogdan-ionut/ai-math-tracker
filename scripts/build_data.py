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
    )


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

    (OUT / "schema.json").write_text(
        json.dumps(MathematicalResult.model_json_schema(by_alias=True), indent=2)
    )

    print(
        f"\033[32mOK\033[0m {len(records)} records -> {summary.total} problems "
        f"({summary.by_status}) | Erdős {summary.erdos_count} | "
        f"{summary.model_families} model families"
    )


if __name__ == "__main__":
    main()
