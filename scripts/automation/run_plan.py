"""Sprint 5.5 — a real end-to-end run that writes nothing to the repository.

    python -m scripts.automation.run_plan          # real APIs, real code path, no repo writes

**Why this exists.** The scheduled "dry run" skipped extraction and the pipeline
entirely (R1). It called TwitterAPI.io and stopped. So every claim about what
this system does downstream of ingestion — extraction quality, matching, the
judge, the merge guardrails — rested on fixtures and stub models. The gate to
enabling live writes was going to be evidence that had never been collected.

**Why a sandbox rather than a `--plan` flag on each stage.** A flag that skips
the write leaves each stage with nothing to hand the next: extraction reads the
observations ingestion did not persist. Threading state through memory would
mean the planned run exercised a different code path from the real one, which
defeats the purpose of the exercise.

So instead: copy `data/automation/` to a temporary directory, point the store at
it, and run the **ordinary** live code — real API calls, real writes, real
guardrails — into that copy. Afterwards, diff the copy against the repository to
show exactly what a live run would have changed, and verify byte-for-byte that
the repository itself did not move.

That last check is the point. It does not trust the code to be well-behaved; it
measures whether it was.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation import store  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REAL_DATA = ROOT / "data" / "automation"
REGISTRY = ROOT / "data" / "results.json"

# Files a run may legitimately create or change inside the sandbox.
TRACKED = (
    "observations.json", "candidates.json", "review_queue.json",
    "aliases.json", "ingest_backlog.json", "processing_state.json",
)


def _digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(directory: Path) -> dict[str, str | None]:
    """Hash every file that a run could touch, plus the curated registry."""
    out = {"data/results.json": _digest(REGISTRY)}
    for name in TRACKED:
        out[name] = _digest(directory / name)
    if directory.exists():
        for f in sorted(directory.rglob("*.json")):
            out[str(f.relative_to(directory))] = _digest(f)
    return out


def _rows(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def diff_stores(sandbox: Path) -> dict:
    """What a live run would have changed, per file."""
    changes = {}
    for name in TRACKED:
        before, after = _rows(REAL_DATA / name), _rows(sandbox / name)
        if _digest(REAL_DATA / name) == _digest(sandbox / name):
            continue
        ids_before = {r.get("id") for r in before if isinstance(r, dict)}
        ids_after = {r.get("id") for r in after if isinstance(r, dict)}
        changes[name] = {
            "recordsBefore": len(before), "recordsAfter": len(after),
            "added": sorted(x for x in ids_after - ids_before if x),
            "removed": sorted(x for x in ids_before - ids_after if x),
        }
    return changes


def run(limit: int | None = None) -> dict:
    """Execute the whole chain against real APIs, into a throwaway store."""
    before = fingerprint(REAL_DATA)
    sandbox = Path(tempfile.mkdtemp(prefix="plan-run-"))
    stages: dict[str, dict] = {}

    try:
        if REAL_DATA.exists():
            shutil.copytree(REAL_DATA, sandbox, dirs_exist_ok=True)

        # Redirect the store. Every stage resolves its paths through these, so
        # this is the whole of the isolation — and the fingerprint check below
        # is what verifies the claim rather than assuming it.
        real_data_dir, real_raw_dir = store.DATA_DIR, store.RAW_DIR
        store.DATA_DIR = sandbox
        store.RAW_DIR = sandbox / "raw" / "twitter"

        try:
            from scripts.automation import extraction, ingest, pipeline, verify_refs

            stages["ingest"] = ingest.run(limit=limit)
            if not stages["ingest"].get("ok"):
                return _finish(before, sandbox, stages, aborted="ingest failed")

            stages["extract"] = extraction.run()
            # Before matching: the merge engine applies the corroboration gate,
            # so a tier that turns out not to be earned has to be known first.
            stages["verify"] = verify_refs.run()
            stages["pipeline"] = pipeline.run()
        finally:
            store.DATA_DIR, store.RAW_DIR = real_data_dir, real_raw_dir

        return _finish(before, sandbox, stages)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _finish(before: dict, sandbox: Path, stages: dict, aborted: str | None = None) -> dict:
    after = fingerprint(REAL_DATA)
    touched = sorted(k for k in before if before.get(k) != after.get(k))
    return {
        "ok": aborted is None,
        "aborted": aborted,
        "mode": "plan — real APIs, no repository writes",
        "stages": stages,
        "wouldChange": diff_stores(sandbox),
        "repositoryUntouched": not touched,
        "repositoryFilesTouched": touched,
        "registryUntouched": before.get("data/results.json") == after.get("data/results.json"),
    }


def _print(report: dict) -> None:
    print("\n═══ PLAN RUN — real APIs, nothing written to the repository ═══\n")
    for name, stage in report["stages"].items():
        print(f"── {name}")
        for key in ("queriesRun", "tweetsFetched", "afterDedupe", "processed",
                    "overflowDeferred", "needingExtraction", "deferredByCap",
                    "deferredByTime", "relevant", "irrelevant", "failed",
                    "throttled", "elapsedSeconds", "quotaReason",
                    "needingCheck", "checked", "referencesResolved",
                    "referencesUnresolved", "referencesUnchecked",
                    "apiCalls", "modelCalls", "judgeCalls",
                    "judgeDeferred", "candidatesCreated", "candidatesUpdated",
                    "candidatesMerged", "reviewsCreated"):
            if key in stage:
                print(f"     {key:<22} {stage[key]}")
        for key in ("tierDowngrades", "lowAffinityResolved"):
            for line in stage.get(key) or []:
                print(f"     {key}: {line}")
        if stage.get("aborted"):
            print(f"     ::warning::ABORTED — {stage['aborted']}")
        if stage.get("decisions"):
            print(f"     decisions              {stage['decisions']}")
        if stage.get("reviewOpenByReason"):
            print(f"     review queue           {stage['reviewOpenByReason']}")
        print()

    print("── what a live run would change\n")
    if not report["wouldChange"]:
        print("     nothing\n")
    for name, delta in report["wouldChange"].items():
        print(f"     {name}: {delta['recordsBefore']} → {delta['recordsAfter']} records, "
              f"+{len(delta['added'])} new")

    print("\n── guardrails\n")
    print(f"     repository untouched   {report['repositoryUntouched']}")
    print(f"     curated registry safe  {report['registryUntouched']}")
    if report["repositoryFilesTouched"]:
        print(f"     ::error::TOUCHED: {report['repositoryFilesTouched']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="cap observations ingested this run")
    ap.add_argument("--json", action="store_true", help="emit the raw report")
    args = ap.parse_args()

    report = run(limit=args.limit)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print(report)
    Path("plan_run.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # A plan run that modified the repository is a failure regardless of what
    # else it found — that is the one thing it promises.
    if not report["repositoryUntouched"] or not report["registryUntouched"]:
        return 2
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
