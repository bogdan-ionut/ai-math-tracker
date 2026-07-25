"""K10 — why do six of fourteen queries return exactly zero?

Two live runs days apart returned the same six queries at zero. Length is ruled
out (462 chars works, 417 does not, everything shorter works) and so is a plain
OR-term count. What survives is that all six demand a conjunction of three or
more concept groups, or a group of almost entirely quoted phrases.

That is consistent with two very different worlds:

  (a) the queries are genuinely restrictive — no post in the searchable window
      contains a Lean phrase *and* a named AI system;
  (b) the backend silently degrades on certain query shapes and drops posts it
      should return.

An ablation ladder alone cannot separate them: "I removed a group and results
appeared" is exactly what world (a) predicts too. So this probe runs two
experiments, and the second is the one that decides.

**Experiment 1 — ablation.** Take a failing query verbatim and remove one
element at a time. Isolates *which* element is responsible, in either world.

**Experiment 2 — witness.** Search one group alone, take a tweet the API itself
just returned, and read its text to find a term from the second group that the
tweet demonstrably contains. Now query the conjunction. The witness is indexed,
recent, and provably satisfies both groups — so if the conjunction does not
return it, world (a) is excluded and the backend is dropping results. If it
does return it, the shape is fine and the six queries are simply restrictive.

This asks a question rather than testing a hypothesis, which is the point: the
last two hypotheses about K10 (length, term count) were both wrong.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.query_builder import build_queries  # noqa: E402
from scripts.automation.twitter import TwitterApiClient, TwitterApiError  # noqa: E402

OUT = Path("differential_probe.json")

# The failing query to dissect. `formal-verification` is the sharpest case: two
# groups, one of them almost entirely quoted phrases.
TARGET = "formal-verification"

_GROUP = re.compile(r"\(([^()]*)\)")
_QUOTED = re.compile(r'^"(.*)"$')


@dataclass
class Trial:
    label: str
    query: str
    returned: int = -1
    error: str | None = None
    note: str = ""

    def row(self) -> str:
        got = "ERROR" if self.error else str(self.returned)
        flag = "  ←" if self.error is None and self.returned == 0 else ""
        return f"  {self.label:<34} {len(self.query):>4}ch {got:>6}{flag}  {self.note}"


@dataclass
class Probe:
    client: TwitterApiClient
    trials: list[Trial] = field(default_factory=list)

    def run(self, label: str, query: str, note: str = "") -> Trial:
        """Search once, reusing the result if this exact query was already run.

        Every trial is a paid call, and the ladder generates no-ops by
        construction — trimming a group to 8 terms does nothing to a group that
        has 3. This matters beyond cost: the witness experiment re-asks the
        *baseline* query, which ablation has already measured, so it must get
        that measurement back rather than nothing.
        """
        for prior in self.trials:
            if prior.query == query:
                print(f"  {label:<34} {len(query):>4}ch {prior.returned:>6}"
                      f"   (reused `{prior.label}`)", flush=True)
                return prior
        t = Trial(label, query, note=note)
        try:
            t.returned = len(self.client.search(query, max_pages=1))
        except TwitterApiError as exc:
            t.error = str(exc)
        self.trials.append(t)
        print(t.row(), flush=True)
        return t


def parse(query: str) -> tuple[list[list[str]], str]:
    """Split a built query into its OR-groups and its trailing bare operators."""
    groups = [[t.strip() for t in m.group(1).split(" OR ") if t.strip()]
              for m in _GROUP.finditer(query)]
    tail = " ".join(tok for tok in _GROUP.sub("", query).split() if tok)
    return groups, tail


def g(terms: list[str]) -> str:
    return "(" + " OR ".join(terms) + ")"


def unquote(terms: list[str]) -> list[str]:
    """Drop quotes, keeping only the first word — an unquoted multi-word phrase
    would become an implicit AND and change the query's meaning entirely."""
    out = []
    for t in terms:
        m = _QUOTED.match(t)
        out.append(m.group(1).split()[0] if m else t)
    return out


# ------------------------------------------------------------------ experiment 1

def ablate(probe: Probe, query: str) -> None:
    groups, tail = parse(query)
    print(f"\n── Experiment 1: ablation of `{TARGET}` "
          f"({len(groups)} groups, tail {tail!r})\n")

    probe.run("baseline (verbatim)", query, "expected 0 from production")

    for tok in tail.split():
        probe.run(f"drop {tok}", " ".join(
            [g(x) for x in groups] + [t for t in tail.split() if t != tok]))

    for i in range(len(groups)):
        kept = [g(x) for j, x in enumerate(groups) if j != i]
        probe.run(f"drop group {i + 1}", " ".join(kept + [tail]),
                  f"{len(groups[i])} terms removed")

    for i, grp in enumerate(groups):
        if any(_QUOTED.match(t) for t in grp):
            swapped = [g(unquote(x)) if j == i else g(x) for j, x in enumerate(groups)]
            probe.run(f"unquote group {i + 1}", " ".join(swapped + [tail]),
                      "phrases → first word only")

    for n in (8, 4, 2, 1):
        trimmed = [g(x[:n]) for x in groups]
        probe.run(f"all groups → {n} term(s)", " ".join(trimmed + [tail]))

    for i, grp in enumerate(groups):
        if len(grp) <= 2:
            continue
        shrunk = [g(x[:2]) if j == i else g(x) for j, x in enumerate(groups)]
        probe.run(f"group {i + 1} → 2 terms", " ".join(shrunk + [tail]),
                  "other group untouched")


# ------------------------------------------------------------------ experiment 2

def witness(probe: Probe, query: str) -> dict:
    """Prove or disprove that the backend drops satisfiable conjunctions."""
    groups, tail = parse(query)
    print("\n── Experiment 2: witness "
          "(does a provably-matching indexed post survive the conjunction?)\n")

    if len(groups) < 2:
        return {"conclusive": False, "why": "need at least two groups"}

    a, b = groups[0], groups[1]
    print(f"  searching group 1 alone ({len(a)} terms) for a witness…")
    try:
        pool = probe.client.search(g(a) + " " + tail, max_pages=1)
    except TwitterApiError as exc:
        return {"conclusive": False, "why": f"group 1 alone failed: {exc}"}

    # A witness must contain a term from group 1 AND a term from group 2, both
    # verified against the text the API itself returned.
    for tw in pool:
        text = (tw.get("text") or "").lower()
        hit_a = next((t for t in a if _needle(t) in text), None)
        hit_b = next((t for t in b if _needle(t) in text), None)
        if not (hit_a and hit_b):
            continue
        author = ((tw.get("author") or {}).get("userName") or "").strip()
        tid = str(tw.get("id") or "")
        print(f"  witness {tid} by @{author or '?'}")
        print(f"    satisfies group 1 via {hit_a}   and group 2 via {hit_b}\n")

        found = {}
        found["pair"] = probe.run(
            "witness: the two hit terms", f"{hit_a} {hit_b} {tail}",
            "minimal conjunction the witness satisfies")
        found["groups"] = probe.run(
            "witness: full group1 AND group2", f"{g(a)} {g(b)} {tail}",
            "the failing shape, unmodified")
        found["scoped"] = probe.run(
            "witness: from:author + both groups", f"from:{author} {g(a)} {g(b)}",
            "narrowed to the witness's own feed") if author else None

        return _verdict(tid, author, hit_a, hit_b, found, probe)

    return {"conclusive": False,
            "why": f"no post among {len(pool)} satisfied both groups — "
                   "consistent with the queries being genuinely restrictive"}


def _needle(term: str) -> str:
    m = _QUOTED.match(term)
    return (m.group(1) if m else term).lower()


def _verdict(tid, author, hit_a, hit_b, found, probe) -> dict:
    """A witness proves the conjunction is satisfiable. Zero results means the
    backend dropped it."""
    seen_in = {}
    for key, trial in found.items():
        if trial is None or trial.error:
            continue
        seen_in[key] = trial.returned

    dropped = [k for k, n in seen_in.items() if n == 0]
    return {
        "conclusive": bool(seen_in),
        "witnessId": tid, "witnessAuthor": author,
        "satisfiesGroup1Via": hit_a, "satisfiesGroup2Via": hit_b,
        "returned": seen_in,
        "backendDropsSatisfiableConjunctions": bool(dropped),
        "queriesReturningZeroDespiteWitness": dropped,
    }


# ------------------------------------------------------------------ experiment 3

def bisect_conjunction(probe: Probe, query: str) -> dict:
    """Where is the boundary, and is it the total or the largest group?

    Experiment 1 showed a 35-term group returns results *alone* but kills the
    query when conjoined, while trimming it to 2 restores it. That is the fix's
    shape — but "cap what?" needs an answer, and the two candidates make
    different predictions:

      total       — 4 AND 20 should fail exactly like 20 AND 4
      largest     — both should fail, but an even 12 AND 12 (same total) should
                    survive if the cap is per-group

    So: walk one group's size down with the other pinned small, then re-test the
    discovered boundary split evenly.
    """
    groups, tail = parse(query)
    print("\n── Experiment 3: where the conjunction breaks\n")
    if len(groups) < 2:
        return {}

    small, big = groups[0][:2], groups[1]
    sizes = [n for n in (35, 28, 24, 20, 16, 12, 8) if n <= len(big)]
    results: dict[int, int] = {}
    for n in sizes:
        t = probe.run(f"2 AND {n} terms", f"{g(small)} {g(big[:n])} {tail}")
        if t.error is None:
            results[n] = t.returned

    working = [n for n, got in results.items() if got > 0]
    failing = [n for n, got in results.items() if got == 0]
    boundary = max(working) if working else None
    out = {"perSize": results, "largestWorking": boundary,
           "smallestFailing": min(failing) if failing else None}

    # Same total, split evenly — the discriminating case.
    if boundary and failing:
        total = min(failing) + 2
        half = total // 2
        if half <= len(groups[0]) and half <= len(big):
            t = probe.run(f"{half} AND {total - half} terms (same total, even split)",
                          f"{g(groups[0][:half])} {g(big[:total - half])} {tail}",
                          f"total {total} failed as 2 AND {min(failing)}")
            if t.error is None:
                out["evenSplitAtFailingTotal"] = t.returned
                out["capIsOn"] = "total" if t.returned == 0 else "the largest group"
    return out


# ------------------------------------------------------------------ main

def main() -> int:
    queries = {q.id: q for q in build_queries()}
    if TARGET not in queries:
        print(f"::error::{TARGET} is not a built query")
        return 2
    query = queries[TARGET].query

    client = TwitterApiClient(timeout=25, max_retries=3, min_interval=2.0)
    probe = Probe(client)

    ablate(probe, query)
    result = witness(probe, query)
    limits = bisect_conjunction(probe, query)

    print("\n── Summary\n")
    zeros = [t for t in probe.trials if t.error is None and t.returned == 0]
    print(f"  trials            : {len(probe.trials)}")
    print(f"  returning zero    : {len(zeros)}")
    for t in zeros:
        print(f"      {t.label}")

    if result.get("conclusive"):
        if result["backendDropsSatisfiableConjunctions"]:
            print("\n  VERDICT: the backend drops results it should return.")
            print(f"  Post {result['witnessId']} contains {result['satisfiesGroup1Via']} "
                  f"and {result['satisfiesGroup2Via']}, is indexed (the API returned it),")
            print(f"  yet these came back empty: {result['queriesReturningZeroDespiteWitness']}")
            print("  → the six queries are not merely restrictive. The shape is at fault.")
        else:
            print("\n  VERDICT: a satisfiable conjunction IS returned.")
            print("  → the shape works; the six queries are genuinely restrictive,")
            print("    and the fix is to loosen them, not to work around the API.")
    else:
        print(f"\n  VERDICT: inconclusive — {result.get('why')}")

    if limits.get("largestWorking"):
        print(f"\n  Largest second group that survives a conjunction: "
              f"{limits['largestWorking']} terms "
              f"(fails at {limits['smallestFailing']}).")
        if "capIsOn" in limits:
            print(f"  The cap is on {limits['capIsOn']}.")

    OUT.write_text(json.dumps({
        "target": TARGET,
        "trials": [vars(t) for t in probe.trials],
        "witness": result,
        "conjunctionLimits": limits,
        "apiCalls": client.call_count,
    }, indent=2, ensure_ascii=False))
    print(f"\n  api calls: {client.call_count}   report: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
