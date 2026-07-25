"""One-off/idempotent merge of impact assessments into data/results.json.

Impact is scored 1-5 with a written assessment. Only results that have actually
been judged get a score; everything else stays `impact: null` and renders as
"not yet assessed" rather than being silently treated as low-impact.

Run: python scripts/merge_impact.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "results.json"

# match -> (impact, resolution, assessment)
# `match` is a regex tested against id + title + description.
ASSESSMENTS: list[tuple[str, int, str, str]] = [
    (
        r"cycle double cover",
        5,
        "Proof",
        "Resolves a central, decades-old structural graph-theory conjecture connecting "
        "cycles and flows. Very recent, so long-run influence still depends on community uptake.",
    ),
    (
        r"unit-distance",
        5,
        "Counterexample",
        "Overturns an approximately 80-year-old central belief in discrete geometry and "
        "creates an unexpected bridge to algebraic number theory. Independent work has "
        "already strengthened it.",
    ),
    (
        r"jacobian",
        5,
        "Counterexample",
        "An explicit Keller map refutes the conjecture in every dimension at least three. "
        "This fundamentally changes a problem dating to 1939, although dimension two remains open.",
    ),
    (
        r"erdos-1196",
        4,
        "Proof",
        "Resolves a 1968 primitive-set conjecture with a sharp asymptotic bound; checked, "
        "extended, and formalized in Lean.",
    ),
    (
        r"dinitz",
        4,
        "Counterexample",
        "Removes a prominent conjectured rounding guarantee in combinatorial optimization "
        "and unsplittable-flow theory. Likely to redirect algorithm design.",
    ),
    (
        r"erdos-1051",
        3,
        "Proof",
        "Settles a longstanding irrationality question for rapidly growing sequences and "
        "led to formalization and generalization.",
    ),
    (
        r"erdos-728",
        3,
        "Proof",
        "Resolves the intended nontrivial factorial-divisibility problem after clarifying "
        "an ambiguous formulation. Important but specialized.",
    ),
    (
        r"anderson",
        3,
        "Counterexample",
        "A genuine result in commutative algebra. Its roughly 19,000-line formalization may "
        "be at least as influential methodologically as the theorem itself.",
    ),
    (
        r"erdos-652",
        2,
        "Proof",
        "Correctly closes the listed problem, but the final argument is essentially an "
        "application of an existing incidence theorem rather than a new theorem.",
    ),
    (
        r"graffiti.*284",
        2,
        "Counterexample",
        "An elegant exact use of the Hoffman-Singleton graph, but the target inequality is narrow.",
    ),
    (
        r"graffiti-conjecture-39$|graffiti.*\b39\b",
        2,
        "Proof",
        "A clean distance-variance and spectral-interlacing theorem with formal verification; "
        "mainly specialist graph theory.",
    ),
    (
        r"graffiti-conjecture-40$|graffiti.*\b40\b",
        2,
        "Proof",
        "The negative-spectrum companion to Conjecture 39. Useful, but largely the same "
        "mechanism and audience.",
    ),
    (
        r"brandt",
        2,
        "Counterexample",
        "Exact and interesting, but only refutes the weak boundary formulation; Brandt's "
        "stronger strict theorem survives.",
    ),
    (
        r"written-on-the-wall|wowii",
        2,
        "Counterexample",
        "Closes a 2004 generated graph conjecture with a small, exact witness. Mathematically "
        "sound but unlikely to reshape the field.",
    ),
    (
        r"graffiti.*154",
        1,
        "Counterexample",
        "The result is valid, but the recorded run rediscovered a witness published one month "
        "earlier, sharply limiting new impact.",
    ),
    (
        r"roll",
        1,
        "Counterexample",
        "The example is standard and predates the claim; no credible provenance for the alleged "
        "open conjecture was found. This is a correction, not a new solution.",
    ),
]


def main() -> None:
    rows = json.loads(SRC.read_text())
    hits = 0
    for r in rows:
        hay = f"{r['id']} {r['title']} {r['description']}".lower()
        for pattern, impact, resolution, assessment in ASSESSMENTS:
            if re.search(pattern, hay):
                r["impact"] = impact
                r["resolution"] = resolution
                r["assessment"] = assessment
                hits += 1
                break
        else:
            r.setdefault("impact", None)
            r.setdefault("assessment", None)
            r.setdefault(
                "resolution",
                "Counterexample"
                if r["resultType"] in ("counterexample", "refutation")
                else "Proof",
            )
        r.setdefault("provenanceNote", None)

    SRC.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    unscored = sum(1 for r in rows if r.get("impact") is None)
    print(f"scored {hits} records; {unscored} left unassessed", file=sys.stderr)


if __name__ == "__main__":
    main()
