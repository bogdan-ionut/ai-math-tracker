"""Sprint 6 — check the references before trusting them.

    python -m scripts.automation.verify_refs --dry-run   # fixtures, writes nothing
    python -m scripts.automation.verify_refs             # live, no API key needed

An observation earns `published` — our strongest evidence tier — because its
text contained something shaped like an arXiv id. This resolves those ids
against arXiv and records what came back.

Three outcomes, and the middle one is the reason this exists:

  resolved     a real preprint; title, date and authors are stored so a curator
               has something to judge with
  unresolved   the id does not exist. A mis-transcription, a hallucinated
               reference, or a number that merely looked like one — and until
               now it counted as our best evidence
  unchecked    we could not ask (network, or arXiv was unwell). Deliberately
               distinct from `unresolved`: not knowing is not a finding, a
               distinction this project has had to relearn twice already

Only the verification fields are written. Nothing here touches the curated
registry, and an unresolved reference is *recorded*, never deleted — the claim
that someone posted that id remains true and auditable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation import store  # noqa: E402
from scripts.automation.arxiv import (  # noqa: E402
    ArxivClient,
    ArxivError,
    ArxivSource,
    FixtureArxivClient,
    normalise,
)
from scripts.automation.models import Observation, utc_now_iso  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

RESOLVED, UNRESOLVED, UNCHECKED = "resolved", "unresolved", "unchecked"


def claimed_ids(obs: dict) -> list[str]:
    return [normalise(i) for i in ((obs.get("externalIds") or {}).get("arxiv") or [])]


def needs_check(obs: dict) -> bool:
    """Check anything with a claimed id we have not already resolved.

    `unchecked` is retried — it means we never got an answer. `unresolved` is
    not: arXiv does not grow new papers under old ids, so re-asking is a request
    we already know the answer to.
    """
    if not claimed_ids(obs):
        return False
    refs = obs.get("references") or {}
    known = {r.get("status") for r in refs.get("arxiv", [])}
    if not known:
        return True
    return UNCHECKED in known


def title_affinity(obs: dict, paper) -> float | None:
    """How much the paper's title looks like the problem the post claimed.

    A **hint for the curator, not a verdict.** Resolving an id proves a preprint
    exists, not that it is the one being talked about — a live check found
    `2607.16401` resolving perfectly to *"Apple-π: Benchmarking Thinking with
    Video"*, which is a real paper and has nothing to do with the Erdős problem
    it was cited for. Existence and relevance are different questions, and only
    the first one can be answered mechanically.

    So this is recorded and shown, never acted on: nothing downgrades or
    discards a reference because the score is low.
    """
    from rapidfuzz import fuzz

    name = ((obs.get("extraction") or {}).get("canonicalProblemName") or "").strip()
    if not name or not paper or not paper.title:
        return None
    return round(fuzz.token_set_ratio(name.lower(), paper.title.lower()) / 100.0, 2)


def verify_one(obs: dict, resolved: dict, now: str) -> dict:
    """Attach verification results to one observation."""
    entries = []
    for arxiv_id in claimed_ids(obs):
        if arxiv_id not in resolved:
            entries.append({"id": arxiv_id, "status": UNCHECKED, "checkedAt": now,
                            "paper": None})
            continue
        paper = resolved[arxiv_id]
        entries.append({
            "id": arxiv_id,
            "status": RESOLVED if paper else UNRESOLVED,
            "checkedAt": now,
            "paper": paper.to_dict() if paper else None,
            # A hint, never a gate. See title_affinity.
            "titleAffinity": title_affinity(obs, paper),
        })

    obs = dict(obs)
    refs = dict(obs.get("references") or {})
    refs["arxiv"] = entries
    obs["references"] = refs
    return obs


def verified_tier(obs: dict) -> str:
    """The evidence tier this observation has actually *earned*.

    `published` requires a reference that resolved. An id that turned out not to
    exist cannot be the reason we call something published — that is exactly the
    overstatement this stage exists to prevent. It falls back to whatever the
    remaining identifiers support.
    """
    from scripts.automation.policy import EVIDENCE_TIERS, TIER_ORDER

    ids = dict(obs.get("externalIds") or {})
    entries = (obs.get("references") or {}).get("arxiv") or []
    if entries and not any(e.get("status") == RESOLVED for e in entries):
        # Every claimed arXiv id failed to resolve, or none was checked.
        ids = {k: v for k, v in ids.items() if k != "arxiv"}

    for tier in TIER_ORDER[:-1]:
        if any(ids.get(k) for k in EVIDENCE_TIERS[tier]):
            return tier
    return "none"


def run(dry_run: bool = False, client: ArxivSource | None = None,
        limit: int | None = None) -> dict:
    now = utc_now_iso()
    try:
        observations = store.read_records(store.observations_path(), Observation)
    except (store.CorruptStoreError, store.ContractError) as exc:
        return {"ok": False, "error": str(exc)}

    pending = [o for o in observations if needs_check(o)]
    todo = pending[:limit] if limit else pending

    if client is None:
        client = FixtureArxivClient() if dry_run else ArxivClient()

    wanted = sorted({i for o in todo for i in claimed_ids(o)})
    resolved: dict = {}
    error: str | None = None
    if wanted:
        try:
            resolved = client.fetch(wanted)
        except ArxivError as exc:
            # Leave every entry `unchecked`. Not knowing is not a finding.
            error = str(exc)

    by_id = {o["id"]: o for o in observations}
    counts = {RESOLVED: 0, UNRESOLVED: 0, UNCHECKED: 0}
    downgraded: list[str] = []
    # Resolved, but the paper's title looks nothing like the claimed problem.
    # Surfaced for a curator rather than acted on.
    low_affinity: list[str] = []

    for obs in todo:
        before = _tier_before(obs)
        updated = verify_one(obs, resolved, now)
        for entry in updated["references"]["arxiv"]:
            counts[entry["status"]] += 1
            affinity = entry.get("titleAffinity")
            if entry["status"] == RESOLVED and affinity is not None and affinity < 0.4:
                low_affinity.append(
                    f"{obs['id']} cites {entry['id']} "
                    f"({entry['paper']['title'][:60]!r}) — affinity {affinity}"
                )
        after = verified_tier(updated)
        if after != before:
            downgraded.append(f"{obs['id']}: {before} → {after}")
        by_id[obs["id"]] = updated

    merged = sorted(by_id.values(),
                    key=lambda o: (o.get("sourceCreatedAt") or "", o["id"]))
    summary = {
        "ok": True, "dryRun": dry_run,
        "observationsTotal": len(observations),
        "needingCheck": len(pending), "checked": len(todo),
        "referencesResolved": counts[RESOLVED],
        "referencesUnresolved": counts[UNRESOLVED],
        "referencesUnchecked": counts[UNCHECKED],
        "tierDowngrades": downgraded,
        "lowAffinityResolved": low_affinity,
        "apiCalls": getattr(client, "call_count", 0),
        "error": error,
    }
    if dry_run:
        summary["proposedMutations"] = {
            "observations.json": f"~{len(todo)} verified",
        }
        return summary

    store.write_records(store.observations_path(), Observation, merged)
    return summary


def _tier_before(obs: dict) -> str:
    from scripts.automation.policy import evidence_tier
    return evidence_tier(obs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="offline fixture client; writes nothing")
    ap.add_argument("--limit", type=int, help="cap observations checked this run")
    args = ap.parse_args()

    result = run(dry_run=args.dry_run, limit=args.limit)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
