# Response to the external review (2026-07-25)

An external review assessed the automation pipeline before enabling live writes. This
document records **which claims were verified against the code**, what the verification
found, and what was discovered that neither the review nor I had flagged.

**Headline: 15 of 15 claims are accurate.** No claim was refuted or overstated. The review
also correctly identified that the project is *architecturally sound but not yet
empirically calibrated*, which matches what the first live run showed.

**The plan has been rewritten accordingly.** `dryRunOnSchedule` stays `true`.

---

## 1. Verification of the review's claims

Each was checked by reading the code, not by recollection.

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Scheduled dry-run skips extraction and pipeline | ✅ **TRUE** | `discover.yml` gates both steps on `dry == 'false'`. Only ingest runs. |
| 2 | No `since:`/`until:`; lookback applied after the API picked 20 | ✅ **TRUE** | `since:` appears only in `query_builder._term_matches` (offline matcher, treated as neutral), never in a built query. `ingest.within_lookback` filters client-side. |
| 3 | `review` observations are re-extracted every day | ✅ **TRUE** | `needs_extraction` skips `("irrelevant","extracted","matched","merged")`. `pipeline.py:135` writes `"review"`. Not in the list. |
| 4 | Pydantic does not validate persisted files | ✅ **TRUE** | `Observation` is `extra:"forbid"`, yet `extractionCacheKey`, `extractionWarnings`, `matchMethod`, `decision` are written to raw dicts and persisted. Nothing re-validates on read. |
| 5 | Matching never searches the candidate store | ✅ **TRUE** | `pipeline.py:108` passes only `registry`. `matching.py` has no notion of candidates. |
| 6 | Corroboration is too broad | ✅ **TRUE** | `CORROBORATING_KINDS` accepts any of six kinds; a bare GitHub link qualifies. |
| 7 | No CI runs the tests | ✅ **TRUE** | No workflow references `pytest`. |
| 8 | No curator workflow | ✅ **TRUE** | No `review_cli` / `promote_candidate` exists. |
| 9 | High-precision sources matter more than the public UI | ✅ **AGREED** | Already amended in Sprint 0; the review independently reaches the same conclusion. |
| 10 | `storeTweetText: true` puts third-party text in a public repo | ✅ **TRUE** | Confirmed in config. |
| 11 | Global cap is unfair, overflow is not queued | ✅ **TRUE** | `capped = deduped[:max_obs]`; `overflowDeferred` is a count only. |
| 12 | `changes.py` "unexpected" can never fire | ✅ **TRUE** | `git status` is scoped to `data/automation`, then filtered for paths *not* under it. Dead code. |
| 13 | README is stale | ✅ **TRUE** | Still says "there is deliberately **no automated scraper**". |
| 14 | `CURRENT_STATUS.md` has a stale tail | ✅ **TRUE** | Header says Sprint 5 done; §"Next recommended task" still says Sprint 3. |
| 15 | Bot push has no rebase/retry | ✅ **TRUE** | Bare `git push`. A concurrent human push loses the run. |

### One claim sharpened

The review notes that nothing merges two candidates with complementary identifiers. The
underlying defect is worse and fires **with a single source**: `candidate_id()` is
**unstable under identifier acquisition**.

```
day 1, name only      -> cand_a7ab176804c2088f
day 2, + arXiv id     -> cand_arxiv_2607-16356
day 3, + Erdős number -> cand_erdos_728
```

Three candidates for one problem, no second source required. Candidate ids must be stable
for the lifetime of the entity, with identifier changes handled by *merging*, never by
*renaming*.

---

## 2. What neither of us had flagged

Found by a five-lens adversarial audit of the automation code, each verified against the
source. These are **more serious than most of the review's list**, because they mean the
judge stage — the most expensive part of the pipeline — is largely decorative.

### A. `matchedProblemId` is never read — CRITICAL

The judge exists to answer one question: *which curated problem is this about?* We ask it,
we schema-validate the answer, and we **throw the answer away**.

- `matching.py:213` is the **only** site that sets `needs_judge=True`, and it hardcodes
  `matched_id=None`.
- `matchedProblemId` appears in exactly three places repo-wide: `matching.py:79`
  (serialising the outcome's *own* id), `matching.py:258` (the schema we send), and
  `judge_v1.md:49` (instructing the model to supply it). **No reader.**

Consequences, all reachable today:

- `same_problem_conflicting_claim` and `related_problem` are reachable *only* through the
  judge, so they **always** produce a review entry with `problemRef: null` and the text
  "contradicts what is recorded for a matched problem" — the curator is told a curated
  record is contradicted but not which of the 40.
- A judge-decided `same_problem_new_claim` creates a candidate with `problemRef: null` — a
  brand-new unlinked candidate for a problem the judge just said is already in the registry.

Missed by tests because `test_merge.outcome()` defaults to `method="identifier"`,
`matched="erdos-728"` — the judge path is never exercised end to end.

### B. `requiresHumanReview` is discarded — MAJOR

```python
if judge.get("requiresHumanReview"):
    return judge.get("decision") or "insufficient_information"
return judge.get("decision") or "insufficient_information"      # identical
```

Both branches are byte-identical. `judge_v1.md` rule 5 instructs the model to set the flag
whenever confidence is below 0.7, so a verdict the model itself flagged as unsafe still
creates a candidate with no review entry. `judgeConfidence` is recorded and never gated on.

### C. "Not judged" is written as "judge says it cannot tell" — MAJOR

Three unrelated operational conditions — no API key, judge error, budget exhausted — all
collapse to `verdict=None`, become the semantic conclusion `insufficient_information`, and
are **terminal**: the observation is stamped `review` and never retried. A day when the
budget ran out is indistinguishable from a day the model genuinely could not decide.

### D. Registry collisions are detected then erased — MAJOR

`match_observation` correctly detects one identifier claiming two curated records and sets
`conflict=True` with an explanatory note. `decide()` then maps it to
`insufficient_information`, and the note never reaches the review entry. A genuine **data
bug in the curated registry** is filed as an ordinary "cannot tell".

### E. Three review reasons are declared but never emitted

`registry_conflict`, `judge_failed` and `judge_uncertain` exist in the `ReviewReason` type
and are produced by no code path. Dead vocabulary that makes the queue look more
discriminating than it is.

---

## 3. What this changes about the plan

The review proposed 5.1 (correctness) → 5.2 (CI/ops) → 6 (multi-source) → 6.5 (curator)
→ 7 (frontend). I have adopted that shape with three changes:

1. **CI comes first, not second.** Six correctness sprints are about to land; the tests
   should gate them from the start rather than after. It is also the cheapest item.
2. **A new sprint for the judge.** Findings A–E were not in the review, and they mean the
   judge stage does not currently do its job. Fixing retrieval before fixing the judge
   would just feed more data into a stage that discards its own conclusion.
3. **Retrieval correctness before the real no-write run.** The review puts the end-to-end
   dry run first. It is the right *gate*, but running it while retrieval silently drops
   matches would measure the wrong pipeline. Fix what you measure with, then measure.

`K10` (six queries returning zero) is folded into the retrieval sprint, since it is the
same question: *are we actually retrieving what we think we are?*

---

## 4. Position on live writes

**Unchanged and reinforced: `dryRunOnSchedule` stays `true`.**

The review's conclusion — *architecturally strong, well tested locally, not yet empirically
production-calibrated* — is accurate, and findings A–D strengthen it. The gate to flipping
is Sprint 5.5: two or three real no-write end-to-end runs whose false-positive rate has
actually been read by a human.
