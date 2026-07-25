"""Live smoke test for Gemini extraction.

Runs the real prompt through the pinned model against a genuine post and reports
whether the output validates. Also runs two control cases the pipeline depends
on being handled correctly:

  * a known-irrelevant post (must come back isRelevant=false);
  * a post with no identifiers (must NOT invent one — the hallucination guard).

Read-only. Prints structure and verdicts, never the API key.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.extraction import load_prompt, render_prompt  # noqa: E402
from scripts.automation.extraction_schema import (  # noqa: E402
    ExtractionResult,
    cross_check_identifiers,
    gemini_response_schema,
)
from scripts.automation.gemini import GeminiClient, GeminiError  # noqa: E402

CONFIG = json.loads(
    (Path(__file__).resolve().parents[2] / "config" / "automation.json").read_text()
)

# Real post — verbatim, cited in data/results.json as a source.
REAL = {
    "author": "imjaredz",
    "sourceCreatedAt": "Thu Jul 23 14:02:11 +0000 2026",
    "url": "https://x.com/imjaredz/status/2080088344424583261",
    "links": ["https://github.com/cognition/graffiti-lean"],
    "text": ("1) Graffiti Conjecture 154 REFUTED. Open for ~40 years. Devin found the "
             "counterexample: glue a 50-clique to a 70-edge path (n=120). The violation "
             "reduces to a single integer inequality, proven in Lean down to the graph's "
             "distance sum. 2) Graffiti Conjectures 39 & 40 PROVEN."),
}

IRRELEVANT = {
    "author": "someone",
    "sourceCreatedAt": "Fri Jul 24 08:00:00 +0000 2026",
    "url": "https://x.com/someone/status/1",
    "links": [],
    "text": "Our new chain uses proof of work with an AI-optimised difficulty adjustment. Airdrop soon.",
}

NO_IDENTIFIERS = {
    "author": "rando",
    "sourceCreatedAt": "Fri Jul 24 09:00:00 +0000 2026",
    "url": "https://x.com/rando/status/2",
    "links": [],
    "text": ("Huge if true — an AI just settled the Erdős unit distance problem. "
             "No link yet, but people are saying the proof is real."),
}


def show(label: str, obs: dict, client: GeminiClient, template: str) -> dict:
    prompt = render_prompt(template, obs)
    try:
        raw = client.generate_json(prompt, gemini_response_schema())
    except GeminiError as exc:
        print(f"  {label}: ERROR — {exc}")
        return {"ok": False}

    try:
        res = ExtractionResult(**raw)
    except Exception as exc:  # noqa: BLE001
        print(f"  {label}: SCHEMA VIOLATION — {type(exc).__name__}")
        return {"ok": False}

    kept, warnings = cross_check_identifiers(res, obs["text"], obs["links"])
    print(f"  {label}")
    print(f"      relevant        : {res.isRelevant}   claimType={res.claimType}   "
          f"resultType={res.resultType}")
    print(f"      problem         : {res.canonicalProblemName!r}")
    print(f"      model / org     : {res.modelName!r} / {res.claimingOrganization!r}")
    print(f"      confidence      : {res.extractionConfidence}")
    print(f"      identifiers kept: {kept or '{}'}")
    if warnings:
        print(f"      guard warnings  : {warnings}")
    if res.uncertainties:
        print(f"      uncertainties   : {res.uncertainties}")
    return {"ok": True, "result": res, "kept": kept, "warnings": warnings}


def main() -> int:
    model = CONFIG["extraction"]["model"]
    version = CONFIG["extraction"]["promptVersion"]
    try:
        client = GeminiClient(model=model, timeout=CONFIG["extraction"]["timeoutSeconds"])
    except GeminiError as exc:
        print(f"::error::{exc}")
        return 1

    template = load_prompt(version)
    print(f"model         : {model}")
    print(f"prompt version: {version}")
    print(f"prompt chars  : {len(template)} (documentation header excluded)")
    print()

    # sanity: the header really is stripped
    leaked = [w for w in ("likes", "retweets", "views", "follower") if w in template.lower()]
    print(f"engagement terms in prompt: {leaked or 'none'}")
    if leaked:
        print("::error::engagement vocabulary leaked into the prompt")
        return 1
    print()

    print("═══ CASE 1 · real post, should be relevant ══════════════════")
    c1 = show("graffiti-154", REAL, client, template)
    print()
    print("═══ CASE 2 · crypto post, should be irrelevant ══════════════")
    c2 = show("proof-of-work", IRRELEVANT, client, template)
    print()
    print("═══ CASE 3 · claim with no identifiers, must not invent ═════")
    c3 = show("no-identifiers", NO_IDENTIFIERS, client, template)
    print()

    override = os.environ.get("PROBE_TEXT", "").strip()
    if override:
        print("═══ CASE 4 · your text ══════════════════════════════════════")
        show("custom", {**REAL, "text": override, "links": []}, client, template)
        print()

    print("═══ VERDICTS ════════════════════════════════════════════════")
    ok = True

    if c1.get("ok") and c1["result"].isRelevant:
        print("  ✅ relevant post recognised")
    else:
        print("  ❌ relevant post NOT recognised"); ok = False

    if c2.get("ok") and not c2["result"].isRelevant:
        print("  ✅ proof-of-work post rejected")
    else:
        print("  ⚠️  proof-of-work post was not rejected — classifier needs tuning")

    if c3.get("ok"):
        invented = c3["kept"].get("erdos") or c3["kept"].get("arxiv")
        if not invented:
            print("  ✅ no identifier invented for an unsourced claim")
        else:
            print(f"  ⚠️  guard kept {invented} — check the source text")

    print(f"  api calls: {client.call_count}")
    print("═════════════════════════════════════════════════════════════")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
