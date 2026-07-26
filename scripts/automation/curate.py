"""Sprint 6.5 — the curator's workbench (R8).

    python -m scripts.automation.curate queue          # what needs a human
    python -m scripts.automation.curate candidates     # what automation proposes
    python -m scripts.automation.curate show <id>      # one item, in full
    python -m scripts.automation.curate promote <id>   # → a draft pull request
    python -m scripts.automation.curate dismiss <id> --why "..."

**Why this exists.** Automation has been filling a review queue and a candidate
store for several sprints with no way to act on either except editing JSON by
hand. A queue nobody can work is a queue nobody works.

**Why `promote` opens a pull request rather than writing the registry.** The
single strongest guarantee this project makes is that `data/results.json` is
never written by automation. A curator command that edited it directly would
technically be a human action, but it would put registry-writing code in the
automation package, one import away from the scheduled workflow — and the
guarantee would then rest on nobody ever calling it. Instead `promote` writes a
proposed record on a branch and opens a **draft** PR, so the change arrives
through review like any other.

**What a proposal deliberately leaves empty.** Every field in
`neverAutoWriteFields` — `status` beyond the weakest tier, `auditedAt`,
`impact`, `assessment`, `confidence`, `auditNotes`, `provenanceNote` — is a
judgement, not a fact automation collected. They come out as `null` with a
checklist in the PR body. A promoted candidate enters as `provisional`: the
tracker's whole claim to honesty is that an announcement is not a confirmation.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation import store  # noqa: E402
from scripts.automation.policy import evidence_tier, load_policy, never_auto_write  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "data" / "results.json"

# The weakest tier the schema allows. A promotion is a proposal, not a finding.
INITIAL_STATUS = "provisional"


class CurateError(RuntimeError):
    pass


# -------------------------------------------------------------- reading

def _load(path: Path) -> list[dict]:
    try:
        return store.read_json(path, [])
    except store.CorruptStoreError as exc:
        raise CurateError(str(exc)) from exc


def open_queue() -> list[dict]:
    return [r for r in _load(store.review_queue_path())
            if r.get("status", "open") == "open"]


def pending_candidates() -> list[dict]:
    return [c for c in _load(store.candidates_path())
            if c.get("status", "pending") == "pending"]


def _find(item_id: str) -> tuple[str, dict]:
    for kind, rows in (("candidate", _load(store.candidates_path())),
                       ("review", _load(store.review_queue_path()))):
        for row in rows:
            if row.get("id") == item_id:
                return kind, row
    raise CurateError(f"no candidate or review entry with id {item_id!r}")


# -------------------------------------------------------------- proposing

def _observations_for(cand: dict) -> list[dict]:
    wanted = set(cand.get("observationIds") or [])
    return [o for o in _load(store.observations_path()) if o.get("id") in wanted]


def propose_record(cand: dict, observations: list[dict] | None = None) -> dict:
    """Build the registry record a curator would be proposing.

    Only fields automation actually observed are filled. The judgements are left
    null on purpose — a proposal that arrived pre-filled with an impact score
    and an assessment would be inviting a rubber stamp.
    """
    observations = observations if observations is not None else _observations_for(cand)
    claims = cand.get("claims") or []
    first = claims[0] if claims else {}
    ext = cand.get("externalIds") or {}

    erdos = (ext.get("erdos") or [None])[0]
    sources = sorted({s for s in (cand.get("sources") or []) if s})

    record = {
        "id": _propose_id(cand, ext),
        "title": cand.get("canonicalName") or cand["id"],
        "family": cand.get("family") or "Uncategorised",
        "description": first.get("summary") or cand.get("canonicalName") or "",
        "resultType": first.get("resultType") or "unknown",
        "status": INITIAL_STATUS,
        "claimedAt": first.get("claimedAt") or _earliest_seen(cand, observations),
        "auditedAt": None,
        "lab": first.get("organization"),
        "labKey": None,
        "model": first.get("modelName"),
        "count": 1,
        "members": None,
        "isOpenProblem": True,
        "yearsOpen": None,
        "erdosNumber": f"#{erdos}" if erdos else None,
        "sources": sources,
        "confidence": None,
        "auditNotes": None,
        "impact": None,
        "assessment": None,
        "resolution": None,
        "provenanceNote": None,
        "externalIds": ext,
        "aliases": sorted({a for a in (cand.get("aliases") or []) if a}),
    }
    return record


def _propose_id(cand: dict, ext: dict) -> str:
    erdos = (ext.get("erdos") or [None])[0]
    if erdos:
        return f"erdos-{erdos}"
    name = (cand.get("canonicalName") or cand["id"]).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", name).strip("-")[:48]
    return slug or cand["id"]


def _earliest_seen(cand: dict, observations: list[dict]) -> str | None:
    dates = [o.get("sourceCreatedAt") for o in observations if o.get("sourceCreatedAt")]
    return (cand.get("firstSeenAt") or (min(dates) if dates else None) or "")[:10] or None


def unresolved_fields(record: dict) -> list[str]:
    """Which judgements the curator still owes, in the order the PR asks for them."""
    protected = never_auto_write()
    owed = [f for f in ("status", "confidence", "impact", "assessment",
                        "auditNotes", "provenanceNote", "auditedAt")
            if f in protected and record.get(f) in (None, "", INITIAL_STATUS)]
    if not record.get("resolution"):
        owed.append("resolution")
    return owed


def _duplicate_of(record: dict) -> str | None:
    """Does the registry already carry this problem?"""
    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ext = record.get("externalIds") or {}
    for existing in registry:
        if existing.get("id") == record["id"]:
            return existing["id"]
        for kind, values in ext.items():
            if set(values) & set((existing.get("externalIds") or {}).get(kind) or []):
                return existing["id"]
    return None


# -------------------------------------------------------------- the PR

def pr_body(cand: dict, record: dict, observations: list[dict]) -> str:
    owed = unresolved_fields(record)
    tier = max((evidence_tier(o) for o in observations), default="none") \
        if observations else "none"
    lines = [
        f"Proposes **{record['title']}** from automated candidate `{cand['id']}`.",
        "",
        "This is a **draft**. Automation collected the facts below; the",
        "judgements are deliberately empty, because a proposal that arrived",
        "pre-filled with an impact score would be inviting a rubber stamp.",
        "",
        "## What was observed",
        "",
        f"- evidence tier: **{tier}**",
        f"- identifiers: `{json.dumps(record.get('externalIds') or {})}`",
        f"- observations: {len(cand.get('observationIds') or [])}",
        f"- claims: {len(cand.get('claims') or [])}",
        f"- first seen: {cand.get('firstSeenAt')}",
        "",
        "### Sources",
        "",
    ]
    lines += [f"- {s}" for s in record.get("sources") or ["_none recorded_"]]
    lines += [
        "",
        "## Before merging, decide",
        "",
    ]
    lines += [f"- [ ] `{f}`" for f in owed]
    lines += [
        "",
        f"`status` enters as `{INITIAL_STATUS}`. Promoting it to `audited` requires",
        "a paper, a Lean artifact, or expert confirmation — and `auditedAt` set.",
        "An announcement is not a confirmation.",
    ]
    dup = _duplicate_of(record)
    if dup:
        lines[0:0] = [f"> **Possible duplicate of `{dup}`** — check before merging.", ""]
    return "\n".join(lines)


def _git(*args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=False)
    if check and proc.returncode != 0:
        raise CurateError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def promote(candidate_id: str, *, dry_run: bool = False) -> dict:
    """Propose a candidate for the registry, as a draft pull request."""
    kind, cand = _find(candidate_id)
    if kind != "candidate":
        raise CurateError(f"{candidate_id!r} is a review entry, not a candidate")

    observations = _observations_for(cand)
    record = propose_record(cand, observations)
    body = pr_body(cand, record, observations)
    branch = f"promote/{record['id']}"

    plan = {
        "candidate": cand["id"],
        "record": record,
        "branch": branch,
        "unresolvedFields": unresolved_fields(record),
        "possibleDuplicateOf": _duplicate_of(record),
        "prBody": body,
        "dryRun": dry_run,
    }
    if dry_run:
        return plan

    if _git("status", "--porcelain"):
        raise CurateError(
            "the working tree has uncommitted changes; commit or stash them first "
            "— a promotion must be reviewable on its own"
        )

    base = _git("rev-parse", "--abbrev-ref", "HEAD")
    _git("checkout", "-b", branch)
    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        registry.append(record)
        REGISTRY.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _git("add", str(REGISTRY.relative_to(ROOT)))
        _git("commit", "-m", f"Propose {record['title']} ({record['id']}) as provisional")
        _git("push", "-u", "origin", branch)
        subprocess.run(
            ["gh", "pr", "create", "--draft", "--base", base, "--head", branch,
             "--title", f"Propose {record['title']} as provisional", "--body", body],
            cwd=ROOT, check=True,
        )
    finally:
        _git("checkout", base, check=False)
    plan["opened"] = True
    return plan


def dismiss(review_id: str, why: str) -> dict:
    """Close a review entry. Only the queue is touched — never the registry."""
    rows = _load(store.review_queue_path())
    for row in rows:
        if row.get("id") == review_id:
            if row.get("status") == "resolved":
                raise CurateError(f"{review_id!r} is already resolved")
            row["status"] = "resolved"
            row["resolution"] = why
            store.write_json(store.review_queue_path(), rows)
            return {"id": review_id, "status": "resolved", "resolution": why}
    raise CurateError(f"no review entry with id {review_id!r}")


# -------------------------------------------------------------- display

def _print_queue() -> None:
    rows = open_queue()
    if not rows:
        print("review queue is empty")
        return
    by_reason: dict[str, list[dict]] = {}
    for r in rows:
        by_reason.setdefault(r.get("reason", "?"), []).append(r)
    print(f"{len(rows)} open\n")
    for reason, group in sorted(by_reason.items()):
        print(f"── {reason} ({len(group)})")
        for r in group[:10]:
            print(f"     {r['id']}  {(r.get('detail') or '')[:80]}")
        if len(group) > 10:
            print(f"     … and {len(group) - 10} more")
        print()


def _print_candidates() -> None:
    rows = pending_candidates()
    if not rows:
        print("no pending candidates")
        return
    print(f"{len(rows)} pending\n")
    for c in rows:
        obs = _observations_for(c)
        tier = max((evidence_tier(o) for o in obs), default="none") if obs else "none"
        linked = c.get("problemRef") or "—"
        print(f"  {c['id']:<34} {tier:<11} obs={len(c.get('observationIds') or []):<3} "
              f"ref={linked}")
        print(f"     {(c.get('canonicalName') or '')[:88]}")


def _print_show(item_id: str) -> None:
    kind, row = _find(item_id)
    print(f"── {kind}: {item_id}\n")
    print(json.dumps(row, indent=2, ensure_ascii=False))
    if kind == "candidate":
        record = propose_record(row)
        print("\n── would propose\n")
        print(json.dumps(record, indent=2, ensure_ascii=False))
        print(f"\n   curator still owes: {', '.join(unresolved_fields(record))}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="curate", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("queue", help="open review-queue entries")
    sub.add_parser("candidates", help="pending candidates")
    p_show = sub.add_parser("show", help="one candidate or review entry, in full")
    p_show.add_argument("id")
    p_promote = sub.add_parser("promote", help="propose a candidate as a draft PR")
    p_promote.add_argument("id")
    p_promote.add_argument("--dry-run", action="store_true",
                           help="print the proposal without branching or pushing")
    p_dismiss = sub.add_parser("dismiss", help="resolve a review entry")
    p_dismiss.add_argument("id")
    p_dismiss.add_argument("--why", required=True, help="why it needed no action")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "queue":
            _print_queue()
        elif args.cmd == "candidates":
            _print_candidates()
        elif args.cmd == "show":
            _print_show(args.id)
        elif args.cmd == "promote":
            plan = promote(args.id, dry_run=args.dry_run)
            if args.dry_run:
                print(json.dumps(plan["record"], indent=2, ensure_ascii=False))
                print("\n── pull-request body\n")
                print(plan["prBody"])
            else:
                print(f"draft PR opened from {plan['branch']}")
        elif args.cmd == "dismiss":
            print(json.dumps(dismiss(args.id, args.why), indent=2))
    except CurateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
