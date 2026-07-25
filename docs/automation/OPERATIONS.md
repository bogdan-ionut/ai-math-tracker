# Operations

How to run, inspect, pause and recover the discovery pipeline. Written for the person who
has forgotten how it works — which will be you, in three weeks.

---

## The short version

| I want to… | Do this |
|---|---|
| See what it *would* do | Actions → **Daily discovery** → Run workflow → `dry_run: true` |
| Actually run it now | Same, but `dry_run: false` |
| Read what needs a human | `data/automation/review_queue.json` |
| See which queries are earning their keep | `data/automation/query_telemetry.json` |
| Turn it off | `config/automation.json` → `schedule.enabled: false` |
| Let it start committing | `config/automation.json` → `schedule.dryRunOnSchedule: false` |

---

## Current state: dry-run by default

**The scheduled run does not write anything yet.** `schedule.dryRunOnSchedule` is `true`,
so the daily job collects, reports what it would do, and exits.

That is deliberate. The search layer deliberately admits noise (recall first), and the
measured corroboration rate on X was only 3 in 20. Before letting anything be written, run
it for a few days and read:

- the per-query telemetry — which families return nothing, or only duplicates;
- the review-queue reasons — mostly `no_corroboration` is expected and healthy.

When the numbers look sane, set `dryRunOnSchedule: false`. It is a config change, not a
code change, and it is reversible.

---

## Schedule and the DST caveat

```
cron: "20 4 * * *"   # UTC
```

GitHub Actions cron is **UTC-only** — there is no timezone field. So:

| Season | UTC | Europe/Bucharest |
|---|---|---|
| Summer (EEST, UTC+3) | 04:20 | **07:20** |
| Winter (EET, UTC+2) | 04:20 | **06:20** |

The one-hour drift across DST is documented rather than solved; nothing in the pipeline
cares what hour it runs, because the lookback window is 30 hours and deduplication is keyed
on the tweet id.

Off-the-hour on purpose: GitHub delays on-the-hour schedules under load.

> **GitHub disables scheduled workflows after 60 days of repository inactivity.** If the
> daily run stops appearing, check the Actions tab for the re-enable prompt.

---

## Workflow topology

```
discover.yml  ──commits data/automation──►  push to main  ──►  deploy-pages.yml
   (contents: write)                                              (contents: read)
```

The graph is **acyclic by construction**: `deploy-pages.yml` has no commit step, so it
cannot re-trigger the collector. No `[skip ci]` guard is needed, and a test asserts the
deploy workflow contains no `git commit` / `git push`.

`concurrency: cancel-in-progress: false` on the collector — a half-written data run must
never be killed mid-flight.

---

## What gets committed, and what does not

Only `data/automation/**`, and only when something **substantive** changed:
observations, candidates, review queue, aliases.

`processing_state.json` and `query_telemetry.json` carry `lastRunAt` / `runAt`, which move
on every single run. Committing on those would produce 365 meaningless commits a year and
bury the ones that matter, so `scripts/automation/changes.py` strips volatile keys before
comparing. Timestamps ride along when something real changed and are discarded when nothing
did.

Losing a run's counters is harmless: nothing depends on the state file having advanced —
the lookback window overlaps deliberately and deduplication is by source id.

**`data/results.json` is never committed by automation.** The workflow only ever runs
`git add data/automation`, and `policy.assert_registry_untouched` fails the run if the file
moved at all.

---

## Running manually

```bash
# everything, without writing
python -m scripts.automation.ingest     --dry-run
python -m scripts.automation.extraction --dry-run
python -m scripts.automation.pipeline   --dry-run

# for real (needs the two keys exported in your shell — never committed)
python -m scripts.automation.ingest
python -m scripts.automation.extraction
python -m scripts.automation.pipeline
```

Useful flags:

| Flag | Effect |
|---|---|
| `--limit N` | cap observations (ingest) or model calls (extract/pipeline) |
| `--lookback-hours N` | override the 30-hour window |
| `--force` | re-extract even when cached (after a prompt change) |
| `--fixtures PATH` | ingest from a file instead of the API |

Offline, no keys, no network:

```bash
python -m scripts.automation.ingest --dry-run \
  --fixtures tests/automation/fixtures/twitter_search.json --lookback-hours 999999
```

---

## Inspecting the review queue

```bash
python - <<'PY'
import json, collections
q = json.load(open("data/automation/review_queue.json"))
open_ = [e for e in q if e["status"] == "open"]
print(collections.Counter(e["reason"] for e in open_))
for e in open_[:10]:
    print(f"\n[{e['reason']}] {e['title']}\n  {e['detail']}\n  {e.get('sourceUrl')}")
PY
```

To resolve an entry, set its `status` to `resolved` or `dismissed` and commit. **A resolved
entry is never reopened** — that is what stops the queue turning into noise you stop reading.

Expected reasons, and what they mean:

| Reason | Meaning | Usually |
|---|---|---|
| `no_corroboration` | a post with no arXiv/DOI/Erdős/Lean identifier | common and healthy — this is the gate working |
| `conflicting_claim` | contradicts a recorded result | **read these first** |
| `ambiguous_identity` | matching could not tell which problem | needs a human eye |
| `judge_failed` | the model errored | re-runs next cycle |
| `identifier_conflict` | explicit identifiers disagree | never merged, by design |
| `registry_conflict` | one identifier maps to two curated records | **a data bug — fix `results.json`** |

---

## Recovering from a failed run

A failure is designed to be non-destructive; there is usually nothing to undo.

1. **API failure during ingest.** Failed queries are recorded and skipped; existing
   observations are untouched. Nothing to do — the next run picks them up, and the 30-hour
   lookback means nothing falls through the gap.
2. **Extraction failed for some observations.** They are marked `extraction_failed` and
   kept. They are retried automatically on the next run.
3. **The judge failed.** Those observations went to review as `insufficient_information`.
   Nothing was guessed.
4. **Corrupt data file.** The pipeline refuses to start (`refusing to run: … is not valid
   JSON`) rather than overwriting good data with empty data. Restore from git:
   ```bash
   git checkout HEAD -- data/automation/observations.json
   ```
5. **A bad commit landed.** Only `data/automation/**` is ever committed, so:
   ```bash
   git revert <sha>          # then push; deploy re-runs automatically
   ```
6. **The site broke.** The site only reads `public/data/*.json`, built from
   `data/results.json`. Automation cannot affect it. Re-run `deploy-pages.yml`.

---

## Turning it off

| Scope | How |
|---|---|
| Stop writing, keep observing | `schedule.dryRunOnSchedule: true` |
| Stop the pipeline entirely | `schedule.enabled: false` (the job exits at the gate) |
| Stop the workflow firing at all | Actions → Daily discovery → ⋯ → Disable workflow |
| Stop one noisy query | `config/twitter_discovery.json` → that family → `"enabled": false` |
| Stop a trusted account | same file → that account → `"enabled": false` |

None of these require a code change.

---

## Rotating secrets

Settings → Secrets and variables → Actions → update `TWITTERAPI_IO_KEY` or
`GEMINI_API_KEY`. Then run the relevant smoke test to confirm:

- **Smoke test — TwitterAPI.io connectivity**
- **Smoke test — Gemini extraction**

Both are read-only and print lengths, never values.

---

## Cost

| Item | Per day | Notes |
|---|---|---|
| TwitterAPI.io | ~14 calls | one page per query family, paced 1.5s apart |
| Gemini extraction | ≤ 50 | capped; cached on `(text, prompt, model)` — a re-run costs 0 |
| Gemini judge | ≤ 15 | only for observations matching could not resolve |

Steady state is far below the caps, because extraction is cached and most observations
resolve deterministically. The expensive day is the first real (non-dry) run.

---

## Health checks

```bash
python -m pytest                       # 230 tests, no network, no keys
python scripts/build_data.py           # curated pipeline still valid
python -m scripts.automation.calibrate # query recall against the gold set
python -m scripts.automation.changes   # would this run commit anything?
```

Live, in Actions: **Probe — TwitterAPI.io syntax and handle verification** re-checks
operator support and trusted-account handles. Worth re-running if results dry up.
