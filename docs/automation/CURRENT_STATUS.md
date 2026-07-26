# Current status — automation implementation log

> Living document, updated by hand as work proceeds. **Deliberately not written by the
> scheduled workflow** — machine state lives in `data/automation/processing_state.json`, so
> this file never accumulates meaningless daily diffs.

**Last updated:** 2026-07-26
**Phase:** executing the revised plan
**Next sprint:** 5.5 — Real no-write end-to-end → gate to live writes
**Live writes:** 🔴 **disabled** (`dryRunOnSchedule: true`) — gate is Sprint 5.5

---

## Where the project is

Sprints 0–5 are delivered: ingestion, extraction, matching, the merge engine with its
guardrails, and a scheduled workflow. 232 tests pass with no network and no API keys, and
`data/results.json` has never been written by automation.

An external review then assessed the pipeline before enabling live writes. **All 15 of its
claims were verified against the code and all 15 are accurate.** A follow-up five-lens audit
found four further defects, all in the judge stage, that neither the review nor I had
flagged — including a critical one: the judge's answer to the only question it is asked is
never read.

Full verification and evidence: **[REVIEW_RESPONSE.md](REVIEW_RESPONSE.md)**.
The revised plan: **[IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md)**.
Delivered sprint detail: **[ROADMAP_ARCHIVE.md](ROADMAP_ARCHIVE.md)**.

### Honest summary

| Dimension | State |
|---|---|
| Editorial policy and guardrails | strong — registry is provably untouched |
| Architecture | sound; the layering has held up under audit |
| Local test coverage | good (372), and CI gates every merge |
| Retrieval correctness | sound — window server-side, cap shared round-robin, surplus carried |
| Judge stage | sound — its verdict is used, validated, and never faked |
| Data-contract validation | validated against the models on every read and write |
| Empirical calibration | **none** — the scheduled dry run has never exercised Gemini |

---

## Open defects

Ordered by what blocks live writes. `R#` = from the external review, `A#` = from the audit,
`K#` = pre-existing.

| # | Defect | Severity | Sprint |
|---|---|---|---|
| ~~A1~~ | ~~Judge's `matchedProblemId` never read~~ | ✅ | closed 5.2 |
| ~~A2~~ | ~~`requiresHumanReview` discarded~~ | ✅ | closed 5.2 |
| ~~A3~~ | ~~Judge *unavailability* recorded as its *conclusion*~~ | ✅ | closed 5.2 |
| ~~A4~~ | ~~Registry identifier collision erased~~ | ✅ | closed 5.2 |
| ~~A5~~ | ~~Four review reasons declared but never emitted~~ | ✅ | closed 5.2 |
| ~~R2~~ | ~~No server-side time window~~ — `since_time`/`until_time`; date form found broken | ✅ | closed 5.3 |
| **R1** | Scheduled dry run skips extraction and pipeline entirely | 🔴 critical | 5.5 |
| **R5** | Matching never searches the candidate store | 🟠 major | 6 |
| ~~R15+~~ | ~~`candidate_id` unstable under identifier acquisition~~ | ✅ | closed 5.4 |
| ~~R3~~ | ~~`review` observations re-extracted daily~~ — plus retry backoff | ✅ | closed 5.4 |
| ~~R4~~ | ~~Pydantic models do not validate persisted files~~ | ✅ | closed 5.4 |
| ~~R11~~ | ~~Unfair per-run cap; overflow counted, not queued~~ | ✅ | closed 5.3 |
| ~~K10~~ | ~~Six of fourteen queries return zero~~ — TwitterAPI.io truncates at 512 chars | ✅ | closed 5.3 |
| **R6** | Corroboration accepts a bare GitHub link | 🟠 major | 6 |
| ~~R7~~ | ~~No CI runs the tests~~ | ✅ | closed 5.1 |
| ~~R15~~ | ~~Bot push has no rebase/retry~~ | ✅ | closed 5.1 |
| ~~R12~~ | ~~`changes.py` unexpected check unreachable~~ | ✅ | closed 5.1 |
| ~~R13~~ | ~~README claims there is no scraper~~ | ✅ | closed 5.1 |
| ~~R10~~ | ~~`storeTweetText: true` commits third-party text~~ | ✅ | closed 5.4 |
| **R8** | No curator workflow | 🟡 minor | 6.5 |
| ~~K11~~ | ~~TwitterAPI.io out of credit~~ | ✅ | topped up 2026-07-25 |
| **K6** | Only 13/40 curated records carry a source URL | 🟡 minor | human backfill |
| **K8** | `teorth` / `erdosproblems` handles unconfirmed | 🟡 minor | opportunistic |
| **K9** | Gold set fitted to known wordings — 100% recall is a floor, not proof | ℹ️ noted | ongoing |

---

## Decisions from this re-planning round

| # | Decision | Rationale |
|---|---|---|
| D33 | **CI moves ahead of the correctness work** | Five correctness sprints are about to land; tests that do not gate a merge are documentation, not protection |
| D34 | **A dedicated judge sprint (5.2) before retrieval** | Improving retrieval first would feed more data into a stage that discards its own conclusion |
| D35 | **Retrieval correctness before the end-to-end gate** | The review put the real dry run first; it is the right gate, but measuring through a lossy retrieval layer measures the wrong pipeline |
| D36 | **Candidate ids must be stable for life** | Reconcile identifier changes by merging, never renaming — today one problem yields three ids across three days |
| D37 | **"Corroboration" becomes a tiered external-reference gate** | A bare GitHub link is a reference, not corroboration; the current boolean overstates what we know |
| D38 | **Candidate-to-candidate matching ships *with* Sprint 6, not after** | The roadmap already promises "Twitter + arXiv resolve to one candidate" and the architecture cannot currently deliver it |
| D39 | **No review reason may exist without an emitter; no model field may be requested without a reader** | Both failure modes were found in this audit; they are now cross-cutting invariants |

---

## Required manual actions

| # | Action | Needed by |
|---|---|---|
| ✅ U1/U2 | Repository secrets added | done |
| ✅ U3 | Actions workflow permissions set to read/write | done |
| ✅ U7 | TwitterAPI.io topped up | done 2026-07-25 |
| U6 | After Sprint 5.5: read three real no-write runs, then flip `dryRunOnSchedule` | the gate |
| U8 | *(optional)* Confirm the correct `teorth` / `erdosproblems` handles by hand | opportunistic |

---

## Tests

**Passing:** 372 / 372 (`python -m pytest`) — no network, no API keys.
**Gating merges:** ✅ `ci.yml` on every push and pull request.
**Coverage gap closed:** `test_judge.py` now exercises the judge path end to end. The gap
was structural — `test_merge.outcome()` defaults to a deterministic identifier match, so
every one of 232 tests took the branch that has no judge in it.
**Build health:** `build_data.py` ✅ · `pnpm build` ✅ · live site ✅ · registry untouched ✅

---

## Completed since the re-plan

### Sprint 5.4 — Data contracts, cost and identity ✅

**R4 — the contract is now enforced.** Every model sets `extra = "forbid"`, which buys
nothing unless something validates, and nothing did: the workflow checked only that these
files were parseable JSON. Wiring `TypeAdapter` validation into every read and write
surfaced **eight fields that had been persisted for weeks without being declared** —
`extractionCacheKey`, `extractionWarnings`, `extractionAttempts`, `lastAttemptAt`,
`nextRetryAt`, `failureType`, `matchMethod`, `decision` — and a test fixture that had never
been a valid `Observation` at all. Validating on *write* catches the bug in the run that
caused it; on *read*, a file edited by hand or left by an older version. `ContractError` is
kept distinct from `CorruptStoreError`: a file that parses but is not what the code thinks it
is, is the more dangerous case, because everything downstream keeps working on data it has
misread.

**R3 — we stop paying for settled questions.** `review` is now a resolved state, so an
observation sitting in a curator's queue is no longer re-sent to Gemini every day it waits.
A failed extraction backs off 1h → 6h → 24h → 72h and then stops: one permanently malformed
post used to cost a call every run, forever. Measured on a broken post: **5 calls over 12
runs instead of 12**, then permanent — and a changed text, prompt or model still revives it.

**R15+ / D36 — an id is assigned once and kept for life.** `candidate_id` was derived from
whatever identifiers an observation happened to carry, so the day an arXiv id arrived the
same problem acquired a second id and a second record. Identity is now resolved by *looking
for* an existing candidate — identifier first, canonical name otherwise — and a late
identifier that reveals two records to be one problem **merges** them, oldest id surviving,
with `mergedFrom` keeping the vanished id traceable. Verified: three days, three identifier
states, **one candidate** where there used to be three.

**R10 — an excerpt, not a republication.** Full post text is working state: it is fetched,
extracted from, and then reduced to a 160-character excerpt once the observation resolves.
The durable committed record is excerpt + `textSha256` + URL; the complete text lives only in
`data/automation/raw/`, which `rawRetention` prunes. Unresolved observations keep their full
text, since truncating before extraction would silently degrade every extraction.

### Sprint 5.3 — Retrieval correctness ✅

**K10.** TwitterAPI.io silently truncates at **512 characters**. Long queries are sharded
into equivalent smaller ones rather than trimmed, and the old group-dropping truncation path
is gone. 8/14 queries returning results became 22/23; 35 tweets per run became 209.

**R2.** The lookback now goes to the server as `since_time`/`until_time`. It used to run
*after* the API had picked its 20 newest all-time matches, so a busy query could hand back 20
stale tweets and contribute nothing. The date form turned out to be applied **wrongly**, not
merely unverified — it returned tweets a day outside the window it was given — so only the
unix form is used. Its 44 characters are reserved out of the 512-char budget, because
otherwise fixing R2 would have re-opened K10.

**R11.** `deduped[:cap]` was a standing preference for whichever families were built first,
not a cap. Selection is round-robin, and the surplus is carried in `ingest_backlog.json`
rather than counted and dropped — deduplicated against both the fresh fetch and the
observation store so the overlapping lookback cannot make it grow without bound.

| first live run with all three | |
|---|---|
| queries | 28, zero failures |
| tweets fetched | 205 → 157 after dedupe |
| processed / **carried** | 50 / **107** (previously discarded) |
| fetched-then-discarded | **0** — `returned == kept` for every query |

Pagination replaced the roadmap's window bisection: the cursor walks exactly the window we
asked for, where bisection re-runs the query and re-fetches the overlap. It also fixed a
quieter mismatch — pages hold 20 and `max_pages` was 1, while tier 1 is configured for 40, so
the config had been asking for twice what the fetch could deliver. New `saturated` telemetry
flags a window that may hold more than we took; that is the signal that would justify
bisection, and it has not fired.

### Sprint 5.2 — Make the judge actually decide ✅

`test_judge.py` was written first, 28 tests, all failing. Then:

- **A1 — the judge's answer is used.** `matchedProblemId` now sets `problemRef` on the
  candidate and on the review entry, but **only if the id appears in the shortlist the judge
  was actually shown**. An invented id is rejected with a note and routed to review rather
  than trusted; the model cannot introduce a registry link out of nothing.
- **A2 — `requiresHumanReview` is honoured**, alongside a confidence floor (0.7). Either one
  routes to `judge_uncertain` instead of creating a candidate, and the review entry keeps the
  judge's decision and confidence so a curator sees what was overridden.
- **A3 — unavailability is no longer a conclusion.** No key, exhausted budget ⇒ the
  observation is **deferred**: nothing is mutated, it stays `extracted`, and the next run
  retries it. A transport *error* is different again and surfaces as `judge_failed`. Only a
  real "cannot tell" verdict is terminal. The run summary reports `judgeDeferred`.
- **A4 — a registry collision surfaces as `registry_conflict`**, carrying the colliding ids,
  and never reaches the judge. One identifier claiming two curated records is our data bug,
  not an ambiguity for a model to arbitrate.
- **A5 — no dead review reasons.** `identifier_conflict` was also declared and unemitted;
  rather than delete it, it now has a real emitter (an alias or lexical match while explicit
  identifiers disagree). A test enforces invariant D39 going forward.

The one structural change: `decide() -> str` became a `Resolution` dataclass. A string cannot
carry "deferred, mutate nothing" as distinct from "concluded", and A3 needs exactly that.

> Verified end to end against a stubbed judge: a confident verdict merges with the right
> `problemRef`; an invented id, a self-flagged verdict and a transport error each route to
> the correct queue reason; an absent key defers and leaves the record untouched.

### Sprint 5.1 — Truthfulness and CI ✅

- **`ci.yml`** on push and pull request: pytest (with keys explicitly blanked, so a test
  that starts needing credentials fails loudly rather than becoming un-runnable),
  `build_data.py`, an assertion that the build does not touch the registry, calibration,
  and `pnpm build`. A third `guardrails` job re-runs the promises this project makes.
- **README corrected.** It claimed "there is deliberately no automated scraper"; there is
  one. Replaced with an honest two-layer table and the measured corroboration base rate.
- **`changes.py` unexpected check made reachable.** It scoped `git status` to
  `data/automation`, then filtered for paths *outside* it — a set that could never be
  non-empty. Now unscoped, with run artifacts allow-listed.
- **Bot push rebases and retries.** A human push between checkout and push would previously
  make it a non-fast-forward and lose the day's run.
- 16 new tests (**248 total**), including one that fails if `data/results.json` is touched
  mid-run — the check that was dead before.

> The tests for `changes.py` used to run against the live working tree and only passed
> *because* the check was dead: any uncommitted edit would have broken them. They now build
> a throwaway git repo and assert the logic.

---

## K10 solved (2026-07-25)

**TwitterAPI.io returns HTTP 200 and an empty list for any query over 512 characters.** No
error. The failure looks exactly like "nobody posted about this today", which is how it
emptied six of fourteen queries through two live runs, an external review and a 232-test
suite.

A length sweep with the term set held broad puts the boundary at exactly 512 → 20 results,
513 → none, monotone. The fix shards long queries instead of trimming them, since a
disjunction distributes over a conjunction and the union of the shards is the original
query. It also removed the old truncation path, which dropped whole OR-groups to make a
query fit — silently narrowing what we looked for.

| | before | after |
|---|---|---|
| queries returning results | 8 / 14 | **22 / 23** |
| tweets fetched per run | 35 | **209** |

Two hypotheses died on the way, and how they died is the useful part. "Length definitively
ruled out" came from a bisect that never crossed 512 except once, and I built a conclusion
on that single reading. "A cap at 37 OR-terms" fit all 14 production queries and was still
wrong — length and term count moved together in the walk that produced it. Fitting every
observation was evidence of correlation, not of the right variable.

What actually decided it was a **witness test**: take a post the API itself returned, verify
from its own text that it satisfies both concept groups, then ask for the conjunction. It
came back empty even scoped to the author's own feed, which excludes "the window is empty"
and leaves only the query shape.

---

## Next task

**Sprint 5.3, remainder.** K10 is closed. Still open in this sprint: **R2** (server-side
`since_time` / `until_time`, so the lookback window stops being applied after the API has
already chosen 20 results) and **R11** (fair per-query quota with a backlog instead of an
overflow counter). Both are now more valuable than they were this morning, because 23
queries returning 209 tweets is a very different load profile from 8 returning 35.
