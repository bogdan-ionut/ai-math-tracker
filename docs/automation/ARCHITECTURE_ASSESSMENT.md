# Architecture assessment — automated discovery pipeline

**Status:** Sprint 0 deliverable. No production behaviour has been changed.
**Date:** 2026-07-25
**Scope:** evaluates the proposed TwitterAPI.io → Gemini → merge pipeline against the
repository as it actually exists today.

---

## 1. The repository as it stands

### 1.1 Source of truth

`data/results.json` — 40 hand-curated records, one per distinct mathematical problem
(a batch such as the 44 OEIS conjectures is a single record with `count: 44` and an
optional `members` list).

Current composition:

| Status | Records | Meaning |
|---|---|---|
| `audited` | 17 | paper, Lean artifact, or named expert confirmation |
| `reported` | 12 | appears in a chronology, not independently audited |
| `provisional` | 9 | public claim awaiting artifacts |
| `disputed` | 2 | contested; recorded but **excluded from all headline totals** |

Families: Erdős 22 · Named conjecture 10 · Graffiti 4 · Graffiti.pc / WOWII 2 ·
Erdős–Graham 1 · OEIS 1.

**Only 13 of 40 records (33%) currently carry a source URL.** This is the single
largest data-quality gap in the repository and it is directly relevant below.

### 1.2 Fields in use

```
id · title · family · description · resultType · resolution · status
claimedAt · auditedAt          ← the honesty split
lab · labKey · model · count · members
isOpenProblem · yearsOpen · erdosNumber
sources[] · paperUrl · leanArtifactUrl
confidence · auditNotes · provenanceNote
impact · assessment            ← editorial judgement
```

### 1.3 Validation

`scripts/schema.py` (Pydantic v2, `extra: forbid`) enforces five invariants:

1. `status == "audited"` ⇒ `auditedAt` is set;
2. `impact` is set ⇒ `assessment` is non-empty;
3. `status == "disputed"` ⇒ `auditNotes` or `supersededBy` explains why;
4. `members` present ⇒ `len(members) == count`;
5. ids are unique.

`scripts/build_data.py` validates, sorts, computes roll-ups, and writes
`public/data/{conjectures,summary,metadata,schema}.json`. Disputed records are
**excluded from `total`** but still emitted.

### 1.4 Build and deploy

`.github/workflows/deploy-pages.yml`, triggered on **any push to `main`** plus
`workflow_dispatch`. Steps: checkout → Python 3.12 → `build_data.py` → pnpm → `pnpm build`
(`tsc && vite build`) → `upload-pages-artifact` → `deploy-pages`.
`concurrency: group: pages`.

### 1.5 Frontend

React 18 + Vite + TS. `useDataset` fetches `public/data/*.json` at runtime relative to
`import.meta.env.BASE_URL`. `computeMetrics` in `src/lib/filters.ts` derives every headline
number **client-side from the full record array**, excluding only `disputed`.

> **Consequence for this project:** any record added to `conjectures.json` immediately
> enters the KPIs, the constellation, the deficit chart and the ledger. There is no
> "quarantine" concept in the current frontend. Candidates therefore **must not** be
> written into `conjectures.json`.

### 1.6 Pre-existing gaps that block the stated testing requirements

| Gap | Impact on this plan |
|---|---|
| No Python test runner (`pytest` not in `scripts/requirements.txt`) | The mandated test suite has nowhere to live |
| No JS test runner (`vitest` not installed) | Frontend tests in the spec cannot run |
| `package.json` has `"lint": "eslint …"` but **ESLint is not a dependency** — the script fails | Must be fixed or removed before CI can lint |
| No `aliases` field on records | Alias matching (explicitly required) has no store |
| No structured external-identifier field (arXiv / DOI / OEIS) | Deterministic matching is weaker than the plan assumes |

These are cheap to fix and are pulled into Sprint 1.

---

## 2. Critical evaluation of the proposed architecture

The proposal is well-specified and its safety instincts are correct. The guardrail list,
the deterministic-merge-engine principle, and the refusal to let an LLM mutate the
repository are all right and I would not weaken them. My criticisms are about **source
selection, scope, and a small number of concrete failure modes.**

### 2.1 The headline objection: X/Twitter is the lowest-precision source available, and this project exists specifically to filter it

This is the most important point in this document.

The entire editorial value of this repository is the separation of *claimed* from
*verified*. The live site's signature chart is literally called **"The verification
deficit"**. X is where the deficit is manufactured.

This is not a hypothetical. Two records in the current dataset are corrections of
X-originated claims:

- **`alleged-roll-conjecture`** — a claimed counterexample to a "50-year-old conjecture"
  that, on research, **does not exist in the mathematical literature**. Traced to a
  single unverifiable social post. Recorded as `disputed`.
- **`graffiti-conjecture-154`** — a real counterexample, but a **rediscovery** of a
  witness published a month earlier. Recorded as `disputed`.

A Twitter-first discovery pipeline will produce these at a high rate. That is not a
defect in the implementation — it is the base rate of the source.

**I am not recommending we drop Twitter.** It is genuinely the fastest signal, and the
objective explicitly asks for it. I am recommending two things:

1. **Twitter-derived items are never auto-promoted to `candidates` on their own.**
   A Twitter observation with no corroborating external identifier (arXiv ID, DOI, Lean
   repo, erdosproblems.com entry) goes to the **review queue**, not to `candidates.json`.
   Corroboration, not model confidence, is the promotion gate. This is a one-line policy
   in the merge engine and it inverts the failure mode from "publishes hype" to
   "surfaces hype for a human".

2. **Add high-precision sources early (Sprint 3.5 / 6), not eventually.** Specifically
   `arxiv.org` API, `erdosproblems.com` (structured problem list + status), and Terence
   Tao's `teorth/erdosproblems` **AI-contributions wiki** — which is already cited as a
   source in this dataset and is a curated, structured, free, high-precision feed of
   exactly the events this project tracks. GitHub search for Lean artifact repos is
   similarly cheap and precise.

   Building the ingestion layer source-agnostic from day one (an `Observation` with a
   `sourceType`) costs nothing now and makes this a config change later.

**Verdict:** proceed with Twitter as specified, but with corroboration-gated promotion,
and design the ingestion interface so additional sources are a plug-in rather than a
rewrite.

### 2.2 Do NOT migrate `results.json`. Add a parallel layer. (Explicitly requested evaluation)

**Recommendation: preserve the existing public data model unchanged; add a parallel
observation/candidate layer.** Reasons:

- The frontend derives every metric from the flat record array. A normalised
  problem/claim/evidence model would require rewriting `computeMetrics`, all six charts,
  the ledger and the drawer — with no user-visible benefit on day one.
- The curated registry is small (40 records) and human-maintained. Normalisation solves
  scale problems this dataset does not have.
- A migration and a new ingestion pipeline landing together means a failure in either is
  hard to attribute.

The parallel layout in the proposal is sound. Adopted with one change (raw storage, §2.5):

```
data/
├── results.json                    # curated, human-owned, untouched by automation
└── automation/
    ├── observations.json           # discovered source signals
    ├── candidates.json             # proposed results — NEVER read by the frontend build
    ├── review_queue.json           # everything uncertain
    ├── aliases.json                # problem-name → canonical id
    ├── processing_state.json       # cursor, counters, last run
    └── raw/twitter/YYYY-MM-DD.json # compacted, retention-limited (§2.5)
```

### 2.3 Should problems / claims / evidence / observations become separate entities? (Explicitly requested evaluation)

**Yes conceptually — inside the automation layer only. No, not in the public model, not now.**

The proposal is right that "announcement → independent confirmation → Lean formalization"
is one problem, one-or-more claims, several evidence events. The current flat model
genuinely cannot express that; it fakes it with `auditNotes` prose.

But the correct sequencing is:

- **Now:** model `Observation` and `Candidate` as first-class records in the automation
  layer, each carrying a `problemRef` (a curated `results.json` id) when matched.
  Evidence events live as a list *on the candidate*.
- **Later, only if the curated registry outgrows the flat file:** promote `Problem` /
  `Claim` / `Evidence` into the public model and rewrite the frontend deliberately, as
  its own project.

This gives us the entity-resolution semantics the plan needs without a schema migration.

### 2.4 Embeddings: not justified at this scale — defer

The corpus is **40 curated records**. A shortlist over 40 items needs no vector index.
Deterministic identifiers + alias table + normalised-title similarity (RapidFuzz or
`difflib`) will resolve nearly everything, and where it does not, the fallback is the
review queue — which is the correct destination anyway.

Embeddings add an API dependency, a cache-invalidation problem, and a cost line for a
retrieval problem that a 40-row scan solves exactly. **Recommendation: no embeddings in
the initial implementation.** Revisit only if the curated registry passes ~500 records
*and* shortlist recall is measurably failing.

### 2.5 Do not commit raw tweet payloads to a public repository

The proposal already says "do not commit uncontrolled amounts of raw API payload data";
I want to state the reason sharply because it changes the design:

- It republishes third-party authors' content verbatim in a public repo (copyright /
  ToS / takedown exposure), and may capture personal data of non-public individuals.
- It bloats git history irreversibly.

**Recommendation:** the committed `raw/twitter/YYYY-MM-DD.json` stores only the *minimal
provenance fields the plan enumerates* — tweet id, URL, author handle, created-at,
collected-at, matched query, extracted links, and a **SHA-256 of the original text** —
plus text truncated to a short excerpt (≤ 280 chars is the whole tweet, so in practice:
store text only where needed for reprocessing, and make it configurable). Full payloads,
if needed for debugging, go to an **Actions artifact with a 7-day retention**, not to git.
Apply a rolling compaction: raw files older than N days are pruned in the same job.

### 2.6 Guardrail gap: the schema alone will not stop an impact write

The invariant "impact requires assessment" prevents a *bare* score — but an automated
writer that emits both fields together would pass validation. The guardrail must be
enforced where mutations are decided, not only where records are validated.

**Recommendation:** the merge engine carries an explicit **field allowlist** for automated
writes. Automation may never write, under any decision branch:

```
status (to "audited")  ·  auditedAt  ·  impact  ·  assessment
confidence             ·  auditNotes ·  provenanceNote
```

and may never delete a curated record. This gets a dedicated test
(`test_no_automatic_audited_promotion`, `test_no_automatic_impact_write`).

### 2.7 `CURRENT_STATUS.md` must not be machine-written on a schedule

The proposal asks for it to be updated "only when appropriate and without creating
meaningless daily diffs". The reliable way to satisfy that is a hard split:

- **`processing_state.json`** — machine-owned. Cursors, counters, timestamps, API call
  counts. Rewritten every run.
- **`CURRENT_STATUS.md`** — human/agent-owned. Never written by the scheduled workflow.

Trying to have a cron job write prose into a status document is how you get 365 noise
commits a year.

### 2.8 Workflow topology and loop prevention

`deploy-pages.yml` currently fires on **any** push to `main`. A data commit from the
collector will therefore trigger a deploy — which is what we want — but we must ensure the
deploy never triggers the collector.

**Recommendation: two workflows, one direction of causation.**

| Workflow | Trigger | Writes | Triggers |
|---|---|---|---|
| `discover.yml` | `schedule` + `workflow_dispatch` | commits `data/automation/**` | deploy (via push) |
| `deploy-pages.yml` | `push` to `main` + `workflow_dispatch` | nothing | nothing |

Plus: `concurrency: group: discover, cancel-in-progress: false` (never cancel a
half-written data run), and the standard `[skip ci]`-style guard is *not* needed because
deploy has no commit step — the causation graph is already acyclic.

Note the collector needs `contents: write`; the deploy job keeps `contents: read`.

### 2.9 Schedule and timezone

GitHub Actions cron is **UTC-only** — there is no timezone field. Europe/Bucharest is
UTC+3 (EEST, summer) and UTC+2 (EET, winter), so any fixed cron drifts one hour across
DST. This must be documented rather than solved.

**Recommendation:** `cron: "20 4 * * *"` → **07:20 EEST / 06:20 EET**. Off-the-hour to
avoid the scheduling stampede at :00 (GitHub explicitly warns that on-the-hour crons are
delayed under load).

### 2.10 Cost

Rough envelope at the proposed 14 queries/day:

- TwitterAPI.io: 14 queries × ~1 page/day. Small, but **needs a hard cap per run**.
- Gemini: only for *new, non-duplicate* observations. With relevance pre-filtering and
  extraction caching keyed on `(tweet_id, prompt_version, model_version)`, steady-state
  should be a handful of calls/day; the expensive day is the first backfill.

**Recommendation:** `MAX_OBSERVATIONS_PER_RUN` (default 50) and `MAX_JUDGE_CALLS_PER_RUN`
(default 15), both configurable, both logged, both counted into `processing_state.json`.
Overflow is not dropped — it is left unprocessed for the next run, and the cursor does not
advance past it.

### 2.11 Smaller notes

- **TwitterAPI.io is a third-party scraper**, not the official X API. Treat availability
  and ToS as a live risk; keep the client behind an interface so it can be swapped.
- **Engagement metrics must never influence classification.** The guardrail list says
  this; it should also be enforced by simply not passing engagement fields into the
  Gemini prompts.
- **`resultType` vs `resolution`** are near-duplicates in the current schema
  (`counterexample` / `"Counterexample"`). Automation should write neither; a human
  cleanup is a separate concern. Noted so it is not "fixed" mid-pipeline.
- **Atomic writes**: write to `*.tmp` then `os.replace()` — a partial API failure must
  never truncate a good file.

---

## 3. Recommended architecture (as amended)

```
config/twitter_queries.json
        │
        ▼
[1] fetch          TwitterAPI.io client · retries · timeouts · rate-limit backoff
        │          → data/automation/raw/twitter/YYYY-MM-DD.json  (minimal, retention-capped)
        ▼
[2] normalise      → Observation records · stable id = sha256(sourceType:sourceNativeId)
        │             URL canonicalisation · identifier extraction (arXiv/DOI/OEIS/Erdős/Lean)
        ▼
[3] dedupe         exact: source-native id, canonical URL, retweet/quote-of
        │          (no model call)
        ▼
[4] extract        Gemini structured output → Pydantic ExtractionResult
        │          cached on (observationId, promptVersion, modelVersion)
        ▼
[5] shortlist      deterministic identifiers → aliases → normalised-title similarity
        │          (no embeddings)
        ▼
[6] judge          Gemini relationship judge — ONLY for ambiguous shortlists
        │          → {same_source_duplicate | same_problem_same_claim | same_problem_new_claim
        │             | same_problem_conflicting_claim | related_problem | distinct_problem
        │             | insufficient_information}
        ▼
[7] merge          DETERMINISTIC Python. Field allowlist. Corroboration gate.
        │          → candidates.json · review_queue.json · aliases.json
        ▼
[8] build          existing scripts/build_data.py  (reads ONLY results.json)
        ▼
[9] deploy         existing deploy-pages.yml
```

Steps 1–7 are new and self-contained. **Steps 8–9 are untouched**, which is the property
that keeps the live site safe throughout.

---

## 4. Risks and limitations

| Risk | Severity | Mitigation |
|---|---|---|
| Twitter source produces mostly noise / hype | **High** | Corroboration-gated promotion (§2.1); review queue is the default sink |
| Automated write reaches an editorial field | **High** | Field allowlist in merge engine + dedicated tests (§2.6) |
| Candidate data leaks into headline metrics | **High** | `candidates.json` is never read by `build_data.py`; frontend loads it only in a later, separate sprint |
| API failure overwrites good data with empty | Medium | Atomic writes; "no results" ≠ "empty result"; explicit failure taxonomy |
| Runaway cost on first backfill | Medium | Per-run caps; cursor does not advance past unprocessed items |
| TwitterAPI.io unavailable / ToS change | Medium | Client behind an interface; pipeline degrades to no-op, not to failure |
| Raw payloads bloat repo / republish third-party text | Medium | Minimal fields + hash; artifacts for full payloads; rolling compaction (§2.5) |
| Bot commit loop | Low | Acyclic workflow topology (§2.8) |
| LLM fabricates identifiers | Medium | Schema permits null; extraction prompt forbids invention; deterministic identifiers always win over model output |

---

## 5. What to implement now vs. defer

**Now (Sprints 1–5):** ingestion, deduplication, extraction, matching, merge, review
queue, scheduled workflow, tests, dry-run. Test scaffolding and the `aliases` field are
pulled into Sprint 1 because nothing else can be tested without them.

**Deferred, with reasons:**

| Deferred | Why | Revisit when |
|---|---|---|
| Embeddings / vector store | 40 records; lexical + identifiers suffice | > ~500 records and measurable recall failure |
| Problem/Claim/Evidence in the **public** model | Would require rewriting all six charts + metrics | Curated registry outgrows the flat file |
| Public "Signals from X — unverified" UI | Adds scope; must not perturb metrics | Sprint 6, after the merge engine has run for a while and we know the false-positive rate |
| Additional sources (arXiv, erdosproblems, OEIS, GitHub) | Sequencing — prove the engine on one source first | Sprint 6+; interface is designed for it now |
| Auto-promotion of any candidate into `results.json` | Contradicts the editorial premise | Never automatic. A human runs a promotion script that opens a PR |

---

## 6. Answers to the questions posed in the brief

> **Is the current `results.json` model sufficient?**

For the curated registry: **yes**, with two small additive fields — `aliases: string[]`
and `externalIds: {arxiv?, doi?, oeis?, erdos?, lean?}` — which improve deterministic
matching and break nothing. It is *not* sufficient to express claims and evidence
separately, which is exactly why those belong in the automation layer for now.

> **Should problems / claims / evidence / observations become separate entities?**

Yes — in the automation layer, now; in the public model, not yet (§2.3).

> **Should the initial implementation preserve the public data model and add a parallel
> observation layer instead of migrating?**

**Yes, unambiguously.** This is the single most important scoping decision in the plan and
the proposal's instinct is correct (§2.2).

> **Should collection and deployment be separate workflows?**

Yes (§2.8). One direction of causation, no loop guard needed.

---

## 7. Deviations from the brief, for the record

1. Twitter-derived candidates require **external corroboration** to become candidates;
   otherwise they enter the review queue. (§2.1)
2. **No embeddings** in the initial implementation. (§2.4)
3. Raw storage is **minimal-field + hash**, not full payload; full payloads go to
   short-retention Actions artifacts. (§2.5)
4. `CURRENT_STATUS.md` is **not** written by the scheduled workflow. (§2.7)
5. Sprint 1 additionally installs test tooling and fixes the broken `lint` script,
   because the brief's testing requirements are otherwise unachievable. (§1.6)

Everything else follows the brief as written.
