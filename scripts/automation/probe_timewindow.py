"""R2 — does TwitterAPI.io actually honour a server-side time window?

Today the lookback is applied *after* the API has already chosen its 20 results,
so a query with more than 20 all-time matches can return 20 tweets that are all
older than the window and yield nothing — while newer matching posts exist and
are never requested. The window has to move server-side.

The existing syntax probe recorded `since:YYYY-MM-DD` as supported on the
evidence that it "returned 20 results". That is not evidence of filtering: an
operator the backend silently ignores also returns 20 results. Given that this
API's characteristic failure mode is *silently doing nothing*, an ignored
operator is the likelier hazard, and the fix would be worse than the bug — we
would trust a window that is not being applied.

So each candidate is checked three ways:

  filters   — with a window in the far past, are the returned dates inside it?
  excludes  — with a window in the future, does it return nothing?
  ignored   — if the future window still returns tweets, the operator is a no-op

`since:`/`until:` take dates (day precision); `since_time:`/`until_time:` take
unix seconds and would let a 30-hour lookback be expressed exactly.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.twitter import TwitterApiClient, TwitterApiError  # noqa: E402

OUT = Path("timewindow_probe.json")
BASE = "(AI OR LLM) (theorem OR conjecture) lang:en -filter:retweets"


def tweet_time(t: dict) -> datetime | None:
    raw = t.get("createdAt") or t.get("created_at")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None


def check(client: TwitterApiClient, label: str, query: str,
          lo: datetime | None, hi: datetime | None) -> dict:
    """Run one windowed query and report whether the dates obey the window."""
    try:
        tweets = client.search(query, max_pages=1)
    except TwitterApiError as exc:
        print(f"  {label:<34} ERROR {exc}")
        return {"label": label, "error": str(exc)}

    dates = [d for d in (tweet_time(t) for t in tweets) if d]
    inside = [d for d in dates
              if (lo is None or d >= lo) and (hi is None or d <= hi)]
    row = {
        "label": label, "query": query, "returned": len(tweets),
        "dated": len(dates), "inside": len(inside),
        "oldest": min(dates).isoformat() if dates else None,
        "newest": max(dates).isoformat() if dates else None,
    }
    verdict = ("no results" if not tweets
               else "ALL inside" if dates and len(inside) == len(dates)
               else f"{len(inside)}/{len(dates)} inside")
    print(f"  {label:<34} {len(tweets):>3} tweets   {verdict}")
    if dates:
        print(f"       {min(dates):%Y-%m-%d %H:%M} … {max(dates):%Y-%m-%d %H:%M}")
    return row


def main() -> int:
    client = TwitterApiClient(timeout=25, max_retries=3, min_interval=2.0)
    now = datetime.now(timezone.utc)
    report: dict[str, dict] = {}

    # A window in the past that certainly contains matching posts.
    past_lo, past_hi = now - timedelta(days=6), now - timedelta(days=4)
    # A window that cannot contain anything. Anything returned means the
    # operator was ignored.
    fut_lo, fut_hi = now + timedelta(days=30), now + timedelta(days=40)

    forms = {
        "date": (
            lambda lo, hi: f"{BASE} since:{lo:%Y-%m-%d} until:{hi:%Y-%m-%d}",
            "since:/until: — day precision",
        ),
        "unix": (
            lambda lo, hi: (f"{BASE} since_time:{int(lo.timestamp())} "
                            f"until_time:{int(hi.timestamp())}"),
            "since_time:/until_time: — second precision",
        ),
    }

    print("── Baseline (no window)\n")
    report["baseline"] = check(client, "no window", BASE, None, None)

    for key, (build, desc) in forms.items():
        print(f"\n── {desc}\n")
        q_past = build(past_lo, past_hi)
        report[f"{key}_past"] = check(client, f"{key}: window 6–4 days ago",
                                      q_past, past_lo, past_hi)
        q_fut = build(fut_lo, fut_hi)
        report[f"{key}_future"] = check(client, f"{key}: window 30–40 days ahead",
                                        q_fut, fut_lo, fut_hi)
        print(f"       (+{len(q_past) - len(BASE)} chars against the 512 limit)")
        report[f"{key}_cost"] = {"extraChars": len(q_past) - len(BASE)}

    print("\n── Verdict\n")
    usable = []
    for key, (_, desc) in forms.items():
        past, fut = report.get(f"{key}_past", {}), report.get(f"{key}_future", {})
        if past.get("error") or fut.get("error"):
            print(f"  {key:<6} unusable — request failed")
            continue
        ignored = fut.get("returned", 0) > 0
        filtered = past.get("dated", 0) > 0 and past["inside"] == past["dated"]
        if ignored:
            print(f"  {key:<6} ✗ IGNORED — a window 30 days in the future still "
                  f"returned {fut['returned']} tweets")
        elif filtered:
            print(f"  {key:<6} ✓ honoured — past window returned only in-window "
                  f"dates, future window returned nothing "
                  f"(+{report[f'{key}_cost']['extraChars']} chars)")
            usable.append(key)
        elif past.get("returned", 0) == 0:
            print(f"  {key:<6} ? inconclusive — future window empty (good) but the "
                  f"past window returned nothing either")
        else:
            print(f"  {key:<6} ✗ dates fall outside the requested window "
                  f"({past['inside']}/{past['dated']})")

    if usable:
        best = "unix" if "unix" in usable else usable[0]
        print(f"\n  Use {best}. A 30-hour lookback needs second precision to be "
              f"expressed exactly; day precision over-fetches by up to 24 hours.")
    else:
        print("\n  No server-side window is usable — the client-side filter stays "
              "the only defence, and R2 cannot be fixed as planned.")

    report["usable"] = {"forms": usable}
    OUT.write_text(json.dumps(report, indent=2))
    print(f"\n  api calls: {client.call_count}   report: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
