"""K10, part two — the cap is on characters, not OR-terms.

The differential probe established that TwitterAPI.io silently returns nothing
for some queries, and I read the boundary as an OR-term count because that is
the variable I had been walking. A live run over 21 sharded queries then gave
16 labelled observations, and they falsify it: a 34-term query returns 20
results and a 32-term one returns none. Character length separates all 16 with
no overlap — 481 works, 515 does not — and my own earlier walk agrees (505
works, 526 does not). Term count and length moved together in that walk, which
is how the confound survived.

So this probe varies length while holding the terms fixed, by padding one group
with junk alternatives. Padding can only broaden a disjunction, so any drop to
zero is the limit and not a change in what matches.

505 works and 515 does not, and 512 is a suspiciously round number for a
backend limit. This checks each length in between.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.twitter import TwitterApiClient, TwitterApiError  # noqa: E402

OUT = Path("charlimit_probe.json")

# Broad enough that the window is never genuinely empty at any length.
BASE_TERMS = ["AI", "LLM", '"language model"']
SECOND = ["theorem", "conjecture", '"open problem"', "counterexample"]
TAIL = "lang:en -filter:retweets"


def build(target_chars: int) -> str | None:
    """A query of exactly `target_chars`, padded with junk OR-alternatives.

    Whole tokens step the length by 9, which is far too coarse to find an exact
    boundary, so the last token absorbs the remainder by growing one character
    at a time.
    """
    for n in range(1, 80):
        pad = [f"zq{i:03d}" for i in range(n)]
        for extra in range(0, 15):
            candidate = pad[:-1] + [pad[-1] + "z" * extra]
            q = _assemble(candidate)
            if len(q) == target_chars:
                return q
            if len(q) > target_chars:
                break
    return None


def _assemble(pad: list[str]) -> str:
    a = "(" + " OR ".join(BASE_TERMS + pad) + ")"
    b = "(" + " OR ".join(SECOND) + ")"
    return f"{a} {b} {TAIL}"


def main() -> int:
    client = TwitterApiClient(timeout=25, max_retries=3, min_interval=2.0)
    rows: list[dict] = []

    print(f"{'chars':>6} {'returned':>9}   (terms held broad; padding only lengthens)\n")
    for target in range(496, 536):
        q = build(target)
        if q is None:
            continue                       # padding cannot hit this length exactly
        try:
            got = len(client.search(q, max_pages=1))
        except TwitterApiError as exc:
            print(f"{target:>6}     ERROR {exc}")
            continue
        flag = "  ←" if got == 0 else ""
        print(f"{target:>6} {got:>9}{flag}", flush=True)
        rows.append({"chars": target, "returned": got})

    ok = [r["chars"] for r in rows if r["returned"] > 0]
    zero = [r["chars"] for r in rows if r["returned"] == 0]
    print()
    if ok and zero:
        last_ok, first_zero = max(ok), min(zero)
        monotone = last_ok < first_zero
        print(f"  longest returning results : {last_ok}")
        print(f"  shortest returning nothing: {first_zero}")
        print(f"  monotone                  : {monotone}")
        if monotone and first_zero == last_ok + 1:
            print(f"\n  The limit is exact: a query may be at most {last_ok} characters.")
            if last_ok == 512:
                print("  512 — a round backend buffer, as suspected.")
    else:
        print("  inconclusive — no boundary inside the swept range")

    OUT.write_text(json.dumps(rows, indent=2))
    print(f"\n  api calls: {client.call_count}   report: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
