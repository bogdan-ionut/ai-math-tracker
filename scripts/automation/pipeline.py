"""Match → judge → merge, over already-extracted observations.

    python -m scripts.automation.pipeline --dry-run   # stub judge, writes nothing
    python -m scripts.automation.pipeline             # live, needs GEMINI_API_KEY

The judge is called only for observations that matching could not resolve, and
its budget is capped. Everything it says is a label; `merge.apply_decision`
decides what actually happens, and `data/results.json` is never opened for
writing anywhere in this path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation import store  # noqa: E402
from scripts.automation.gemini import GeminiClient, GeminiError, StructuredModel  # noqa: E402
from scripts.automation.matching import (  # noqa: E402
    build_judge_payload,
    judge_response_schema,
    load_registry,
    match_observation,
)
from scripts.automation.merge import apply_decision, resolve  # noqa: E402
from scripts.automation.models import ProcessingState, utc_now_iso  # noqa: E402
from scripts.automation.policy import assert_registry_untouched  # noqa: E402
from scripts.automation.review import summarize  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def load_judge_prompt(version: str) -> str:
    body = (PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")
    idx = body.find("## SYSTEM")
    if idx == -1:
        raise ValueError(f"judge prompt {version} has no ## SYSTEM section")
    return body[idx:]


def ask_judge(client: StructuredModel, template: str, payload: dict) -> tuple[dict | None, str | None]:
    prompt = (
        template.replace("{observation}", json.dumps(payload["observation"], indent=2, ensure_ascii=False))
        .replace("{candidates}", json.dumps(payload["candidates"], indent=2, ensure_ascii=False))
    )
    try:
        return client.generate_json(prompt, judge_response_schema()), None
    except GeminiError as exc:
        return None, str(exc)


def run(dry_run: bool = False, judge_client: StructuredModel | None = None,
        limit: int | None = None) -> dict:
    cfg = json.loads((ROOT / "config" / "automation.json").read_text(encoding="utf-8"))
    jcfg = cfg["judge"]
    max_judge = limit if limit is not None else jcfg.get("maxCallsPerRun", 15)
    shortlist_size = jcfg.get("shortlistSize", 5)

    try:
        observations = store.read_json(store.observations_path(), [])
        candidates = store.read_json(store.candidates_path(), [])
        queue = store.read_json(store.review_queue_path(), [])
    except store.CorruptStoreError as exc:
        return {"ok": False, "error": f"refusing to run: {exc}"}

    registry = load_registry()
    registry_snapshot = json.loads(json.dumps(registry))

    ready = [o for o in observations if o.get("status") == "extracted"]
    now = utc_now_iso()

    template = load_judge_prompt(jcfg.get("promptVersion", "judge_v1"))

    # The judge client is built lazily, on first genuine need. Most runs resolve
    # every observation deterministically, and those must not require a
    # GEMINI_API_KEY at all — demanding one up front would make the common path
    # fail for a call it was never going to make.
    _judge_state: dict = {"client": judge_client, "tried": judge_client is not None,
                          "error": None}

    def get_judge() -> StructuredModel | None:
        if _judge_state["tried"]:
            return _judge_state["client"]
        _judge_state["tried"] = True
        if dry_run:
            return None
        try:
            _judge_state["client"] = GeminiClient(
                model=jcfg.get("model", "gemini-3.6-flash"),
                timeout=jcfg.get("timeoutSeconds", 60),
            )
        except GeminiError as exc:
            _judge_state["error"] = str(exc)
            _judge_state["client"] = None
        return _judge_state["client"]

    judge_calls = judge_failures = judge_deferred = 0
    decisions: dict[str, int] = {}
    totals = {"candidatesCreated": 0, "candidatesUpdated": 0, "claimsAdded": 0,
              "sourcesAttached": 0, "reviewsCreated": 0}
    by_id = {o["id"]: dict(o) for o in observations}

    for o in ready:
        outcome = match_observation(o, registry, shortlist_size=shortlist_size)

        verdict = None
        judge_status = "not_needed"
        if outcome.needs_judge:
            if judge_calls >= max_judge:
                judge_status = "budget_exhausted"
            else:
                client = get_judge()
                if client is None:
                    judge_status = "unavailable"
                else:
                    judge_calls += 1
                    verdict, err = ask_judge(client, template,
                                             build_judge_payload(o, outcome, registry))
                    if err:
                        judge_failures += 1
                        judge_status = "failed"
                    else:
                        judge_status = "ok"

        resolution = resolve(outcome, verdict, judge_status=judge_status)
        decisions[resolution.decision] = decisions.get(resolution.decision, 0) + 1

        candidates, queue, report = apply_decision(
            resolution, o, outcome, candidates, queue, now=now
        )
        for k in totals:
            totals[k] += getattr(report, k)

        rec = by_id[o["id"]]
        if resolution.deferred:
            # We never asked. Leave the observation untouched so the next run
            # retries it — recording a conclusion here would make an operational
            # gap look like a judgement about the post.
            judge_deferred += 1
            by_id[o["id"]] = rec
            continue

        rec["matchMethod"] = outcome.method
        rec["problemRef"] = resolution.matched_id
        rec["decision"] = resolution.decision
        rec["status"] = "merged" if report.candidatesCreated or report.candidatesUpdated else "review"
        by_id[o["id"]] = rec

    # The guarantee, checked rather than asserted in prose.
    assert_registry_untouched(registry_snapshot, load_registry())

    summary = {
        "ok": True, "dryRun": dry_run,
        "observationsReady": len(ready),
        "judgeCalls": judge_calls, "judgeFailures": judge_failures,
        "judgeDeferred": judge_deferred,
        "judgeBudget": max_judge,
        "judgeUnavailable": _judge_state["error"],
        "decisions": decisions,
        **totals,
        "candidatesTotal": len(candidates),
        "reviewOpenByReason": summarize(queue),
    }

    if dry_run:
        summary["proposedMutations"] = {
            "candidates.json": f"{len(candidates)} after run",
            "review_queue.json": f"{len(queue)} after run",
        }
        return summary

    store.write_json(store.candidates_path(), candidates)
    store.write_json(store.review_queue_path(), queue)
    store.write_json(store.observations_path(),
                     sorted(by_id.values(), key=lambda o: (o.get("sourceCreatedAt") or "", o["id"])))

    try:
        state = ProcessingState(**store.read_json(store.state_path(), {}))
    except Exception:
        state = ProcessingState()
    state.lastRunAt = now
    state.bump("candidatesCreated", totals["candidatesCreated"])
    state.bump("reviewsCreated", totals["reviewsCreated"])
    state.bump_api("geminiJudge", judge_calls)
    store.write_json(store.state_path(), state.model_dump(mode="json"))

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Match, judge and merge extracted observations.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, help="override the judge call budget")
    args = ap.parse_args()
    result = run(dry_run=args.dry_run, limit=args.limit)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
