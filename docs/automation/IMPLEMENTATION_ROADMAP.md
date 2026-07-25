# Implementation roadmap — automated discovery pipeline

Sprint sequence refined from the brief after the repository assessment. Changes from the
proposed sequence are flagged **[amended]** with a reason.

**Statuses:** `planned` · `in progress` · `blocked` · `completed`

| Sprint | Title | Status |
|---|---|---|
| 0 | Repository assessment and architecture | **completed** |
| 1 | Test scaffolding + deterministic ingestion | **completed** |
| 1.5 | Query strategy, syntax probe and calibration **[amended]** | **completed** |
| 2 | Gemini structured extraction | **completed** |
| 3 | Entity matching and shortlist | **completed** |
| 4 | Safe merge engine and review queue | **completed** |
| 5 | Scheduled GitHub Actions workflow | **completed** |
| 6 | Additional high-precision sources **[amended]** | planned |
| 7 | Frontend candidate visibility (optional) | planned |
| 8 | Hardening and operational documentation | planned |

> **[amended]** The brief's Sprint 6 was "frontend candidate visibility". A sprint for
> **additional sources** (arXiv, erdosproblems.com, Tao's AI-contributions wiki) has been
> inserted ahead of it, per §2.1 of the assessment: those sources are higher-precision
> than X and materially improve the corroboration gate that Twitter promotion depends on.
> Frontend visibility moves to Sprint 7 and remains optional.

---

## Sprint 0 — Repository assessment and architecture · `completed`

**Objective.** Understand the repository, critically evaluate the proposal, and record
the plan before any production change.

**Files changed.** `docs/automation/ARCHITECTURE_ASSESSMENT.md`,
`docs/automation/IMPLEMENTATION_ROADMAP.md`, `docs/automation/CURRENT_STATUS.md`.

**Deliverables.** All three documents, containing a critical evaluation, an explicit
answer on the schema-migration question, and a documented data-layer contract.

**Validation.** `pnpm build` and `python scripts/build_data.py` still succeed; live site
unchanged; `git diff` touches only `docs/`.

**Acceptance criteria.** ✅ No production behaviour changed. ✅ Assessment names concrete
weaknesses, not generic ones. ✅ Migration question answered explicitly.

**Dependencies.** None. **Risks.** None. **Rollback.** Delete `docs/automation/`.

---

## Sprint 1 — Test scaffolding + deterministic ingestion · `completed`

**Objective.** Get raw Twitter data into a normalised, deduplicated, stably-identified
observation store — with zero model calls — and make the repository testable.

> **[amended]** Test tooling is pulled forward from the brief's later sprints. The brief
> mandates a large test suite; none of it can run today (assessment §1.6).

**Files expected to change**
```
scripts/requirements.txt              + pytest, httpx, rapidfuzz
package.json                          fix the broken "lint" script
config/twitter_queries.json           NEW
scripts/automation/__init__.py        NEW
scripts/automation/models.py          NEW  Observation, RawTweet (Pydantic)
scripts/automation/urls.py            NEW  canonicalisation, tracking-param stripping
scripts/automation/identifiers.py     NEW  arXiv / DOI / OEIS / Erdős / Lean extraction
scripts/automation/ids.py             NEW  stable id derivation
scripts/automation/twitter.py         NEW  TwitterAPI.io client behind an interface
scripts/automation/ingest.py          NEW  fetch → normalise → dedupe → persist
scripts/automation/store.py           NEW  atomic read/write JSON helpers
data/automation/*.json                NEW  seeded empty
tests/automation/…                    NEW  + fixtures
```

**Deliverables.** Query config; API client with timeouts, retries and rate-limit backoff;
URL canonicalisation; identifier extraction; stable observation ids
(`sha256("twitter:" + tweet_id)`); exact deduplication; atomic writes; `--dry-run`;
processing-state persistence; fixtures + tests.

**Validation.** `pytest tests/automation -q` green with **no API keys present**;
`python -m scripts.automation.ingest --dry-run --fixtures` reports proposed mutations and
writes nothing; rerunning against the same fixture produces **zero** new records.

**Acceptance criteria.** Idempotent reruns. No network access in tests. `results.json`
byte-identical. `build_data.py` and `pnpm build` still pass.

**Dependencies.** Sprint 0. **Risks.** TwitterAPI.io response shape may differ from the
docs — mitigated by fixture-driven development and a tolerant parser.
**Rollback.** Delete `scripts/automation/` and `data/automation/`; nothing else reads them.

---

## Sprint 1.5 — Query strategy, syntax probe and calibration · `completed` **[amended, new]**

**Objective.** Replace hand-written intuition queries with a measured, calibrated,
configuration-driven search strategy — before the daily automation starts spending money on
the wrong searches.

> **[amended]** Not in the original plan. Added after a proposal review: Sprint 1's queries
> were written from intuition, searched only for *success* claims, and used six account
> handles written from memory. The live smoke test (15% corroboration) showed recall was the
> binding constraint.

**Files.** `.github/workflows/probe-twitter-syntax.yml`, `scripts/automation/probe_syntax.py`,
`config/twitter_discovery.json` (replaces `config/twitter_queries.json`),
`scripts/automation/query_builder.py`, `scripts/automation/calibrate.py`,
`tests/automation/fixtures/gold_set.json`, `tests/automation/test_query_strategy.py`,
`docs/automation/TWITTER_QUERY_STRATEGY.md`, `scripts/automation/twitter.py` (pacing),
`scripts/automation/ingest.py` (taxonomy + telemetry).

**Deliverables.** Operator support verified against the live API; request pacing after
measuring 429s; keyword taxonomy with a template grammar; 14 queries across 3 tiers with
per-family caps; dispute/verification/registry/arXiv families; probe-verified trusted
accounts; gold-set calibration harness; per-query telemetry; strategy document.

**Validation.** `python -m scripts.automation.calibrate` → 12/12 recall, 3/10 noise.
73 tests green, no network, no keys. `results.json` byte-identical.

**Acceptance criteria.** ✅ Syntax verified, not assumed. ✅ No handle enabled without probe
verification (test-enforced). ✅ Dispute language searched. ✅ Recall and noise locked by tests.
✅ Noisy families disableable from config alone.

**Dependencies.** Sprint 1. **Risks.** Gold-set circularity — documented as blind spot 5.
**Rollback.** Re-enable the previous flat query list; the ingest interface is unchanged.

---

## Sprint 2 — Gemini structured extraction · `completed`

**Objective.** Turn observation text into validated structured data, cached and versioned.

**Files.** `scripts/automation/gemini.py`, `extraction.py`, `prompts/extraction_v1.md`,
`models.py` (+ `ExtractionResult`), tests + mocked responses.

**Deliverables.** Gemini client with timeout/retry; strict Pydantic `ExtractionResult`
(all fields nullable — the model must never be forced to invent an identifier);
`promptVersion` + `modelVersion` recorded on every extraction; cache keyed on
`(observationId, promptVersion, modelVersion)`; failure marks the observation
`extraction_failed` and **keeps the raw observation** for later reprocessing.

**Validation.** Mocked-response tests for success, malformed JSON, schema-violating
output, timeout, and rate-limit. Cache test: a second run makes **zero** API calls.

**Acceptance criteria.** No unvalidated model output ever reaches disk. Engagement metrics
are **not** included in the prompt. Extraction failure is non-destructive.

**Dependencies.** Sprint 1. **Risks.** Structured-output drift between Gemini versions —
mitigated by pinning the model id and versioning the schema.
**Rollback.** Extraction is a separate stage; disable it and observations still accumulate.

---

## Sprint 3 — Entity matching and shortlist · `completed`

**Objective.** Decide *what an observation is about*, cheaply and deterministically first.

**Files.** `scripts/automation/matching.py`, `aliases.py`,
`prompts/judge_v1.md`, `data/automation/aliases.json`, tests.

**Deliverables.** Deterministic identifier matching (arXiv, DOI, OEIS, Erdős number, Lean
repo, canonical URL) → alias lookup → normalised-title similarity (RapidFuzz).
Shortlist capped at 5 candidates. Relationship-judge schema with the seven decision
values. Judge invoked **only** on ambiguous shortlists. **No embeddings** (assessment §2.4).

**Validation.** Table-driven tests: exact Erdős-number match resolves without a model call;
alias hit resolves without a model call; ambiguous case produces a shortlist and *calls the
mocked judge exactly once*; judge failure routes to review.

**Acceptance criteria.** Deterministic identifiers always beat model output. Judge is never
called when a deterministic match exists. Conflicting explicit identifiers **never** merge.

**Dependencies.** Sprint 2. **Risks.** Alias table cold-start — seeded from existing
`title` + `erdosNumber` values in `results.json`.
**Rollback.** Fall back to "everything ambiguous → review queue".

---

## Sprint 4 — Safe merge engine and review queue · `completed`

**Objective.** Apply decisions deterministically, in Python, with a field allowlist.

**Files.** `scripts/automation/merge.py`, `review.py`, `policy.py`, tests.

**Deliverables.** One handler per decision value (per the brief's table). **Field allowlist**
(assessment §2.6): automation may never write `status: audited`, `auditedAt`, `impact`,
`assessment`, `confidence`, `auditNotes`, `provenanceNote`, and may never delete a curated
record. **Corroboration gate** (assessment §2.1): a Twitter-only observation with no
external identifier becomes a review-queue entry, not a candidate. Review queue with typed
reasons. Conflict preservation — both claims retained, neither overwritten.

**Validation.** Tests for every decision branch; `test_no_automatic_audited_promotion`;
`test_no_automatic_impact_write`; `test_curated_results_unchanged` (hash `results.json`
before/after a full pipeline run); idempotent-rerun test; corrupted-JSON handling.

**Acceptance criteria.** A full fixture run leaves `data/results.json` **byte-identical**.
Every uncertain case is recoverable from `review_queue.json`.

**Dependencies.** Sprint 3. **Risks.** Over-eager merging — mitigated by defaulting every
unhandled case to review. **Rollback.** `candidates.json` / `review_queue.json` are
additive; deleting them restores the prior state.

---

## Sprint 5 — Scheduled GitHub Actions workflow · `completed`

**Objective.** Run daily, safely, without loops or noise commits.

**Files.** `.github/workflows/discover.yml` (new), `docs/automation/OPERATIONS.md` (new).
`deploy-pages.yml` is **not** modified.

**Deliverables.** `schedule` (`20 4 * * *` UTC = 07:20 EEST / 06:20 EET, DST drift
documented) + `workflow_dispatch` with a `dry_run` input. Secret validation that fails
fast **without printing values**. `concurrency: group: discover, cancel-in-progress: false`.
`contents: write` on the collector only. Commit only on meaningful data change. Per-run
caps logged into `processing_state.json`.

**Validation.** `workflow_dispatch` with `dry_run: true` completes and commits nothing.
A real run commits only `data/automation/**` and triggers exactly one deploy.
A forced API failure leaves all existing JSON intact.

**Acceptance criteria.** No commit loop. No secret in logs. Live site still deploys.

**Dependencies.** Sprint 4 + the two user-provided secrets.
**Risks.** Scheduled-workflow disablement after 60 days of repo inactivity (GitHub
behaviour) — documented in OPERATIONS.md.
**Rollback.** Disable the workflow in the Actions tab; deployment is unaffected.

---

## Sprint 6 — Additional high-precision sources · `planned` **[amended, new]**

**Objective.** Reduce dependence on X and strengthen the corroboration gate.

**Files.** `scripts/automation/sources/{arxiv,erdosproblems,github}.py`,
`config/sources.json`, tests.

**Deliverables.** arXiv API client (free, structured); erdosproblems.com + Tao's
`teorth/erdosproblems` AI-contributions wiki reader; GitHub search for Lean artifact repos.
All emit the **same `Observation` shape** as Twitter, so steps 3–7 are unchanged.

**Validation.** Fixture tests per source; a cross-source corroboration test (a Twitter
observation plus a matching arXiv observation resolves to one candidate, corroborated).

**Acceptance criteria.** Adding a source requires no change to matching or merge code.

**Dependencies.** Sprint 5. **Risks.** HTML scraping fragility for erdosproblems — prefer
its structured endpoints / the wiki's markdown. **Rollback.** Per-source enable flag.

---

## Sprint 7 — Frontend candidate visibility (optional) · `planned`

**Objective.** Surface unverified signals without contaminating curated metrics.

**Files.** `scripts/build_data.py` (emit `public/data/candidates.json` — **separately**),
`src/hooks/useCandidates.ts`, `src/components/SignalsFromX.tsx`, `src/app/App.tsx`.

**Deliverables.** A visually and semantically separate "Signals from X — unverified"
section: unverified badge, source, author, discovery date, original post date, extracted
problem name, relationship to an existing result when known, review status, link to source.

**Validation.** A test asserting `computeMetrics` output is **identical** with and without
candidates loaded. Candidates must not appear in KPIs, the constellation, the deficit
chart, the lab charts or the ledger.

**Acceptance criteria.** Zero effect on any curated number. Clearly not presented as fact.

**Dependencies.** Sprint 4 (data) — deliberately gated on observed false-positive rate.
**Risks.** Publishing unverified claims under this project's name is a reputational risk;
this is precisely why it is last and optional. **Rollback.** Remove the component.

---

## Sprint 8 — Hardening and operational documentation · `planned`

**Objective.** Make it operable by a human who has forgotten how it works.

**Deliverables.** End-to-end fixture run; API-call/cost metrics in `processing_state.json`;
`OPERATIONS.md` covering manual run, dry run, inspecting the review queue, recovering from
a failed run, disabling automation, and rotating secrets; final documentation sync.

**Validation.** A fresh clone can run the full dry-run path with no secrets.

**Acceptance criteria.** Every question in the brief's "final report" list is answered by a
document in the repository, not only by a chat message.

---

## Cross-cutting invariants (every sprint)

1. `data/results.json` is never written by automation.
2. `scripts/build_data.py` reads **only** `results.json`.
3. Tests never require real API keys.
4. Every write is atomic (`*.tmp` → `os.replace`).
5. An API failure never replaces good data with empty data.
6. `pnpm build` and `python scripts/build_data.py` pass at the end of every sprint.
7. The live GitHub Pages deployment keeps working.
