"""Sprint 2: Gemini structured extraction over observations.

    python -m scripts.automation.extract --dry-run     # stub model, writes nothing
    python -m scripts.automation.extract               # live, needs GEMINI_API_KEY

Contract:
  * only observations that need it are sent (cache key = observation text +
    prompt version + model), so a second run costs zero API calls;
  * a failure marks the observation `extraction_failed` and **keeps it**, so it
    can be reprocessed later — a failed extraction is never an empty one;
  * identifiers reported by the model are cross-checked against our own regexes
    before they are stored.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation import store  # noqa: E402
from scripts.automation.extraction_schema import (  # noqa: E402
    ExtractionResult,
    cross_check_identifiers,
    gemini_response_schema,
)
from scripts.automation.gemini import (  # noqa: E402
    GeminiClient,
    GeminiError,
    SchemaViolation,
    StructuredModel,
)
from scripts.automation.ids import text_hash  # noqa: E402
from scripts.automation.models import Observation, ProcessingState, utc_now_iso  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


PROMPT_START = "## SYSTEM"


def load_prompt(version: str) -> str:
    """Return only the prompt itself, not the file's documentation header.

    These files are both documentation and prompt. Everything above `## SYSTEM`
    is commentary for maintainers — and it discusses the very things the prompt
    must not mention (engagement metrics), so shipping it would defeat the
    purpose. Only the SYSTEM/USER sections go over the wire.
    """
    path = PROMPT_DIR / f"{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt {version} not found at {path}")
    body = path.read_text(encoding="utf-8")
    idx = body.find(PROMPT_START)
    if idx == -1:
        raise ValueError(f"prompt {version} has no {PROMPT_START} section")
    return body[idx:]


def render_prompt(template: str, obs: dict) -> str:
    """Fill the template. Engagement metrics are structurally unavailable here —
    Observation does not carry them (see models.py)."""
    return (
        template.replace("{author}", str(obs.get("author") or "unknown"))
        .replace("{created_at}", str(obs.get("sourceCreatedAt") or "unknown"))
        .replace("{url}", str(obs.get("url") or ""))
        .replace("{links}", ", ".join(obs.get("links") or []) or "none")
        .replace("{text}", str(obs.get("text") or ""))
    )


def cache_key(obs: dict, prompt_version: str, model: str) -> str:
    """Stable across runs; changes when the text, the prompt or the model changes."""
    basis = f"{obs.get('textSha256') or text_hash(obs.get('text'))}:{prompt_version}:{model}"
    return text_hash(basis) or ""


# Statuses whose extraction question is settled. `review` belongs here: a
# curator looking at an observation is not a reason to pay Gemini to read it
# again tomorrow, and every day it sat in the queue it was re-extracted.
RESOLVED_STATUSES = ("irrelevant", "extracted", "matched", "merged", "review")

# Backoff after a failed extraction, in hours. A post the model cannot parse
# today will usually still be unparseable tomorrow, and it used to cost a call
# every single run, forever. After the last step the failure is permanent and
# only a changed text, prompt or model revives it.
RETRY_BACKOFF_HOURS = (1, 6, 24, 72)


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat()


def needs_extraction(obs: dict, prompt_version: str, model: str, force: bool,
                     now: datetime | None = None) -> bool:
    if force:
        return True

    # A moved cache key means the text, the prompt or the model changed, so the
    # previous answer — success or failure — no longer speaks to this input.
    key_moved = obs.get("extractionCacheKey") != cache_key(obs, prompt_version, model)

    if obs.get("status") in RESOLVED_STATUSES:
        return key_moved

    if obs.get("status") == "extraction_failed":
        if key_moved:
            return True
        if obs.get("failureType") == "permanent":
            return False
        nxt = obs.get("nextRetryAt")
        if not nxt:
            return True
        return _iso(now or datetime.now(timezone.utc)) >= nxt

    return True


def _record_failure(obs: dict, message: str, prompt_version: str, model_name: str,
                    now: datetime | None = None) -> dict:
    """Mark a failed extraction and schedule when — or whether — to try again."""
    now = now or datetime.now(timezone.utc)
    attempts = int(obs.get("extractionAttempts") or 0) + 1

    obs = dict(obs)
    obs["status"] = "extraction_failed"
    obs["extractionError"] = message
    obs["extractionModel"] = model_name
    obs["extractionPromptVersion"] = prompt_version
    obs["extractionAttempts"] = attempts
    obs["lastAttemptAt"] = _iso(now)
    # Stored so a *changed* text or prompt is recognised as a new question
    # rather than another attempt at the old one.
    obs["extractionCacheKey"] = cache_key(obs, prompt_version, model_name)

    if attempts > len(RETRY_BACKOFF_HOURS):
        obs["failureType"] = "permanent"
        obs["nextRetryAt"] = None
    else:
        obs["failureType"] = "transient"
        obs["nextRetryAt"] = _iso(
            now + timedelta(hours=RETRY_BACKOFF_HOURS[attempts - 1])
        )
    return obs


EXCERPT_CHARS = 160


def redact_resolved(observations: list[dict], limit: int = EXCERPT_CHARS) -> list[dict]:
    """Replace full text with an excerpt once the observation is resolved.

    R10. The text of third-party posts was committed in full, indefinitely, to a
    public repository. It is needed to extract from, and after that the
    structured `extraction` payload is what everything downstream reads — so the
    full text is transient and the excerpt plus `textSha256` plus the URL is the
    durable record.

    Deliberately not applied to unresolved observations: those still have to be
    sent to the model, and truncating them first would silently degrade every
    extraction.
    """
    out = []
    for obs in observations:
        if obs.get("status") in RESOLVED_STATUSES and obs.get("text"):
            obs = dict(obs)
            text = obs["text"]
            obs["textExcerpt"] = (
                text if len(text) <= limit else text[:limit].rstrip() + "…"
            )
            obs["text"] = None
        out.append(obs)
    return out


def extract_one(
    model_client: StructuredModel,
    obs: dict,
    template: str,
    prompt_version: str,
    model_name: str,
) -> tuple[dict, str | None]:
    """Returns (updated observation, error message or None). Never raises."""
    prompt = render_prompt(template, obs)
    try:
        raw = model_client.generate_json(prompt, gemini_response_schema())
    except (SchemaViolation, GeminiError) as exc:
        return _record_failure(obs, str(exc), prompt_version, model_name), str(exc)

    try:
        result = ExtractionResult(**raw)
    except ValidationError as exc:
        message = f"schema validation failed: {exc.error_count()} error(s)"
        return _record_failure(obs, message, prompt_version, model_name), message

    verified_ids, warnings = cross_check_identifiers(
        result, obs.get("text"), obs.get("links")
    )

    payload = result.model_dump(mode="json")
    payload["externalIdentifiers"] = verified_ids      # model output never wins

    obs = dict(obs)
    obs["extraction"] = payload
    obs["extractionModel"] = model_name
    obs["extractionPromptVersion"] = prompt_version
    obs["extractionConfidence"] = result.extractionConfidence
    obs["extractionCacheKey"] = cache_key(obs, prompt_version, model_name)
    obs["extractionError"] = None
    obs["extractionAttempts"] = 0
    obs["failureType"] = None
    obs["nextRetryAt"] = None
    if warnings:
        obs["extractionWarnings"] = warnings
    # merge verified identifiers back onto the observation for matching
    merged = dict(obs.get("externalIds") or {})
    for k, v in verified_ids.items():
        merged[k] = sorted(set(merged.get(k, [])) | set(v))
    obs["externalIds"] = merged
    obs["status"] = "extracted" if result.isRelevant else "irrelevant"
    return obs, None


def run(
    dry_run: bool = False,
    model_client: StructuredModel | None = None,
    limit: int | None = None,
    force: bool = False,
) -> dict:
    cfg = json.loads((ROOT / "config" / "automation.json").read_text(encoding="utf-8"))
    ex = cfg["extraction"]
    prompt_version = ex.get("promptVersion", "extraction_v1")
    model_name = ex.get("model", "gemini-3.6-flash")
    max_calls = limit or ex.get("maxCallsPerRun", 50)

    try:
        observations = store.read_records(store.observations_path(), Observation)
    except store.CorruptStoreError as exc:
        return {"ok": False, "error": f"refusing to run: {exc}"}

    template = load_prompt(prompt_version)

    pending = [o for o in observations if needs_extraction(o, prompt_version, model_name, force)]
    todo = pending[:max_calls]
    deferred = len(pending) - len(todo)

    if model_client is None:
        if dry_run:
            from scripts.automation.gemini import StubModel

            model_client = StubModel({
                "isRelevant": False, "claimType": "unrelated",
                "resultType": "unknown", "extractionConfidence": 0.0,
                "relevanceReason": "dry-run stub — no model was called",
            })
        else:
            model_client = GeminiClient(
                model=model_name,
                timeout=ex.get("timeoutSeconds", 60),
            )

    by_id = {o["id"]: o for o in observations}
    relevant = failed = 0
    errors: list[str] = []

    for obs in todo:
        updated, err = extract_one(model_client, obs, template, prompt_version, model_name)
        by_id[updated["id"]] = updated
        if err:
            failed += 1
            errors.append(f"{obs['id']}: {err}")
        elif updated["status"] == "extracted":
            relevant += 1

    merged = sorted(by_id.values(), key=lambda o: (o.get("sourceCreatedAt") or "", o["id"]))

    summary = {
        "ok": True,
        "dryRun": dry_run,
        "model": model_name,
        "promptVersion": prompt_version,
        "observationsTotal": len(observations),
        "needingExtraction": len(pending),
        "processed": len(todo),
        "deferredByCap": deferred,
        "relevant": relevant,
        "irrelevant": len(todo) - relevant - failed,
        "failed": failed,
        "errors": errors[:10],
        "apiCalls": getattr(model_client, "call_count", 0),
    }

    if dry_run:
        summary["proposedMutations"] = {
            "observations.json": f"{len(todo)} observations would be extracted"
        }
        return summary

    store.write_records(store.observations_path(), Observation, redact_resolved(merged))

    try:
        state = ProcessingState(**store.read_json(store.state_path(), {}))
    except Exception:
        state = ProcessingState()
    state.lastRunAt = utc_now_iso()
    state.bump("extracted", relevant)
    state.bump("extractionFailed", failed)
    state.bump_api("gemini", getattr(model_client, "call_count", 0))
    store.write_json(store.state_path(), state.model_dump(mode="json"))

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract structured data from observations.")
    ap.add_argument("--dry-run", action="store_true", help="use a stub model, write nothing")
    ap.add_argument("--limit", type=int, help="override maxCallsPerRun")
    ap.add_argument("--force", action="store_true", help="re-extract even when cached")
    args = ap.parse_args()

    result = run(dry_run=args.dry_run, limit=args.limit, force=args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
