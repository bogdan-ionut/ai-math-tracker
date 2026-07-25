# Current status — automation implementation log

> Living document. Updated by hand (or by the agent doing the work) as implementation
> proceeds. **Deliberately not written by the scheduled workflow** — machine state lives in
> `data/automation/processing_state.json` instead, so this file never accumulates
> meaningless daily diffs. See assessment §2.7.

**Last updated:** 2026-07-25
**Current sprint:** Sprint 3 — Entity matching and shortlist · **completed**
**Next recommended task:** Sprint 4 — safe merge engine and review queue
**Awaiting:** Q2/Q3 in §6; optional manual confirmation of the `teorth` / `erdosproblems` handles

---

## Completed work

### Sprint 0 — Repository assessment and architecture ✅

- Inspected the full repository: data model, Pydantic pipeline, `build_data.py` outputs,
  frontend data loading and metric derivation, deploy workflow, editorial status tiers.
- Wrote `ARCHITECTURE_ASSESSMENT.md` with a critical evaluation of the proposed design.
- Wrote `IMPLEMENTATION_ROADMAP.md` (9 sprints, amended from the brief).
- Wrote this log.
- **No production code changed.** `data/results.json`, `scripts/`, `src/` and
  `.github/workflows/` are untouched.

### Sprint 1 — Test scaffolding + deterministic ingestion ✅

- **Test tooling.** `pytest` added via `scripts/requirements-dev.txt`; `pytest.ini` added.
  The broken `"lint"` script (called an ESLint that was never installed) was **removed**
  rather than pulling in a toolchain this repo does not otherwise use — K3 closed.
- **Config.** `config/twitter_queries.json` (14 topical queries + 6 trusted accounts) and
  `config/automation.json` (lookback, caps, retention, model pinning, policy). Neither
  contains a credential; a test enforces that.
- **Modules** under `scripts/automation/`:
  `urls.py` (canonicalisation, tracking-param stripping, twitter.com→x.com),
  `identifiers.py` (arXiv / DOI / OEIS / Erdős / GitHub / Lean extraction + conflict
  detection), `ids.py` (stable, purely derived ids), `models.py` (`RawTweet`,
  `Observation`, `ProcessingState`), `store.py` (atomic writes, corruption-tolerant
  reads), `twitter.py` (TwitterAPI.io client behind a `SearchClient` protocol +
  offline `FixtureSearchClient`), `ingest.py` (orchestration, `--dry-run`).
- **Tests.** 49 passing, no network, no API keys.
- **Smoke test.** `.github/workflows/smoke-twitter.yml` — manual only, read-only,
  prints counts and field names but never the key or tweet text.

Dry-run over the fixture: 100 fetched → **4 unique** after deduplication (the retweet
collapses onto its original), **3 of 4 carry an external identifier**; the fourth is a
no-link opinion tweet, which is exactly what the corroboration gate is for.

**Live smoke test — passed** (run `30154800586`, 2026-07-25):

| | |
|---|---|
| secret | present, masked in logs (`***`) |
| api calls | 1 |
| tweets returned | 20 |
| normalised / unique | 20 / 20 |
| **with external identifier** | **3 of 20 (15%)** |
| response shape | matches the client's expectations |
| working tree | clean — the job wrote nothing |

The 15% corroboration rate is the important number: it is measured, not assumed, and it
says a pipeline without the corroboration gate would produce roughly six unverifiable
candidates for every corroborated one. Logged in ARCHITECTURE_ASSESSMENT §2.1.

### Sprint 1.5 — Query strategy, syntax probe and calibration ✅

Prompted by a proposal review. Sprint 1's queries were intuition, searched only success
claims, and used handles written from memory.

- **Syntax probed against the live API** (run `30155078770`). All of quoted phrase, `OR`,
  parentheses/implicit AND, `-negation`, `lang:`, `-filter:retweets`, `url:`, `since:` and
  Unicode are supported; a 788-char query is accepted.
- **Rate limiting found and fixed.** The first probe fired 37 back-to-back calls and ~40%
  returned 429. The client now paces requests; re-probe was 36 calls, zero 429s. This would
  have silently dropped whole query families from the daily run.
- **Taxonomy + template grammar** in `config/twitter_discovery.json`; 14 queries, 3 tiers,
  per-family caps, all editable without code changes.
- **Dispute/correction family added** — the significant hole in Sprint 1. Both `disputed`
  records in this dataset are exactly that signal and were previously undiscoverable.
- **Handles probe-verified.** 5 of 8 verified and enabled; `erdosproblems`, `teorth`,
  `XenaProject` returned nothing and are kept **disabled**. A test blocks enabling a handle
  without a `verifiedOn` date.
- **Gold-set calibration** — 12/12 recall, 3/10 noise, both locked by tests.
- **Per-query telemetry** with `uniqueFirstSeen`, so redundant families can be retired on
  evidence rather than opinion.

Calibration caught three things a review would not have: `academic-announcement` matched
nothing (its AI group omitted system names); account queries appeared to match everything
(the offline matcher ignored `from:`); and five system names present in `results.json`
(Fable, MathDyad, Rethlas, Archon, Harmonic) were missing from the taxonomy.

### Sprint 2 — Gemini structured extraction ✅

- **Client** (`gemini.py`) behind a `StructuredModel` protocol, paced and retried like the
  Twitter client, key from env only, never logged or in an exception.
- **Schema** (`extraction_schema.py`): 21 fields, **all optional**, only four required
  (`isRelevant`, `claimType`, `resultType`, `extractionConfidence`). Nothing fabricable is
  required — a forced field invites invention.
- **Prompt** `extraction_v1`, versioned into the cache key. Distinguishes *claim* from
  *evidence* from *dispute*, and forbids inventing identifiers.
- **Hallucination guard** — identifiers the model reports are cross-checked against our own
  regexes over the source text; unverifiable ones are discarded with a warning, and our
  canonical form always wins over the model's.
- **Cache** keyed on `(text hash, promptVersion, model)` — second run costs zero calls.
- **Failure is never emptiness** — malformed JSON, schema violation, timeout and 5xx all
  mark `extraction_failed` and keep the observation for reprocessing.
- 47 tests; 120 total.

**Live smoke test passed** (run `30155637877`, `gemini-3.6-flash`, 3 API calls):

| Case | Result |
|---|---|
| Real Graffiti 154 post | ✅ relevant · `new_result` / `counterexample` · problem, model (Devin) and org (Cognition) all correct · confidence 0.95 |
| Proof-of-work crypto post | ✅ rejected as `unrelated`, confidence 1.0 |
| Unsourced "AI settled Erdős unit distance" | ✅ read as a claim, **no identifier invented** |

Two bugs the work surfaced:

1. `load_prompt` was shipping the file's documentation header to the model — and that
   header lists the engagement vocabulary the prompt exists to avoid. Now only the
   SYSTEM/USER sections go over the wire. Caught by a test, not by review.
2. The live output kept both `cognition/graffiti-lean` and
   `https://github.com/cognition/graffiti-lean` as separate identifiers, because the model
   returned a URL where our regex produced a slug. One identifier looking like two would
   silently weaken deterministic matching. The guard now folds onto our canonical form.

### Sprint 3 — Entity matching and shortlist ✅

- **K4/K5 closed.** `scripts/backfill_identifiers.py` (a curator action, not automation)
  added `aliases` and `externalIds` to all 40 curated records, derived only from fields
  already present. 24/40 now carry identifiers; `data/automation/aliases.json` holds the
  alias and identifier indexes.
- **`matching.py`** resolves in strict order: deterministic identifier → alias → lexical
  shortlist. A certain match **never** costs a model call.
- **Conflict is a hard exclusion.** A record whose identifier disagrees with the
  observation is removed from every later phase.
- **`judge_v1` prompt** with the seven decision values; the judge sees a capped shortlist
  and is told to prefer `insufficient_information` over a guess.
- **Judge payload is minimal** — no engagement data, and no editorial field
  (`impact`, `assessment`, `auditNotes`, `confidence`) ever reaches it. Identity is the
  judge's question; merit is a human's.
- 27 tests; 147 total.

Two bugs the work surfaced, both caught by tests rather than review:

1. **The backfill made one identifier point at two records.** `erdos:1196` resolved to both
   `erdos-1196` and `erdos-1217`, because the #1217 record's *description* says "same method
   as #1196". Identity is now derived from title and `erdosNumber` only — never free text
   that may cite another problem. A test asserts no identifier maps to two records.
2. **A conflicting identifier was being overridden by name similarity.** An observation
   carrying Erdős #999 matched `erdos-728` at lexical score 100 and was returned as an
   unambiguous match — precisely the failure the design exists to prevent. Conflict now
   excludes the record entirely rather than merely annotating the outcome.

---

## Remaining work

Sprints 4–8 in `IMPLEMENTATION_ROADMAP.md`, all `planned`.

---

## Decisions made

| # | Decision | Rationale |
|---|---|---|
| D1 | Preserve `data/results.json`; add a **parallel** `data/automation/` layer | Frontend derives every metric from the flat array; migrating now would mean rewriting six charts for no user-visible gain (§2.2) |
| D2 | Problem/Claim/Evidence modelled in the **automation layer only** | Gives the entity-resolution semantics without a public schema migration (§2.3) |
| D3 | **No embeddings** initially | 40 curated records; identifiers + aliases + lexical similarity suffice; review queue is the correct fallback (§2.4) |
| D4 | Twitter candidates require **external corroboration** to leave the review queue | X is the lowest-precision source and two existing `disputed` records originate there (§2.1) |
| D5 | Raw storage = minimal fields + text hash; full payloads → Actions artifacts | Avoids republishing third-party content and bloating git history (§2.5) |
| D6 | **Field allowlist** enforced in the merge engine, not only in the schema | The schema would accept `impact` + `assessment` written together; the guardrail belongs where mutations are decided (§2.6) |
| D7 | `CURRENT_STATUS.md` is never written by the cron job | Prevents 365 noise commits/year; machine state goes to `processing_state.json` (§2.7) |
| D8 | Two workflows, acyclic: `discover.yml` commits → `deploy-pages.yml` deploys | Deploy has no commit step, so no loop guard is needed (§2.8) |
| D9 | Cron `20 4 * * *` UTC; DST drift documented, not solved | GitHub Actions cron is UTC-only (§2.9) |
| D10 | A new **Sprint 6** adds arXiv / erdosproblems / GitHub sources before the optional frontend | Higher-precision sources materially improve D4's corroboration gate |
| D11 | Gemini pinned to **`gemini-3.6-flash`** for both extraction and judging | User decision, 2026-07-25. Right tier for structured output over one short post and a ≤5-item shortlist; asserted by a test so it cannot drift |
| D12 | Retweets are attributed to the **original** tweet id | An RT and its source are one signal, not two — deduplication happens before any model call |
| D13 | `lookbackHours` is overridable per run | Fixture tests must not depend on today's date; also satisfies the brief's "configurable lookback" |
| D14 | The broken `lint` script was **removed**, not repaired | ESLint was never a dependency; adding a linter is a separate decision, not a side effect of this work |
| D15 | Search syntax is **probed**, not assumed | An operator working on x.com is no evidence TwitterAPI.io supports it; all 10 were verified live |
| D16 | Requests are **paced** (1.5s), not just retried | Measured ~40% 429s on a 37-call burst; retry alone would have masked intermittent family loss |
| D17 | **One** taxonomy file, not the nine proposed | At this size a single file reviews better in a diff and cannot drift out of sync; the "editable without code changes" requirement is met either way |
| D18 | A **dispute/correction** family is Tier 1 | Both `disputed` records here are that signal; Sprint 1 searched only success claims and could not have found either |
| D19 | Trusted accounts require **probe verification** to be enabled | Sprint 1 shipped six handles from memory; three of them return nothing. Test-enforced |
| D20 | Known false positives are **accepted**, not excluded by keyword | Recall in search, precision in the classifier. `-counterexample` would gut two of the best families |
| D21 | Only 4 of 21 extraction fields are **required** | A required field the post does not support is an invitation to invent one |
| D22 | Model-reported identifiers are **cross-checked** against our regexes, and our canonical form wins | An invented arXiv id would be treated as a hard deterministic match and merge unrelated problems |
| D23 | Prompt files are documentation **and** prompt; only the `## SYSTEM` section onward is sent | The header discusses engagement metrics, which the prompt must never mention |
| D24 | Curated identity is derived from **title + erdosNumber only**, never the description | A description may cite another problem; treating that as identity made one identifier point at two records |
| D25 | An identifier conflict **excludes the record from all matching phases** | Otherwise a fuzzy title match can override an explicit disagreement — Erdős #999 matched #728 at score 100 before this |
| D26 | The judge sees no editorial field and no engagement data | It decides identity, never merit |

---

## Deviations from the original plan

1. **Sprint order changed** — test scaffolding pulled into Sprint 1; a new source-expansion
   sprint inserted at 6; frontend visibility moved to 7 and kept optional.
2. **No embeddings** (brief listed them as optional; assessment declines them for now).
3. **Corroboration gate** added on top of the brief's merge rules.
4. **Raw payload retention** narrowed beyond the brief's "do not commit uncontrolled
   amounts".
5. **`CURRENT_STATUS.md` excluded from workflow writes** (brief said "only when
   appropriate"; the reliable reading of that is "never, from cron").

All deviations are argued in `ARCHITECTURE_ASSESSMENT.md` §7.

---

## Known issues / pre-existing gaps

| # | Issue | Blocking? | Plan |
|---|---|---|---|
| K1 | ~~No Python test runner~~ | — | ✅ Closed in Sprint 1 (pytest, 49 tests) |
| K2 | No JS test runner (`vitest` absent) | Blocks frontend tests only | Sprint 7, when there is frontend behaviour to test |
| K3 | ~~Broken `lint` script~~ | — | ✅ Closed in Sprint 1 (removed) |
| K4 | ~~No `aliases` field~~ | — | ✅ Closed in Sprint 3 (backfilled) |
| K5 | ~~No structured external-identifier field~~ | — | ✅ Closed in Sprint 3 (24/40 carry identifiers; the rest have no source to derive from — see K6) |
| K6 | Only **13 of 40** records carry a source URL | Weakens corroboration matching | Backfill is a human task; not automation's job |
| K8 | `teorth` and `erdosproblems` handles return no results | Loses two high-value trusted accounts | Confirm the correct handles by hand, then enable |
| K9 | Gold set is fitted to wordings we already know | 100% recall is a floor, not proof | Add positives whenever a real miss is observed |
| K7 | `resultType` and `resolution` are near-duplicate fields | Cosmetic | Out of scope; automation writes neither |

---

## Tests

**Currently passing:** 147 / 147 (`python -m pytest`) — no network, no API keys required.
**Currently failing:** none.
**Build health:** `python scripts/build_data.py` ✅ · `pnpm build` ✅ · live deploy ✅
**`data/results.json`:** byte-identical — asserted by `test_curated_results_are_never_touched`.

---

## Required manual user actions

| # | Action | Needed by |
|---|---|---|
| U1 | ~~Add repository secret `TWITTERAPI_IO_KEY`~~ | ✅ Done 2026-07-25 |
| U2 | ~~Add repository secret `GEMINI_API_KEY`~~ | ✅ Done 2026-07-25 |
| U5 | ~~Run the TwitterAPI.io smoke test~~ | ✅ Passed 2026-07-25 (run 30154800586) |
| U3 | Confirm Actions has **write** permission for the collector (Settings → Actions → General → Workflow permissions → Read and write) | Sprint 5 |
| U4 | Answer the open questions in §6 | Sprint 1 |

> Secrets are **not** required for Sprints 1–4: all tests and the dry-run path use fixtures.

---

## Open questions for the user

| # | Question | Default if unanswered |
|---|---|---|
| Q1 | Do you accept the **corroboration gate** (D4) — a tweet with no arXiv/DOI/Lean/Erdős identifier goes to the review queue rather than becoming a candidate? | Yes, apply it |
| Q2 | Should the public site ever show unverified signals (Sprint 7), given this project's whole premise is filtering hype? | Build it, keep it behind a flag, decide after seeing the false-positive rate |
| Q3 | Is committing **tweet text** to a public repo acceptable, or should only the hash + link be stored? | Store excerpt + hash; make it configurable |
| Q4 | Should Sprint 6 (arXiv / erdosproblems) be pulled **ahead**? The live smoke test measured only **15% corroboration** on X, which strengthens the case. | Follow the brief for now; revisit after a week of real data |

---

## Next recommended task

**Sprint 3 — entity matching and shortlist.** Extraction now yields a canonical problem
name, aliases and verified identifiers; matching decides *which existing problem* an
observation is about. In order:

1. Seed `data/automation/aliases.json` from `title` + `erdosNumber` in `results.json`,
   and add the additive `aliases` / `externalIds` fields to curated records (K4, K5).
2. Deterministic identifier matching first — arXiv, DOI, OEIS, Erdős, Lean repo, canonical
   URL. A deterministic hit must **skip the judge entirely**.
3. Alias lookup, then normalised-title similarity (RapidFuzz). No embeddings (D3).
4. Shortlist capped at 5; `prompts/judge_v1.md` with the seven decision values.
5. Judge invoked **only** on ambiguous shortlists; failure routes to review, never guesses.
6. Tests: exact identifier resolves with zero model calls; conflicting identifiers never
   merge; judge called exactly once on ambiguity.
