"""Find the effective maximum query length for TwitterAPI.io.

The endpoint does not reject a long query — it accepts it and returns zero
results. That failure mode is silent, which is why it survived a syntax probe
that only checked for errors. This bisects a *real* query, progressively
dropping OR-terms, to find where results start coming back.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.twitter import TwitterApiClient, TwitterApiError  # noqa: E402

AI = ['AI', 'LLM', '"language model"', '"reasoning model"', '"AI-assisted"',
      '"AI-generated"', '"machine-generated"', '"computer-assisted"', 'AlphaProof',
      'AlphaGeometry', 'Aletheia', 'Aristotle', '"Deep Think"', 'Gemini', 'GPT',
      'Claude', 'Grok', 'Codex', 'Devin', 'AxiomProver', 'Fable', 'MathDyad']
OBJ = ['conjecture', '"open problem"', '"unsolved problem"', 'theorem', 'lemma',
       'counterexample', '"upper bound"', '"lower bound"', 'classification']


def build(n_ai: int, n_obj: int) -> str:
    a = "(" + " OR ".join(AI[:n_ai]) + ")"
    o = "(" + " OR ".join(OBJ[:n_obj]) + ")"
    return f"{a} {o} lang:en -filter:retweets"


def main() -> int:
    client = TwitterApiClient(timeout=25, max_retries=3, min_interval=2.0)
    rows = []
    print(f"{'chars':>6} {'ai':>3} {'obj':>4} {'returned':>9}")
    for n_ai, n_obj in ((22, 9), (18, 9), (14, 9), (12, 8), (10, 7),
                        (8, 6), (6, 5), (4, 4), (3, 3), (2, 2)):
        q = build(n_ai, n_obj)
        try:
            got = len(client.search(q, max_pages=1))
        except TwitterApiError as exc:
            print(f"{len(q):>6} {n_ai:>3} {n_obj:>4}   ERROR {exc}")
            rows.append({"chars": len(q), "returned": -1})
            continue
        print(f"{len(q):>6} {n_ai:>3} {n_obj:>4} {got:>9}")
        rows.append({"chars": len(q), "aiTerms": n_ai, "objTerms": n_obj, "returned": got})

    working = [r for r in rows if r.get("returned", 0) > 0]
    empty = [r for r in rows if r.get("returned") == 0]
    print()
    if working and empty:
        print(f"longest query returning results : {max(r['chars'] for r in working)} chars")
        print(f"shortest returning nothing      : {min(r['chars'] for r in empty)} chars")
    Path("length_probe.json").write_text(json.dumps(rows, indent=2))
    print(f"api calls: {client.call_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
