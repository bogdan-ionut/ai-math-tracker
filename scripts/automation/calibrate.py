"""Offline calibration of the query set against a gold set.

Answers, without spending a single API call: *would today's queries have found
the events we already know about, and how much obvious noise would they let in?*

    python -m scripts.automation.calibrate

Recall here is recall **against the gold set**, not against Twitter. Perfect
recall cannot be demonstrated from search alone; this measures whether the
taxonomy covers the wordings we have actually seen, which is the part we can
control. Blind spots are reported explicitly rather than hidden behind a score.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.query_builder import (  # noqa: E402
    BuiltQuery,
    build_queries,
    query_matches,
)

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "tests" / "automation" / "fixtures" / "gold_set.json"


def calibrate(queries: list[BuiltQuery] | None = None, gold: dict | None = None) -> dict:
    queries = queries or build_queries()
    gold = gold or json.loads(GOLD.read_text(encoding="utf-8"))

    positives, negatives = gold["positives"], gold["negatives"]

    caught: list[dict] = []
    missed: list[dict] = []
    for pos in positives:
        hits = [q.id for q in queries if query_matches(q, pos["text"], pos.get("author"))]
        (caught if hits else missed).append({**pos, "matchedBy": hits})

    false_pos: list[dict] = []
    clean: list[dict] = []
    for neg in negatives:
        hits = [q.id for q in queries if query_matches(q, neg["text"], neg.get("author"))]
        (false_pos if hits else clean).append({**neg, "matchedBy": hits})

    # per-query contribution
    per_query = []
    for q in queries:
        p = sum(1 for x in positives if query_matches(q, x["text"], x.get("author")))
        n = sum(1 for x in negatives if query_matches(q, x["text"], x.get("author")))
        uniq = sum(
            1 for x in caught
            if x["matchedBy"] == [q.id]
        )
        per_query.append({
            "id": q.id, "tier": q.tier, "positives": p, "negatives": n,
            "uniqueCatches": uniq,
            "precisionProxy": round(p / (p + n), 2) if (p + n) else None,
        })

    return {
        "queries": len(queries),
        "recall": {
            "caught": len(caught), "total": len(positives),
            "rate": round(len(caught) / len(positives), 3) if positives else None,
        },
        "noise": {
            "falsePositives": len(false_pos), "totalNegatives": len(negatives),
            "rate": round(len(false_pos) / len(negatives), 3) if negatives else None,
        },
        "missedPositives": [{"id": m["id"], "signalType": m.get("signalType")} for m in missed],
        "falsePositiveDetail": [{"id": f["id"], "matchedBy": f["matchedBy"]} for f in false_pos],
        "perQuery": sorted(per_query, key=lambda r: (-r["positives"], r["id"])),
        "deadQueries": [r["id"] for r in per_query if r["positives"] == 0],
    }


def main() -> int:
    rep = calibrate()

    print("═══ QUERY CALIBRATION ═══════════════════════════════════════")
    print(f"queries built     : {rep['queries']}")
    r, n = rep["recall"], rep["noise"]
    print(f"gold-set recall   : {r['caught']}/{r['total']}  ({r['rate']:.0%})")
    print(f"false positives   : {n['falsePositives']}/{n['totalNegatives']}  ({n['rate']:.0%})")
    print()

    print("per-query contribution (positives / negatives / unique):")
    for q in rep["perQuery"]:
        prec = f"{q['precisionProxy']:.2f}" if q["precisionProxy"] is not None else "  – "
        flag = "  ← catches nothing" if q["positives"] == 0 else ""
        star = "  ★ sole catcher" if q["uniqueCatches"] else ""
        print(f"  t{q['tier']} {q['id']:<26} {q['positives']:>2} / {q['negatives']:>2}"
              f"  prec≈{prec}{star}{flag}")
    print()

    if rep["missedPositives"]:
        print("MISSED — blind spots to fix:")
        for m in rep["missedPositives"]:
            print(f"  · {m['id']}  ({m['signalType']})")
    else:
        print("No gold-set positive was missed.")
    print()

    if rep["falsePositiveDetail"]:
        print("FALSE POSITIVES — noise the classifier will have to reject:")
        for f in rep["falsePositiveDetail"]:
            print(f"  · {f['id']}  via {', '.join(f['matchedBy'])}")
    print("═════════════════════════════════════════════════════════════")

    Path("calibration_report.json").write_text(
        json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
