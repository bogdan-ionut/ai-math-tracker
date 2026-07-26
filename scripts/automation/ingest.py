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
from scripts.automation.query_builder import (  # noqa: E402
    API_MAX_QUERY_CHARS,
    BuiltQuery,
    build_queries,
    with_time_window,
)
from scripts.automation.urls import canonicalize_url, expand_links, tweet_url  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def load_config() -> dict:
    return json.loads((CONFIG_DIR / "automation.json").read_text(encoding="utf-8"))


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

def select_fairly(records: list[RawTweet], cap: int) -> tuple[list[RawTweet], list[RawTweet]]:
    """Take up to `cap` records, spreading them evenly across queries.

    Straight truncation of a query-ordered list is not a cap, it is a silent
    preference for whichever families happen to be built first. On a busy day
    the last families never got in at all — and because the surplus was only
    ever reported as a count, nothing showed which ones lost.

    Round-robin instead: one record from each query in turn, so a cap of 50
    across 28 queries costs every query the same. Order within a query is
    preserved, so the newest tweets survive a partial take. Everything not
    taken is returned as backlog rather than dropped.
    """
    by_query: dict[str, list[RawTweet]] = {}
    for rec in records:
        by_query.setdefault(rec.matchedQueryId, []).append(rec)

    taken: list[RawTweet] = []
    while len(taken) < cap and any(by_query.values()):
        for queue in by_query.values():
            if not queue:
                continue
            taken.append(queue.pop(0))
            if len(taken) >= cap:
                break

    deferred = [rec for queue in by_query.values() for rec in queue]
    return taken, deferred


def _combine_with_backlog(
    backlog: list[RawTweet], fresh: list[RawTweet], existing: list[dict]
) -> tuple[list[RawTweet], int]:
    """Merge carried-over records with this run's fetch.

    Two things have to be dropped, or the backlog grows without bound:

      * anything the overlapping lookback window re-fetched, which is most of
        it — the carried copy and the fresh copy are the same tweet;
      * anything already turned into an observation by an earlier run, which is
        what the backlog exists to make happen.

    Backlog first, so the oldest waiting records are the ones that get in.
    """
    done = {o.get("sourceNativeId") for o in existing}
    carried = {r.tweetId for r in backlog}
    seen: set[str] = set()
    out: list[RawTweet] = []
    for rec in [*backlog, *fresh]:
        if rec.tweetId in done or rec.tweetId in seen:
            continue
        seen.add(rec.tweetId)
        out.append(rec)
    return out, len(seen & carried)


def _load_backlog() -> list[RawTweet]:
    """Records carried from a previous run. Corruption is not fatal here — the
    backlog is an optimisation, and losing it costs API calls, not data."""
    try:
        rows = store.read_json(store.backlog_path(), [])
    except store.CorruptStoreError:
        return []
    out: list[RawTweet] = []
    for row in rows:
        try:
            out.append(RawTweet.model_validate(row))
        except ValidationError:
            continue
    return out


def run(
    dry_run: bool = False,
    fixtures: Path | None = None,
    limit: int | None = None,
    lookback_hours: int | None = None,
) -> dict:
    automation = load_config()
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
            min_interval=ing.get("minRequestIntervalSeconds", 1.5),
        )
        source = "twitterapi.io"

    # --- fetch ------------------------------------------------------------
    queries: list[BuiltQuery] = build_queries()
    raw_records: list[RawTweet] = []
    failures: list[str] = []
    telemetry: list[dict] = []

    # R2. The window goes to the server. Applying it here only, as before, meant
    # the API picked its 20 newest matches over all time and *then* we discarded
    # the ones outside the window — so a query with more than 20 all-time
    # matches could return 20 stale tweets and yield nothing, while newer
    # matching posts existed and were never asked for. `within_lookback` below
    # stays as a safety net for undated records and clock skew.
    window_start = now_dt - timedelta(hours=lookback)
    windowed = not isinstance(client, FixtureSearchClient)

    for bq in queries:
        query = (with_time_window(bq.query, window_start, now_dt)
                 if windowed else bq.query)
        if len(query) > API_MAX_QUERY_CHARS:
            # Would trip the silent-zero limit. Never send it: a query that
            # returns nothing looks exactly like a quiet day.
            failures.append(f"{bq.id}: {len(query)} chars exceeds the API limit")
            telemetry.append({"queryId": bq.id, "tier": bq.tier,
                              "error": f"over {API_MAX_QUERY_CHARS} chars"})
            continue
        try:
            tweets = client.search(query, query_type="Latest", max_pages=1)
        except TwitterApiError as exc:
            # A partial failure must never wipe good data: record and continue.
            failures.append(f"{bq.id}: {exc}")
            telemetry.append({"queryId": bq.id, "tier": bq.tier, "error": str(exc)})
            continue
        kept = 0
        for t in tweets[: bq.max_results]:
            rec = normalise_tweet(t, bq.id, now, store_text)
            if rec and within_lookback(rec, lookback, now_dt):
                raw_records.append(rec)
                kept += 1
        telemetry.append({
            "queryId": bq.id, "tier": bq.tier,
            "returned": len(tweets), "keptInWindow": kept,
            "cappedAt": bq.max_results,
        })

    # --- deduplicate (exact, by source-native id) -------------------------
    seen: dict[str, RawTweet] = {}
    first_seen_by: dict[str, str] = {}
    for rec in raw_records:
        if rec.tweetId not in seen:
            seen[rec.tweetId] = rec
            first_seen_by[rec.tweetId] = rec.matchedQueryId
    deduped = list(seen.values())

    # per-query: how many observations did this family *uniquely* surface?
    unique_by_query: dict[str, int] = {}
    for qid in first_seen_by.values():
        unique_by_query[qid] = unique_by_query.get(qid, 0) + 1
    for row in telemetry:
        row["uniqueFirstSeen"] = unique_by_query.get(row["queryId"], 0)

    # R11. `deduped[:max_obs]` took the first N in query order, so the families
    # built first always won and the ones built last were dropped whenever a day
    # was busy — a systematic bias dressed up as a cap. Selection is now
    # round-robin across queries, and the surplus is carried rather than
    # counted.
    try:
        existing = store.read_json(store.observations_path(), [])
    except store.CorruptStoreError as exc:
        return {"ok": False, "error": f"refusing to run: {exc}"}

    backlog_in = _load_backlog()
    pending, backlog_used = _combine_with_backlog(backlog_in, deduped, existing)
    capped, deferred = select_fairly(pending, max_obs)
    overflow = len(deferred)

    observations = [to_observation(r, now) for r in capped]

    # --- merge ------------------------------------------------------------
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
        "backlogConsumed": backlog_used,
        "overflowDeferred": overflow,
        "windowStart": window_start.isoformat() if windowed else None,
        "observationsAdded": added,
        "observationsUpdated": updated,
        "observationsTotal": len(merged),
        "withExternalIdentifier": with_ids,
        "apiCalls": getattr(client, "call_count", 0),
        "perQuery": telemetry,
    }

    if dry_run:
        summary["proposedMutations"] = {
            "observations.json": f"+{added} new, ~{updated} updated",
            "raw/twitter/%s.json" % today: f"{len(capped)} records",
            "ingest_backlog.json": f"{len(deferred)} carried to the next run",
        }
        return summary

    # --- persist (atomic) -------------------------------------------------
    store.write_json(store.observations_path(), merged)
    store.write_json(store.raw_path(today), [r.model_dump(mode="json") for r in capped])
    # Carry the surplus rather than dropping it. Already fetched, already paid.
    store.write_json(store.backlog_path(),
                     [r.model_dump(mode="json") for r in deferred])

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
    state.counters["queriesRun"] = len(queries)
    # keep the latest per-query telemetry so noisy families can be retired on evidence
    store.write_json(store.DATA_DIR / "query_telemetry.json",
                     {"runAt": now, "perQuery": telemetry})
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
