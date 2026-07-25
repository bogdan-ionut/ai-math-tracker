# Current status — automation implementation log

> Living document, updated by hand as work proceeds. **Deliberately not written by the
> scheduled workflow** — machine state lives in `data/automation/processing_state.json`, so
> this file never accumulates meaningless daily diffs.

**Last updated:** 2026-07-25
**Phase:** executing the revised plan
**Next sprint:** 5.2 — Make the judge actually decide
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
| Local test coverage | good (232) — but nothing gates a merge |
| Retrieval correctness | **defective** — a busy query silently loses matches |
| Judge stage | **largely decorative** — its conclusion is discarded |
| Data-contract validation | JSON-parseable only, not model-validated |
| Empirical calibration | **none** — the scheduled dry run has never exercised Gemini |

---

## Open defects

Ordered by what blocks live writes. `R#` = from the external review, `A#` = from the audit,
`K#` = pre-existing.

| # | Defect | Severity | Sprint |
|---|---|---|---|
| **A1** | Judge's `matchedProblemId` never read → every judge-resolved observation loses its registry link | 🔴 critical | 5.2 |
| **A2** | `requiresHumanReview` discarded — both branches of the `if` are identical | 🟠 major | 5.2 |
| **A3** | Judge *unavailability* recorded as the judge's *conclusion*, and terminal | 🟠 major | 5.2 |
| **A4** | Registry identifier collision detected, then erased into "insufficient_information" | 🟠 major | 5.2 |
| **A5** | `registry_conflict` / `judge_failed` / `judge_uncertain` declared but never emitted | 🟡 minor | 5.2 |
| **R2** | No server-side `since:`/`until:` — lookback applied after the API picked 20 | 🔴 critical | 5.3 |
| **R1** | Scheduled dry run skips extraction and pipeline entirely | 🔴 critical | 5.5 |
| **R5** | Matching never searches the candidate store | 🟠 major | 6 |
| **R15+** | `candidate_id` unstable under identifier acquisition → duplicates from one source | 🟠 major | 5.4 |
| **R3** | `review` observations re-extracted daily (wasted Gemini) | 🟠 major | 5.4 |
| **R4** | Pydantic models do not validate persisted files | 🟠 major | 5.4 |
| **R11** | Unfair per-run cap; overflow counted, not queued | 🟠 major | 5.3 |
| **K10** | Six of fourteen queries return zero — **reproduced twice**; length and term-count ruled out, cause still unknown | 🟠 major | 5.3 |
| **R6** | Corroboration accepts a bare GitHub link | 🟠 major | 6 |
| ~~R7~~ | ~~No CI runs the tests~~ | ✅ | closed 5.1 |
| ~~R15~~ | ~~Bot push has no rebase/retry~~ | ✅ | closed 5.1 |
| ~~R12~~ | ~~`changes.py` unexpected check unreachable~~ | ✅ | closed 5.1 |
| ~~R13~~ | ~~README claims there is no scraper~~ | ✅ | closed 5.1 |
| **R10** | `storeTweetText: true` commits third-party text | 🟡 minor | 5.4 |
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

**Passing:** 248 / 248 (`python -m pytest`) — no network, no API keys.
**Gating merges:** ✅ `ci.yml` on every push and pull request.
**Known coverage gap:** the judge path is never exercised end to end. `test_merge.outcome()`
defaults to a deterministic identifier match, which is precisely why A1–A4 survived.
**Build health:** `build_data.py` ✅ · `pnpm build` ✅ · live site ✅ · registry untouched ✅

---

## Completed since the re-plan

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

## K10 narrowed (2026-07-25)

Re-measured now that credit is restored. The same six queries return zero on a second run
days apart — **structural, not transient**. Query length is definitively ruled out (462
chars works, 417 does not, everything shorter works). A plain OR-term count is ruled out
too. The failing six all demand three-or-more concept groups or an all-quoted-phrase group;
whether that makes them genuinely restrictive or trips a backend limit is the question
Sprint 5.3 opens with, using a differential probe that strips one element at a time.

Consequence worth stating: `disputes-and-corrections` — added precisely because both
`disputed` records here are dispute signals — is currently returning nothing in production.

---

## Next task

**Sprint 5.2 — Make the judge actually decide.** The largest correctness gain per line
changed: A1–A5 in the defect table. Start with `tests/automation/test_judge.py`, because the
existing `outcome()` helper defaults to a deterministic identifier match and that is exactly
why these defects survived.
