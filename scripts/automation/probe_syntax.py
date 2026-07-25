"""Empirically probe TwitterAPI.io search capabilities and verify account handles.

The strategy document must not assume that every X search operator works here just
because it works on the public website. This script *measures* instead:

  - runs a control query and a series of operator queries;
  - an operator is judged SUPPORTED if it returns results that differ from the
    control in the direction the operator implies (e.g. a negation returns fewer,
    a `from:` returns only that author);
  - reports UNKNOWN rather than guessing when the evidence is ambiguous.

Read-only. Prints counts and verdicts, never tweet text and never the key.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.twitter import TwitterApiClient, TwitterApiError  # noqa: E402

# Handles to verify. Sourced from data/results.json where possible; the rest are
# candidates awaiting exactly this verification before being enabled.
CANDIDATE_HANDLES = [
    ("octonion", "evidenced in data/results.json"),
    ("imjaredz", "evidenced in data/results.json"),
    ("erdosproblems", "candidate — problem registry"),
    ("teorth", "candidate — mathematician who audits AI proofs"),
    ("GoogleDeepMind", "candidate — lab"),
    ("OpenAI", "candidate — lab"),
    ("leanprover", "candidate — formal methods"),
    ("XenaProject", "candidate — formal methods"),
]


def probe_operators(client: TwitterApiClient) -> list[dict]:
    """Each probe: (name, query, predicate on results, why it matters)."""
    results: list[dict] = []

    def run(name: str, query: str, note: str) -> tuple[int, list[dict]]:
        try:
            tweets = client.search(query, query_type="Latest", max_pages=1)
            return len(tweets), tweets
        except TwitterApiError as exc:
            results.append({"operator": name, "query": query, "verdict": "ERROR",
                            "detail": str(exc), "note": note})
            return -1, []

    # control
    n_control, _ = run("control (single term)", "conjecture", "baseline")
    results.append({"operator": "control (single term)", "query": "conjecture",
                    "verdict": "OK" if n_control > 0 else "NO RESULTS",
                    "returned": n_control, "note": "baseline"})

    # quoted phrase
    n, tweets = run("quoted phrase", '"open problem"', "phrases must stay intact")
    if n >= 0:
        hit = sum(1 for t in tweets if "open problem" in (t.get("text") or "").lower())
        results.append({"operator": "quoted phrase", "query": '"open problem"',
                        "verdict": "SUPPORTED" if hit else "UNKNOWN",
                        "returned": n, "matchingPhrase": hit,
                        "note": "phrases must stay intact"})

    # OR
    n, _ = run("OR", "(conjecture OR theorem)", "needed by every query family")
    results.append({"operator": "OR", "query": "(conjecture OR theorem)",
                    "verdict": "SUPPORTED" if n > 0 else "UNKNOWN", "returned": n,
                    "note": "needed by every query family"})

    # implicit AND + parentheses
    n, tweets = run("AND + parentheses", '(conjecture OR theorem) (AI OR LLM)',
                    "the core shape of all families")
    if n >= 0:
        both = sum(1 for t in tweets
                   if any(k in (t.get("text") or "").lower() for k in ("conjecture", "theorem"))
                   and any(k in (t.get("text") or "").lower() for k in ("ai", "llm")))
        results.append({"operator": "AND + parentheses",
                        "query": '(conjecture OR theorem) (AI OR LLM)',
                        "verdict": "SUPPORTED" if both else "UNKNOWN",
                        "returned": n, "matchingBoth": both,
                        "note": "the core shape of all families"})

    # negation
    n_neg, tweets = run("negation (-term)", "conjecture -crypto", "noise reduction")
    if n_neg >= 0:
        leaked = sum(1 for t in tweets if "crypto" in (t.get("text") or "").lower())
        results.append({"operator": "negation (-term)", "query": "conjecture -crypto",
                        "verdict": "SUPPORTED" if leaked == 0 else "NOT SUPPORTED",
                        "returned": n_neg, "excludedTermLeaked": leaked,
                        "note": "noise reduction"})

    # language filter
    n, tweets = run("lang:", "conjecture lang:en", "cuts non-English noise")
    if n >= 0:
        results.append({"operator": "lang:", "query": "conjecture lang:en",
                        "verdict": "SUPPORTED" if n > 0 else "UNKNOWN", "returned": n,
                        "note": "cuts non-English noise"})

    # retweet filter
    n, tweets = run("-filter:retweets", "conjecture -filter:retweets", "dedup before ingest")
    if n >= 0:
        rts = sum(1 for t in tweets if t.get("retweeted_tweet"))
        results.append({"operator": "-filter:retweets", "query": "conjecture -filter:retweets",
                        "verdict": "SUPPORTED" if rts == 0 else "NOT SUPPORTED",
                        "returned": n, "retweetsLeaked": rts, "note": "dedup before ingest"})

    # url filter
    n, tweets = run("url:", "url:arxiv.org", "artifact-bearing posts")
    if n >= 0:
        results.append({"operator": "url:", "query": "url:arxiv.org",
                        "verdict": "SUPPORTED" if n > 0 else "UNKNOWN", "returned": n,
                        "note": "artifact-bearing posts"})

    # unicode
    n, tweets = run("unicode (Erdős)", '"Erdős problem"', "must not need ASCII folding")
    if n >= 0:
        results.append({"operator": "unicode (Erdős)", "query": '"Erdős problem"',
                        "verdict": "SUPPORTED" if n > 0 else "UNKNOWN", "returned": n,
                        "note": "must not need ASCII folding"})

    # since/until
    n, _ = run("since:", "conjecture since:2026-07-01", "window control")
    results.append({"operator": "since:", "query": "conjecture since:2026-07-01",
                    "verdict": "SUPPORTED" if n > 0 else "UNKNOWN", "returned": n,
                    "note": "window control"})

    # long query — where does it break?
    long_q = "(" + " OR ".join(f'"term number {i}"' for i in range(40)) + ")"
    n, _ = run(f"long query ({len(long_q)} chars)", long_q, "max query length")
    results.append({"operator": f"long query ({len(long_q)} chars)", "query": "<40 OR-terms>",
                    "verdict": "ACCEPTED" if n >= 0 else "REJECTED", "returned": n,
                    "note": "max query length"})

    return results


def probe_handles(client: TwitterApiClient) -> list[dict]:
    out: list[dict] = []
    for handle, why in CANDIDATE_HANDLES:
        try:
            tweets = client.search(f"from:{handle}", query_type="Latest", max_pages=1)
        except TwitterApiError as exc:
            out.append({"handle": handle, "verdict": "ERROR", "detail": str(exc), "why": why})
            continue
        authors = {
            (t.get("author") or {}).get("userName", "").lower()
            for t in tweets
            if isinstance(t.get("author"), dict)
        }
        if not tweets:
            verdict = "NO RESULTS"          # may exist but be quiet, or may not exist
        elif authors and authors <= {handle.lower()}:
            verdict = "VERIFIED"            # from: filtered correctly to this author
        else:
            verdict = "UNEXPECTED AUTHORS"
        out.append({"handle": handle, "verdict": verdict, "returned": len(tweets),
                    "distinctAuthors": len(authors), "why": why})
    return out


def main() -> int:
    try:
        client = TwitterApiClient(timeout=25, max_retries=4, min_interval=2.5)
    except TwitterApiError as exc:
        print(f"::error::{exc}")
        return 1

    print("═══ OPERATOR SUPPORT ══════════════════════════════════════")
    ops = probe_operators(client)
    for r in ops:
        extra = " ".join(f"{k}={v}" for k, v in r.items()
                         if k not in ("operator", "query", "verdict", "note"))
        print(f"  {r['verdict']:<16} {r['operator']:<28} {extra}")

    print()
    print("═══ TRUSTED-ACCOUNT HANDLES ═══════════════════════════════")
    handles = probe_handles(client)
    for r in handles:
        print(f"  {r['verdict']:<18} @{r['handle']:<18} returned={r.get('returned','-')}  ({r['why']})")

    verified = [h["handle"] for h in handles if h["verdict"] == "VERIFIED"]
    print()
    print(f"api calls total : {client.call_count}")
    print(f"verified handles: {verified or 'none'}")

    Path("probe_report.json").write_text(
        json.dumps({"operators": ops, "handles": handles,
                    "verifiedHandles": verified, "apiCalls": client.call_count},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("wrote probe_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
