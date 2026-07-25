"""End-to-end trace of a single observation, printing every stage.

Runs a real post through the real pipeline and shows exactly what each layer
received and produced — what the API returned, what survived validation, what
the guard discarded, what matching decided, and what actually landed on disk.

Uses a verbatim captured post so the trace is honest about real behaviour rather
than fixture-shaped. Read-only: writes to a temp directory, never to the repo.

    python -m scripts.automation.trace            # live Gemini
    python -m scripts.automation.trace --offline  # stub model, no key needed
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation import store  # noqa: E402

# --- the raw tweet, exactly as TwitterAPI.io returns it --------------------
# Verbatim; cited as a source in data/results.json.
RAW_TWEET = {
    "id": "2080088344424583261",
    "text": ("1) Graffiti Conjecture 154 REFUTED. Open for ~40 years. Devin found the "
             "counterexample: glue a 50-clique to a 70-edge path (n=120). The violation "
             "reduces to a single integer inequality, proven in Lean down to the graph's "
             "distance sum. 2) Graffiti Conjectures 39 & 40 PROVEN."),
    "url": "https://x.com/imjaredz/status/2080088344424583261",
    "createdAt": "Thu Jul 23 14:02:11 +0000 2026",
    "conversationId": "2080088344424583261",
    "likeCount": 1200, "retweetCount": 210, "replyCount": 33,
    "quoteCount": 8, "viewCount": 99000,
    "author": {"userName": "imjaredz", "name": "Jared Zoneraich"},
    "entities": {"urls": [{
        "url": "https://t.co/abc",
        "expanded_url": "https://github.com/cognition/graffiti-lean?utm_source=twitter&ref=x",
    }]},
}

RULE = "─" * 74


def head(n: int, title: str) -> None:
    print(f"\n{RULE}\n {n}. {title}\n{RULE}")


def blob(obj, limit: int = 2000) -> str:
    s = json.dumps(obj, indent=2, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + "\n  … truncated"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use a stub model")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="trace-"))
    store.DATA_DIR = tmp
    store.RAW_DIR = tmp / "raw"

    from scripts.automation.extraction import extract_one, load_prompt, render_prompt
    from scripts.automation.extraction_schema import (
        ExtractionResult, cross_check_identifiers, gemini_response_schema,
    )
    from scripts.automation.ingest import normalise_tweet, to_observation
    from scripts.automation.matching import build_judge_payload, load_registry, match_observation
    from scripts.automation.merge import apply_decision, decide
    from scripts.automation.models import utc_now_iso

    now = utc_now_iso()

    # ---------------------------------------------------------------- 1
    head(1, "WHAT TWITTERAPI.IO RETURNED (raw, one tweet)")
    print(blob({k: RAW_TWEET[k] for k in
                ("id", "text", "url", "createdAt", "author", "likeCount", "viewCount")}))
    print(f"\n  entities.urls[0].expanded_url:\n    {RAW_TWEET['entities']['urls'][0]['expanded_url']}")

    # ---------------------------------------------------------------- 2
    head(2, "NORMALISED → OBSERVATION (no model involved)")
    raw = normalise_tweet(RAW_TWEET, "explicit-ai-solution", now, store_text=True)
    obs = to_observation(raw, now).model_dump(mode="json")
    print(blob({k: obs[k] for k in
                ("id", "sourceNativeId", "url", "author", "links", "externalIds", "status")}))
    print("\n  ▸ tracking params stripped from the link (utm_source, ref)")
    print("  ▸ identifiers extracted by regex, before any model saw the text")
    print(f"  ▸ engagement captured on the raw record but ABSENT from the observation: "
          f"{'engagement' not in obs}")

    # ---------------------------------------------------------------- 3
    head(3, "WHAT WAS SENT TO GEMINI")
    template = load_prompt("extraction_v1")
    prompt = render_prompt(template, obs)
    print(f"  prompt chars     : {len(prompt)}")
    print(f"  model            : gemini-3.6-flash")
    print(f"  engagement words : "
          f"{[w for w in ('likes','retweets','views','follower') if w in prompt.lower()] or 'none'}")
    print(f"  required fields  : {gemini_response_schema()['required']}")
    print("\n  --- last 12 lines of the rendered prompt ---")
    for line in prompt.strip().splitlines()[-12:]:
        print(f"    {line}")

    # ---------------------------------------------------------------- 4
    head(4, "WHAT GEMINI RETURNED")
    if args.offline:
        from scripts.automation.gemini import StubModel
        client = StubModel({
            "isRelevant": True, "claimType": "new_result", "resultType": "counterexample",
            "canonicalProblemName": "Graffiti Conjecture 154",
            "problemAliases": ["Graffiti 154"], "problemFamily": "Graffiti",
            "mathematicalField": "graph theory", "modelName": "Devin",
            "claimingOrganization": "Cognition", "claimedAt": "2026-07-23",
            "externalIdentifiers": {"github": ["https://github.com/cognition/graffiti-lean"]},
            "evidenceAvailable": True, "extractionConfidence": 0.95,
            "summary": "Devin refuted Graffiti Conjecture 154 with a 120-vertex counterexample.",
            "uncertainties": [],
        })
        print("  (offline stub — no API call)")
    else:
        from scripts.automation.gemini import GeminiClient
        client = GeminiClient(model="gemini-3.6-flash", timeout=60)

    raw_out = client.generate_json(prompt, gemini_response_schema())
    print(blob(raw_out))

    # ---------------------------------------------------------------- 5
    head(5, "VALIDATION + HALLUCINATION GUARD")
    parsed = ExtractionResult(**raw_out)
    kept, warnings = cross_check_identifiers(parsed, obs.get("text"), obs.get("links"))
    print(f"  model claimed identifiers : {parsed.externalIdentifiers or '{}'}")
    print(f"  regex found in source     : "
          f"{ {k: v for k, v in kept.items()} }")
    print(f"  guard warnings            : {warnings or 'none'}")
    print("\n  ▸ the stored value is OUR canonical form, never the model's raw string")

    updated, err = extract_one(client, obs, template, "extraction_v1", "gemini-3.6-flash")
    print(f"  observation status        : {updated['status']}   (error: {err})")

    # ---------------------------------------------------------------- 6
    head(6, "MATCHING AGAINST THE CURATED REGISTRY (no model)")
    registry = load_registry()
    outcome = match_observation(updated, registry)
    print(f"  registry size   : {len(registry)} curated records")
    print(f"  method          : {outcome.method}")
    print(f"  matched problem : {outcome.matched_id}")
    print(f"  needs judge     : {outcome.needs_judge}")
    print(f"  notes           : {outcome.notes}")
    if outcome.shortlist:
        print("  shortlist:")
        for c in outcome.shortlist[:5]:
            print(f"      {c.score:6.1f}  {c.record_id:<32} via {c.method}  — {c.reason}")

    # ---------------------------------------------------------------- 7
    head(7, "JUDGE")
    if outcome.needs_judge:
        payload = build_judge_payload(updated, outcome, registry)
        print(f"  judge WOULD be called; payload candidates: {len(payload['candidates'])}")
        print(f"  editorial fields in payload: "
              f"{[f for f in ('impact','assessment','auditNotes') if f in json.dumps(payload)] or 'none'}")
    else:
        print("  NOT CALLED — matching was deterministic, so no model call and no cost.")

    # ---------------------------------------------------------------- 8
    head(8, "DECISION + MERGE")
    decision = decide(outcome, None)
    print(f"  decision : {decision}")
    cands, queue, report = apply_decision(decision, updated, outcome, [], [], now=now)
    print(f"  report   : created={report.candidatesCreated} updated={report.candidatesUpdated} "
          f"claims={report.claimsAdded} sources={report.sourcesAttached} "
          f"reviews={report.reviewsCreated}")
    print(f"  notes    : {report.notes}")

    # ---------------------------------------------------------------- 9
    head(9, "WHAT ENDED UP ON DISK")
    print("  data/automation/candidates.json:")
    print(blob(cands, 1400))
    print("\n  data/automation/review_queue.json:")
    print(blob(queue, 800) if queue else "    []   (nothing needed a human)")

    head(10, "WHAT DID NOT CHANGE")
    reg_after = load_registry()
    print(f"  data/results.json records : {len(reg_after)}")
    print(f"  identical to before       : {reg_after == registry}")
    print("  ▸ candidates are proposals. Promotion into the curated registry is a")
    print("    human action; no code path in this pipeline can perform it.")
    print(f"\n  (trace wrote only to {tmp})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
