"""Sprint 1: deterministic ingestion.

fetch → normalise → deduplicate → persist. **No model is called here.**

Run:
    python -m scripts.automation.ingest --dry-run          # fixtures, writes nothing
    python -m scripts.automation.ingest                    # live, needs TWITTERAPI_IO_KEY

Idempotency contract: running this twice over the same window creates zero new
observations, because ids are derived from the source-native tweet id.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation import store  # noqa: E402
from scripts.automation.identifiers import extract_identifiers  # noqa: E402
from scripts.automation.ids import observation_id, text_hash  # noqa: E402
from scripts.automation.models import (  # noqa: E402
    Observation,
    ProcessingState,
    RawTweet,
    utc_now_iso,
)
from scripts.automation.twitter import (  # noqa: E402
    FixtureSearchClient,
    TwitterApiClient,
    TwitterApiError,
)
from scripts.automation.urls import canonicalize_url, expand_links, tweet_url  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def load_config() -> tuple[dict, dict]:
    automation = json.loads((CONFIG_DIR / "automation.json").read_text(encoding="utf-8"))
    queries = json.loads((CONFIG_DIR / "twitter_queries.json").read_text(encoding="utf-8"))
    return automation, queries


def enabled_queries(qcfg: dict) -> list[tuple[str, str]]:
    """Return (query_id, query_string) pairs, including per-account queries."""
    defaults = qcfg.get("defaults", {})
    out: list[tuple[str, str]] = []
    for q in qcfg.get("queries", []):
        if q.get("enabled", defaults.get("enabled", True)):
            out.append((q["id"], q["query"]))
    accounts = qcfg.get("accounts") or {}
    if accounts.get("enabled"):
        tpl = accounts.get("queryTemplate", "from:{handle}")
        for handle in accounts.get("handles", []):
            out.append((f"account-{handle}", tpl.format(handle=handle)))
    return out


# --------------------------------------------------------------------------
# normalisation
# --------------------------------------------------------------------------

def _author(tweet: dict) -> tuple[str | None, str | None]:
    a = tweet.get("author") or {}
    if not isinstance(a, dict):
        return None, None
    return a.get("userName") or a.get("screen_name"), a.get("name")


def normalise_tweet(tweet: dict, query_id: str, collected_at: str, store_text: bool) -> RawTweet | None:
    """Convert one API tweet dict into our minimal record.

    Retweets are attributed to the *original* tweet id, so an RT and the tweet it
    quotes deduplicate onto a single observation rather than becoming two.
    """
    tid = str(tweet.get("id") or "").strip()
    if not tid:
        return None

    retweeted = tweet.get("retweeted_tweet") if isinstance(tweet.get("retweeted_tweet"), dict) else None
    quoted = tweet.get("quoted_tweet") if isinstance(tweet.get("quoted_tweet"), dict) else None

    effective = retweeted or tweet          # follow retweets to the source
    eid = str(effective.get("id") or tid)

    handle, name = _author(effective)
    text = effective.get("text") or ""
    links = expand_links(effective.get("entities"))

    url = canonicalize_url(effective.get("url")) or tweet_url(handle, eid)

    engagement = {
        k: int(effective.get(src) or 0)
        for k, src in (
            ("likes", "likeCount"),
            ("retweets", "retweetCount"),
            ("replies", "replyCount"),
            ("quotes", "quoteCount"),
            ("views", "viewCount"),
        )
        if isinstance(effective.get(src), (int, float))
    }

    return RawTweet(
        tweetId=eid,
        url=url,
        authorHandle=handle,
        authorName=name,
        createdAt=effective.get("createdAt"),
        collectedAt=collected_at,
        matchedQueryId=query_id,
        text=text if store_text else None,
        textSha256=text_hash(text),
        links=links,
        engagement=engagement,
        isRetweet=bool(retweeted),
        isQuote=bool(quoted),
        referencedTweetId=str(quoted.get("id")) if quoted and quoted.get("id") else None,
        conversationId=str(effective.get("conversationId")) if effective.get("conversationId") else None,
    )


def to_observation(raw: RawTweet, now: str) -> Observation:
    ext = extract_identifiers(raw.text, raw.links)
    return Observation(
        id=observation_id("twitter", raw.tweetId),
        sourceType="twitter",
        sourceNativeId=raw.tweetId,
        url=raw.url,
        author=raw.authorHandle,
        sourceCreatedAt=raw.createdAt,
        collectedAt=raw.collectedAt,
        lastSeenAt=now,
        matchedQueryIds=[raw.matchedQueryId],
        text=raw.text,
        textSha256=raw.textSha256,
        links=raw.links,
        externalIds={k: v for k, v in ext.to_dict().items() if v},
        status="new",
    )


def within_lookback(raw: RawTweet, hours: int, now: datetime) -> bool:
    """Keep tweets inside the lookback window; keep anything undated (fail open)."""
    if not raw.createdAt:
        return True
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            when = datetime.strptime(raw.createdAt, fmt)
            return when >= now - timedelta(hours=hours)
        except ValueError:
            continue
    return True


# --------------------------------------------------------------------------
# merge into the store
# --------------------------------------------------------------------------

def merge_observations(existing: list[dict], fresh: list[Observation], now: str) -> tuple[list[dict], int, int]:
    """Insert new observations; for ones already known, refresh non-editorial
    metadata only. Returns (merged, added, updated)."""
    by_id = {o["id"]: dict(o) for o in existing}
    added = updated = 0

    for obs in fresh:
        if obs.id in by_id:
            prev = by_id[obs.id]
            before = json.dumps(prev, sort_keys=True)
            prev["lastSeenAt"] = now
            qids = sorted(set(prev.get("matchedQueryIds", [])) | set(obs.matchedQueryIds))
            prev["matchedQueryIds"] = qids
            # links/identifiers can only grow — never drop what we saw before
            prev["links"] = sorted(set(prev.get("links", [])) | set(obs.links))
            merged_ext = dict(prev.get("externalIds") or {})
            for k, v in (obs.externalIds or {}).items():
                merged_ext[k] = sorted(set(merged_ext.get(k, [])) | set(v))
            prev["externalIds"] = merged_ext
            if json.dumps(prev, sort_keys=True) != before:
                updated += 1
            by_id[obs.id] = prev
        else:
            by_id[obs.id] = obs.model_dump(mode="json")
            added += 1

    merged = sorted(by_id.values(), key=lambda o: (o.get("sourceCreatedAt") or "", o["id"]))
    return merged, added, updated


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def run(
    dry_run: bool = False,
    fixtures: Path | None = None,
    limit: int | None = None,
    lookback_hours: int | None = None,
) -> dict:
    automation, qcfg = load_config()
    ing = automation["ingestion"]
    now_dt = datetime.now(timezone.utc)
    now = utc_now_iso()
    today = now_dt.date().isoformat()

    max_obs = limit or ing.get("maxObservationsPerRun", 50)
    lookback = lookback_hours if lookback_hours is not None else ing.get("lookbackHours", 30)
    store_text = ing.get("storeTweetText", True)

    # --- client -----------------------------------------------------------
    if fixtures:
        payload = json.loads(Path(fixtures).read_text(encoding="utf-8"))
        client = FixtureSearchClient(default=payload.get("tweets", []))
        source = f"fixtures:{Path(fixtures).name}"
    else:
        client = TwitterApiClient(
            timeout=ing.get("httpTimeoutSeconds", 20),
            max_retries=ing.get("maxRetries", 3),
            backoff=ing.get("retryBackoffSeconds", 2.0),
        )
        source = "twitterapi.io"

    # --- fetch ------------------------------------------------------------
    queries = enabled_queries(qcfg)
    raw_records: list[RawTweet] = []
    failures: list[str] = []
    qtype = qcfg.get("defaults", {}).get("queryType", "Latest")
    pages = qcfg.get("defaults", {}).get("maxPagesPerQuery", 1)

    for qid, qstr in queries:
        try:
            tweets = client.search(qstr, query_type=qtype, max_pages=pages)
        except TwitterApiError as exc:
            # A partial failure must never wipe good data: record and continue.
            failures.append(f"{qid}: {exc}")
            continue
        for t in tweets:
            rec = normalise_tweet(t, qid, now, store_text)
            if rec and within_lookback(rec, lookback, now_dt):
                raw_records.append(rec)

    # --- deduplicate (exact, by source-native id) -------------------------
    seen: dict[str, RawTweet] = {}
    for rec in raw_records:
        if rec.tweetId not in seen:
            seen[rec.tweetId] = rec
    deduped = list(seen.values())

    capped = deduped[:max_obs]
    overflow = len(deduped) - len(capped)

    observations = [to_observation(r, now) for r in capped]

    # --- merge ------------------------------------------------------------
    try:
        existing = store.read_json(store.observations_path(), [])
    except store.CorruptStoreError as exc:
        return {"ok": False, "error": f"refusing to run: {exc}"}

    merged, added, updated = merge_observations(existing, observations, now)

    with_ids = sum(1 for o in observations if o.has_external_identifier())
    summary = {
        "ok": True,
        "lookbackHours": lookback,
        "dryRun": dry_run,
        "source": source,
        "queriesRun": len(queries),
        "queryFailures": failures,
        "tweetsFetched": len(raw_records),
        "afterDedupe": len(deduped),
        "processed": len(capped),
        "overflowDeferred": overflow,
        "observationsAdded": added,
        "observationsUpdated": updated,
        "observationsTotal": len(merged),
        "withExternalIdentifier": with_ids,
        "apiCalls": getattr(client, "call_count", 0),
    }

    if dry_run:
        summary["proposedMutations"] = {
            "observations.json": f"+{added} new, ~{updated} updated",
            "raw/twitter/%s.json" % today: f"{len(capped)} records",
        }
        return summary

    # --- persist (atomic) -------------------------------------------------
    store.write_json(store.observations_path(), merged)
    store.write_json(store.raw_path(today), [r.model_dump(mode="json") for r in capped])

    removed = store.prune_raw(automation.get("rawRetention", {}).get("keepDays", 30), today)
    summary["rawPruned"] = removed

    try:
        state = ProcessingState(**store.read_json(store.state_path(), {}))
    except (store.CorruptStoreError, ValidationError):
        state = ProcessingState()
    state.lastRunAt = now
    state.lastRunStatus = "partial" if failures else "ok"
    if not failures:
        state.lastSuccessfulRunAt = now
    state.bump("observationsAdded", added)
    state.bump("runs")
    state.bump_api("twitter", getattr(client, "call_count", 0))
    state.notes = failures[:10]
    store.write_json(store.state_path(), state.model_dump(mode="json"))

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest AI-mathematics signals from X.")
    ap.add_argument("--dry-run", action="store_true", help="report proposed mutations, write nothing")
    ap.add_argument("--fixtures", type=Path, help="read tweets from a fixture file instead of the API")
    ap.add_argument("--limit", type=int, help="override maxObservationsPerRun")
    ap.add_argument("--lookback-hours", type=int, help="override lookbackHours")
    args = ap.parse_args()

    result = run(
        dry_run=args.dry_run,
        fixtures=args.fixtures,
        limit=args.limit,
        lookback_hours=args.lookback_hours,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
