# Implementation roadmap — automated discovery pipeline

Revised 2026-07-25 after an external review (all 15 claims verified — see
[REVIEW_RESPONSE.md](REVIEW_RESPONSE.md)) and a five-lens adversarial audit that found four
further defects in the judge stage.

**Statuses:** `planned` · `in progress` · `blocked` · `completed`

| Sprint | Title | Status |
|---|---|---|
| 0 | Repository assessment and architecture | **completed** |
| 1 | Test scaffolding + deterministic ingestion | **completed** |
| 1.5 | Query strategy, syntax probe and calibration | **completed** |
| 2 | Gemini structured extraction | **completed** |
| 3 | Entity matching and shortlist | **completed** |
| 4 | Safe merge engine and review queue | **completed** |
| 5 | Scheduled GitHub Actions workflow | **completed** |
| **5.1** | **Truthfulness and CI** | **completed** |
| **5.2** | **Make the judge actually decide** | **completed** |
| **5.3** | **Retrieval correctness** | **completed** |
| **5.4** | **Data contracts, cost and identity** | **completed** |
| **5.5** | **Real no-write end-to-end → gate to live writes** | **completed — gate blocked on K12** |
| 6 | Multi-source + candidate entity resolution | **completed** |
| 6.5 | Curator workflow | **completed** |
| 7 | Frontend candidate visibility | **completed** |
| 8 | Hardening and operational documentation | planned |

> **Sprints 0–5 are unchanged and remain as delivered.** Their detail has been moved to
> [ROADMAP_ARCHIVE.md](ROADMAP_ARCHIVE.md) so this file stays about what is next.

---

## Why the order changed

The review proposed *correctness → CI → multi-source*. Three adjustments:

1. **CI first.** Five correctness sprints are about to land. Tests that do not gate a merge
   are documentation, not protection, and this is the cheapest item on the list.
2. **A new judge sprint (5.2).** The audit found the judge's `matchedProblemId` is never
   read, `requiresHumanReview` is discarded, and judge *unavailability* is recorded as the
   judge's *conclusion*. Improving retrieval first would only feed more data into a stage
   that throws away its own answer.
3. **Retrieval before the end-to-end gate.** The review puts the real no-write run first.
   It is the right gate, but running it while retrieval silently drops matches measures the
   wrong pipeline. Fix the instrument, then take the measurement.

---

## Sprint 5.1 — Truthfulness and CI · `completed`

**Objective.** Stop the repository asserting things that are not true, and make the 232
tests actually protect the branch.

**Why first.** Every later sprint is a correctness change; they should land behind a gate.

**Files.** `.github/workflows/ci.yml` (new) · `README.md` · `scripts/automation/changes.py`
· `.github/workflows/discover.yml`

**Deliverables**

1. `ci.yml` on `push` and `pull_request`: `pytest`, `build_data.py`,
   `pnpm install --frozen-lockfile`, `pnpm build`, `calibrate` (recall must not regress).
2. README: remove "there is deliberately no automated scraper" — there is one. Describe the
   curated-vs-automated split honestly.
3. `changes.py`: make the `unexpected` check real — run `git status --porcelain` unscoped,
   then flag anything outside `data/automation/`. Today it is unreachable code.
4. `discover.yml`: `git pull --rebase` before push, with a bounded retry, so a concurrent
   human push cannot silently lose the day's run.

**Acceptance.** A red test blocks a merge. No document asserts something contradicted by
the code. A deliberate `data/results.json` edit inside a run is caught by `changes.py`.

**Risk.** None material. **Rollback.** Delete `ci.yml`.

---

## Sprint 5.2 — Make the judge actually decide · `completed`

**Objective.** The judge currently costs money and produces nothing that survives. Fix that,
and stop conflating "we did not ask" with "it could not tell".

**Files.** `scripts/automation/merge.py` · `pipeline.py` · `matching.py` · `review.py`
· `tests/automation/test_merge.py` · `tests/automation/test_judge.py` (new)

**Deliverables**

1. **Thread `matchedProblemId` through.** Accept it **only** if it appears in the shortlist
   actually shown to the judge — never an id the model invented. Use it for `problemRef` on
   candidates and for `problem_ref` on review entries.
2. **Honour `requiresHumanReview`** and a configurable judge-confidence floor: route to
   `review("judge_uncertain")` instead of creating a candidate.
3. **Separate unavailability from uncertainty.** No key / error / exhausted budget ⇒ leave
   the observation `extracted` so the next run retries it, and report
   `judgeDeferred` / `judgeUnavailable` in the summary. Only a real verdict of
   "cannot tell" may be terminal.
4. **Emit `registry_conflict`** when one identifier claims two curated records, carrying the
   colliding ids — it is a curated-data bug, not an ordinary ambiguity.
5. **Emit `judge_failed`.** Together with 2 and 4 this retires all three dead review reasons.
6. **Carry `outcome.notes` onto the review entry** so the curator sees why.

**Validation.** A new `test_judge.py` exercising the judge path end to end — the existing
`outcome()` helper defaults to a deterministic identifier match, which is exactly why these
defects survived. Tests: judge id honoured; invented id rejected; `requiresHumanReview`
routes to review; budget exhaustion is retried not terminal; registry collision surfaces as
`registry_conflict`.

**Acceptance.** Every field in the judge response schema is either used or removed from the
schema. No review reason is declared and unemitted.

**Risk.** Touching the decision path. Mitigated by the tests above landing first.

**Delivered.** All six deliverables, plus one structural change the plan did not anticipate:
`decide() -> str` became a `Resolution` dataclass. A bare string cannot express *"deferred —
mutate nothing"* as distinct from *"concluded"*, and deliverable 3 requires exactly that
distinction. `identifier_conflict` was declared but unemitted and would have failed the same
D39 invariant as the other three, so rather than delete it, it was given a real emitter: an
alias or lexical match while explicit identifiers disagree with another record.

`test_judge.py` (28 tests) landed first and all 28 failed against the old code. Suite: 274.

---

## Sprint 5.3 — Retrieval correctness · `completed`

**Objective.** Retrieve what we believe we retrieve. Currently a busy query silently loses
matches, and six of fourteen queries return nothing for reasons unknown.

**Files.** `query_builder.py` · `twitter.py` · `ingest.py` · `config/automation.json`
· `docs/automation/TWITTER_QUERY_STRATEGY.md`

**Deliverables**

1. **Server-side time windows.** Put `since_time` / `until_time` (or the verified
   equivalent) into the query itself. Today the 30-hour lookback is applied *after* the API
   has already chosen its 20 most recent results, so a query with 500 matches in the window
   loses 480 of them unseen. **This is the single biggest recall defect.**
2. **Adaptive window splitting.** When a window returns a full page, bisect it
   (30h → 15h + 15h, recursively) until each sub-window is fully retrievable.
3. **Fair per-query quota and a persistent backlog.** Replace `deduped[:max_obs]` with a
   per-tier allocation, and write overflow to a real backlog file that the next run drains —
   today the first query can consume the whole budget and starve trusted accounts.
4. **Resolve K10.** Six queries returned exactly zero live. Length was tested and is *not*
   the cause. Determine whether they are genuinely restrictive or structurally broken, and
   record the answer. Needs API credit.

**Validation.** A fixture whose window contains more items than one page proves nothing is
lost. Backlog drains deterministically across runs. K10 answered in the strategy doc.

**Blocked by.** TwitterAPI.io credit (currently HTTP 402).

---

## Sprint 5.4 — Data contracts, cost and identity · `completed`

**Objective.** Make the persisted files match their declared models, stop paying for the
same observation daily, and make candidate identity stable.

**Files.** `models.py` · `merge.py` · `extraction.py` · `store.py` · `ids.py`
· `config/automation.json`

**Deliverables**

1. **Real contract validation.** Declare every persisted field on `Observation` /
   `Candidate` / `ReviewEntry` (`extractionCacheKey`, `extractionWarnings`, `matchMethod`,
   `decision`, …) and validate with `TypeAdapter(list[Model])` **on read and before every
   write**. Today the workflow checks only that the file is parseable JSON.
2. **`review` becomes a stable state** in `needs_extraction`, so a reviewed observation is
   not re-sent to Gemini every day.
3. **Retry backoff for `extraction_failed`**: `extractionAttempts`, `lastAttemptAt`,
   `nextRetryAt`, `failureType` — a permanently malformed post must not cost a call a day.
4. **Stable candidate ids.** An id must not change when an identifier arrives. Assign once,
   keep for life, and reconcile identifier changes by *merging* candidates, never renaming.
5. **Tweet-text policy.** Commit excerpt + hash + URL; keep full text to the run and to a
   short-retention artifact. Flip `storeTweetText` accordingly.

**Validation.** A deliberately malformed persisted file fails validation loudly. A candidate
that gains an arXiv id keeps its id. Second run over unchanged data makes zero paid calls.

---

## Sprint 5.5 — Real no-write end-to-end · `planned` — **the gate**

**Objective.** Run the *whole* pipeline against real APIs without writing anything, and read
the false-positive rate before trusting it.

**Why it exists.** Today `--dry-run` on the schedule runs ingest only, and
`extraction --dry-run` uses a stub model — so the scheduled dry run has never exercised
Gemini, matching, the judge or the merge engine. `OPERATIONS.md` promised reviewable
"review-queue reasons" from those runs, which was not achievable.

**Files.** `scripts/automation/run_pipeline.py` (new orchestrator) · `discover.yml`
· `OPERATIONS.md`

**Deliverables**

1. `run_pipeline --plan`: real Twitter, real Gemini, real matching and judging, candidates
   and review queue built **in memory**, written only to an artifact and the Step Summary.
   Repository untouched.
2. Two distinct modes, named honestly: **offline fixture mode** (no keys, no network) and
   **real-API no-write mode**.
3. `discover.yml` uses `--plan` for scheduled dry runs, so the dry run finally exercises
   the whole pipeline.
4. Three real `--plan` runs; a written note recording observed precision, the review-reason
   distribution, and the API cost per run.

**Acceptance — and this is the gate to live writes.** `git status` clean after a `--plan`
run; a human has read three runs' output; the false-positive rate is written down. Only
then does `dryRunOnSchedule` flip to `false`.

---

## Sprint 6 — Multi-source + candidate entity resolution · `planned`

**Objective.** Add higher-precision sources, and make cross-source deduplication actually
possible.

> The review is right that this ordering matters: the roadmap already promised
> "Twitter + arXiv resolve to one candidate", and the current architecture **cannot deliver
> it**, because matching never consults the candidate store. That must land *with* the new
> sources, not after them.

**Deliverables**

1. **Candidate-to-candidate matching.** `match_observation` searches two indexes — the
   curated registry *and* pending candidates — returning `matchedProblemRef` and/or
   `matchedCandidateId`. Includes a merge path for two candidates with complementary
   identifiers.
2. **Evidence strength**, replacing the single boolean gate. Rename *corroboration gate* →
   **external-reference gate** and tier it:
   `reference_only < artifact_available < formal_artifact < paper_available <
   independent_confirmation < registry_confirmation`.
   A bare GitHub link is `reference_only` — enough to create a candidate internally, not
   enough to be called corroborated.
3. **arXiv** ingestion (free, structured, high precision).
4. **erdosproblems.com + Tao's AI-contributions wiki** — already cited as sources in this
   dataset.
5. **GitHub** search for Lean artifact repositories.

All sources emit the same `Observation` shape, so stages 3–7 stay unchanged.

**Acceptance.** A Twitter observation and an arXiv observation about one problem resolve to
**one** candidate, and a test proves it.

---

## Sprint 6.5 — Curator workflow · `planned`

**Objective.** Close the loop from "signal" to "curated result" without hand-editing JSON.

**Deliverables**

```bash
python -m scripts.automation.review_cli list [--reason ...]
python -m scripts.automation.review_cli approve <id>
python -m scripts.automation.review_cli dismiss <id>
python -m scripts.automation.review_cli link <id> erdos-728
python -m scripts.automation.promote_candidate <id> --draft
```

`promote_candidate` **generates a proposed `results.json` entry and opens a draft PR**. It
never edits the registry directly — promotion stays a human merge, which is the project's
central promise.

**Acceptance.** A candidate can go from queue to draft PR without a text editor, and no path
in the tool can write `results.json`.

---

## Sprint 7 — Frontend candidate visibility (optional) · `planned`

Unchanged, and still last. A "Signals from X — unverified" section, visually and
semantically separate, with zero effect on any curated metric (test-enforced). Deliberately
gated on the false-positive rate measured in 5.5 — publishing unverified claims under this
project's name is the reputational risk the whole design exists to avoid.

---

## Sprint 8 — Hardening and operational documentation · `planned`

End-to-end fixture run, cost metrics, recovery procedures, and a final documentation sync.

---

## Cross-cutting invariants (unchanged)

1. `data/results.json` is never written by automation.
2. `build_data.py` reads only `results.json`.
3. Tests never require real API keys.
4. Every write is atomic.
5. An API failure never replaces good data with empty data.
6. `pnpm build` and `build_data.py` pass at the end of every sprint.
7. The live GitHub Pages deployment keeps working.
8. **New:** no review reason is declared without a code path that emits it.
9. **New:** no field is requested from a model without a code path that reads it.
