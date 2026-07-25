# Current status — automation implementation log

> Living document. Updated by hand (or by the agent doing the work) as implementation
> proceeds. **Deliberately not written by the scheduled workflow** — machine state lives in
> `data/automation/processing_state.json` instead, so this file never accumulates
> meaningless daily diffs. See assessment §2.7.

**Last updated:** 2026-07-25
**Current sprint:** Sprint 0 — Repository assessment and architecture · **completed**
**Next recommended task:** Sprint 1 — test scaffolding + deterministic ingestion
**Awaiting:** user decision on the open questions in §6 below

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

---

## Remaining work

Sprints 1–8 in `IMPLEMENTATION_ROADMAP.md`, all `planned`. Nothing started.

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
| K1 | No Python test runner (`pytest` absent) | Blocks all mandated tests | Sprint 1 |
| K2 | No JS test runner (`vitest` absent) | Blocks frontend tests | Sprint 1 (install) / Sprint 7 (use) |
| K3 | `package.json` `"lint"` script calls ESLint, which is **not installed** — the script fails | Blocks CI linting | Sprint 1: install ESLint or remove the script |
| K4 | No `aliases` field on curated records | Weakens alias matching | Sprint 1: additive field, seeded from titles |
| K5 | No structured external-identifier field (arXiv/DOI/OEIS) | Weakens deterministic matching | Sprint 1: additive `externalIds` object |
| K6 | Only **13 of 40** records carry a source URL | Weakens corroboration matching | Backfill is a human task; not automation's job |
| K7 | `resultType` and `resolution` are near-duplicate fields | Cosmetic | Out of scope; automation writes neither |

---

## Tests

**Currently passing:** none — no test suite exists yet (K1, K2).
**Currently failing:** none.
**Build health:** `python scripts/build_data.py` ✅ · `pnpm build` ✅ · live deploy ✅

---

## Required manual user actions

| # | Action | Needed by |
|---|---|---|
| U1 | Add repository secret **`TWITTERAPI_IO_KEY`** | Sprint 5 (first real run) |
| U2 | Add repository secret **`GEMINI_API_KEY`** | Sprint 5 (first real run) |
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
| Q4 | Should Sprint 6 (arXiv / erdosproblems) be pulled **ahead** of the Twitter work, given it is higher-precision and cheaper? | No — follow the brief; Twitter first |

---

## Next recommended task

**Sprint 1.** Concretely, in order:

1. Add `pytest` + `httpx` + `rapidfuzz` to `scripts/requirements.txt`; fix or remove the
   broken `lint` script.
2. Create `config/twitter_queries.json` from the brief's query list.
3. Implement `models.py`, `urls.py`, `identifiers.py`, `ids.py`, `store.py`.
4. Implement `twitter.py` behind an interface, with recorded fixtures.
5. Implement `ingest.py` with `--dry-run`.
6. Tests: dedup, URL canonicalisation, identifier extraction, stable ids, idempotent rerun,
   corrupted JSON, empty API response.
7. Verify `results.json` is byte-identical and `pnpm build` still passes.
