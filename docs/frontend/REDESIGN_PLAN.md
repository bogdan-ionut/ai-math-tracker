# Frontend redesign — plan and sprints

**Written:** 2026-07-26 · **Status:** proposed, not started
**Companion documents:** [automation/CURRENT_STATUS.md](../automation/CURRENT_STATUS.md) ·
[automation/IMPLEMENTATION_ROADMAP.md](../automation/IMPLEMENTATION_ROADMAP.md)

> Every number in this document was measured against `data/results.json` and
> `public/data/*.json` on 2026-07-26, not estimated. Where a claim is an inference rather
> than a measurement, it says so.

---

## 1. Where the frontend actually stands

The page is well made. The typography is distinctive, the dark/light tokens are disciplined,
the charts are hand-built rather than bolted on, and `CumulativeTimeline` in particular makes
a real argument with an honest linear axis and refuses a log scale on principle. That is
better than most data sites manage.

It is also now sitting on a backend it cannot describe, and — more seriously — it makes two
claims the underlying data does not support.

### 1.1 Two things the page currently asserts that the data does not back

**The `claimedAt` / `auditedAt` split carries no information.**
`MethodologyFooter.tsx:27` tells the reader the two dates "are kept separate — an
announcement is not a confirmation". That split is described across this codebase as the
spine of the project. In the data:

| audited records | `auditedAt` equals `claimedAt` | `auditedAt` null |
|---|---|---|
| 17 | **17** | 0 |

Every audit is dated the same day as the claim. Not one differs. The lag distribution the
prose implies is a column of zeros, and `CumulativeTimeline.tsx:33` bins the audited series
by `claimedAt` anyway, so the chart cannot expose the problem either. `auditedAt` appears in
exactly one place in the UI: the detail drawer.

This is not a rendering bug. It is either placeholder data or a curation practice that never
distinguished the two, and the site should not keep advertising a distinction it is not
making.

**The audited tier is mostly unsourced.**

| status | records with a source | records with none |
|---|---|---|
| audited | 5 | **12** |
| reported | 2 | 10 |
| provisional | 5 | 4 |
| disputed | 1 | 1 |

27 of 40 records carry no source URL at all, and the concentration is worst exactly where it
matters most — `audited` is the only tier allowed to be green, and 12 of its 17 records point
at nothing. `build_data.py` warns about this on every single run (defect K6). The site says
nothing.

### 1.2 The dataset is a batch dataset presented as a problem dataset

| | |
|---|---|
| records | 40 |
| problems | 121 |
| top 4 records | **83 of 123 problem-counts (67%)** |

`alphaproof-oeis-44` alone is 44 problems; `star-fleet-26` is 26. Every per-problem figure on
the page is therefore dominated by a handful of batch entries, and the reader is not told.

The clearest casualty is the lab comparison. `LabBars` shows problems credited per lab, which
reads as:

| lab | problems | audited | rate |
|---|---|---|---|
| DeepMind | 53 | 53 | **100%** |
| OpenAI | 57 | 15 | 26% |

That looks like a dramatic institutional difference in verification discipline. It is
substantially an artifact: DeepMind's 53 problems are **four records**, one of which
(`alphaproof-oeis-44`) is 44 audited problems in a single batch. The honest reading is "one
large batch was audited", not "DeepMind audits 53 times more carefully". A chart that invites
the first reading is doing harm, and this is the single most misleading thing on the page
today.

### 1.3 Assessment is far sparser than the page implies

`ImpactConstellation` is the visual centrepiece — a date × impact scatter. But impact is null
unless a human assessed it, and **16 of 40 records are assessed**; `byImpact` is
`{1:2, 2:6, 3:3, 4:2, 5:3}`. A flagship scatter plotting sixteen points, with 24 records
silently absent, is the wrong instrument for this data and quietly overstates how much of the
dataset has been judged.

### 1.4 What the backend now models and the UI cannot say

Sprints 5.1–7 built a discovery pipeline and, with it, a vocabulary the interface does not
speak:

| concept | where it lives | visible in UI? |
|---|---|---|
| Evidence tiers — published / registered / referenced / none | `policy.py` | only inside `SignalsPanel` |
| Reference resolution — resolved / unresolved / **unchecked** | `verify_refs.py` | no |
| `titleAffinity` (a cited paper that is about something else) | `verify_refs.py` | no |
| Review queue + 8 typed reasons | `review.py` | no |
| Provenance chain: observation → candidate → claim → reference | `merge.py` | no |
| `mergedFrom` (two records revealed to be one problem) | `merge.py` | no |
| Curator flow: promote → draft PR, judgements left null | `curate.py` | no |

The most valuable of these is the `unresolved` / `unchecked` distinction. The pipeline is
careful to separate "the paper does not exist" from "we could not ask", a distinction this
project has had to relearn twice. The UI has no way to render it, so the care is invisible.

### 1.5 Delivery defects

| defect | evidence |
|---|---|
| No `og:` or `twitter:` meta tags | `index.html` — 0 occurrences; the site is shared on X |
| ECharts ships as a 564 kB chunk, no code splitting | `pnpm build` output |
| `src/types/result.ts` is hand-synced to `scripts/schema.py` | stated in its own header comment |

---

## 2. Design thesis

**The subject of this site is not what AI solved in 2026. It is how well anyone actually
knows.**

The current page is organised around chronology and volume — how many, by whom, when. That is
the shape of a leaderboard, and the data does not support a leaderboard: it is 40 records
dominated by four batches, a third of them verified, most of them unsourced, and a sixth
assessed. The redesign reorganises the page around **the strength of the evidence** and makes
volume secondary. Every claim on the page should arrive attached to how it is known, and where
that is weak the page should say so before the reader finds out.

This is not a decorative change. It converts the project's biggest liability — an honest
dataset full of gaps — into its subject matter.

---

## 3. The page, in reading order

| # | Section | Purpose | Visual | Data |
|---|---|---|---|---|
| 1 | **Masthead** | State the size and the limits in one breath | Four figures, and a fifth in the same type size: *"12 of 17 audited records carry no source"*. The caveat is not smaller than the boast. | `summary.json` + new `sourceCoverage` |
| 2 | **The evidence bar** | The whole dataset in one 100%-wide stacked bar, by evidence strength, not status | Single horizontal bar, segments: audited-with-source · audited-unsourced · reported · provisional · disputed. Hover reveals counts in both records and problems. | `conjectures.json` |
| 3 | **Records, not problems** | Disarm the batch distortion up front | Small paired bars: 40 records vs 121 problems, with the four batch records marked. One sentence: two thirds of the problem count comes from four entries. | `conjectures.json` `count` |
| 4 | **The verification deficit** | Keep the current chart — it is the best thing on the page | Unchanged stacked linear timeline | unchanged |
| 5 | **Who claimed, who verified** | Replace `LabBars` with something that cannot be misread | Per lab: two bars, **records** and **problems**, audited portion shaded. An explicit note wherever one record supplies most of a lab's total. | `summary.byLab` + record-level counts |
| 6 | **The assessed sixteen** | Stop pretending the scatter is the dataset | Retire `ImpactConstellation` as the centrepiece. Sixteen assessed records become a small ranked strip; the 24 unassessed get a visible "not yet assessed" block of equal weight. | `impact`, `assessment` |
| 7 | **The ledger** | The workhorse — keep, extend | Add an evidence column: tier chip + source presence + reference-resolution state. Sortable by evidence strength. | `conjectures.json` + `references` |
| 8 | **Detail drawer** | Show provenance as a chain | Vertical chain: observation → claim → reference (with resolution state and, when low, `titleAffinity`) → curated record. `mergedFrom` shown when a record absorbed another. | `conjectures.json`, `signals.json` |
| 9 | **Methodology** | Say what the tiers mean and what the gaps are | Keep, but correct the `auditedAt` sentence to describe reality (see F1). | prose |
| 10 | **Unverified signals** | Keep exactly as built | Unchanged: dashed, drab, below the fold, never green | `signals.json` |

---

## 4. Colour and typography discipline

1. **Green (`--good`) means `audited` and nothing else.** No hover state, no accent, no chart
   series, no signal chip may use it. This already holds; it becomes a lint rule (F5).
2. **A second reserved role: absence.** Missing evidence — no source, unresolved reference —
   gets one consistent treatment (a hollow mark / hatched fill), used nowhere else. Absence
   should be recognisable across every chart without a legend.
3. **Unverified material is never saturated.** Signals and candidates stay monochrome.
4. **Batch records are marked** wherever a count above 1 contributes to a figure.
5. Display face for headings, mono for all data. Unchanged — it works.

---

## 5. How each backend concept becomes visible

| concept | surface |
|---|---|
| Evidence tiers | Section 2 bar; ledger column; drawer |
| `resolved` | Drawer shows paper title, date, authors |
| `unresolved` | Ledger evidence column shows a struck reference; never counted as published |
| `unchecked` | **Distinct third state**, rendered as "not yet checked" — never merged with `unresolved` |
| `titleAffinity` | Drawer only, shown when low, worded as a curator hint and never as a verdict |
| Review reasons | Aggregate counts in the methodology section; not per-record |
| Provenance chain | Drawer, section 8 |
| `mergedFrom` | Drawer, one line: "absorbed *id* when a shared identifier revealed one problem" |
| Curator flow | Methodology: one paragraph, that promotion is a human-merged pull request |
| **K6 source gap** | Masthead figure, evidence bar segment, ledger column — three places, unavoidable |

---

## 6. Sprints

Ordered so each ships something usable alone, and nothing waits on later work.
**F1–F3 need no new backend data.**

### F1 — Stop asserting what is not true
**Objective.** Remove the two false claims before building anything on top of them.
**Files.** `MethodologyFooter.tsx` · `build_data.py` · `Masthead.tsx` · `data/results.json` (curation)
**Deliverables.** Correct the `auditedAt` sentence to describe what the data actually shows.
Emit `sourceCoverage` in `summary.json`. Surface the source gap in the masthead. Decide, as a
curation question: is `auditedAt` real and merely equal, or placeholder? If placeholder, null
it — a null is honest, a copied date is not.
**Acceptance.** No sentence on the page is contradicted by `data/results.json`. A test asserts
the source-coverage figure matches the registry.
**Risk.** None technical. It makes the site look worse, which is the point.

### F2 — The evidence bar and the batch disclosure
**Objective.** Reframe the top of the page from volume to evidence.
**Files.** new `EvidenceBar.tsx`, `RecordsVsProblems.tsx` · `App.tsx` · `lib/filters.ts`
**Deliverables.** Sections 2 and 3. Hover gives both record and problem counts everywhere.
**Acceptance.** Both figures reachable for every segment; batch records visibly marked.
**Risk.** Two new charts above the fold; must not push the timeline below it on mobile.

### F3 — Fix the lab comparison
**Objective.** Retire the most misleading chart on the page.
**Files.** `LabBars.tsx` → `LabComparison.tsx` · `Landmarks.tsx`
**Deliverables.** Section 5. Paired record/problem bars; automatic annotation when one record
supplies over half a lab's problems.
**Acceptance.** DeepMind's 100% no longer readable as 53 independent verifications. Test on
the real distribution.
**Risk.** Loses a visually clean bar chart. Correct trade.

### F4 — Evidence in the ledger, provenance in the drawer
**Objective.** Make the pipeline's vocabulary legible per record.
**Files.** `Ledger.tsx` · `ResultDrawer.tsx` · `types/result.ts` · `build_data.py`
**Deliverables.** Sections 7 and 8. `build_data.py` joins verified `references` onto public
records. `unchecked` renders as its own state.
**Acceptance.** A record whose arXiv id did not resolve cannot display as published.
`unresolved` and `unchecked` are never rendered alike — test-enforced.
**Risk.** Needs the pipeline to have written `references`, so it wants live writes on
(blocked by the Gemini free-tier daily cap) or a seeded fixture. Ship against a fixture first.

### F5 — Discipline as tests
**Objective.** Make the colour and honesty rules mechanical.
**Files.** `tests/frontend/` (new, vitest) · `styles/globals.css`
**Deliverables.** A test that fails if `--good` is referenced outside the audited path. A test
that fails if a signal field appears in a curated component. Generate `types/result.ts` from
`public/data/schema.json` instead of hand-syncing.
**Acceptance.** Renaming a status in `schema.py` breaks the frontend build rather than
silently mis-rendering.
**Risk.** New test toolchain in CI.

### F6 — Delivery
**Objective.** The page that gets shared should survive being shared.
**Files.** `index.html` · `vite.config.ts` · `App.tsx`
**Deliverables.** `og:`/`twitter:` tags with a generated preview image. Code-split ECharts
(564 kB) so first paint does not wait on it. Audit contrast, focus states, reduced-motion, and
chart keyboard access in both themes.
**Acceptance.** Lighthouse a11y ≥ 95; no horizontal overflow at 360 px; link preview renders
on X.
**Risk.** The preview image needs a generation step in the deploy workflow.

---

## 7. Out of scope, and why

| excluded | reason |
|---|---|
| Promoting or editing records from the browser | The registry changes only through a reviewed pull request. A write path in the client would put registry-editing code one import from a static page. |
| Showing the review queue per record | It is an operator's working state. Publishing it invites reading unresolved internal questions as claims about mathematics. Aggregate counts only. |
| A search backend | Static hosting. 40 records fit in memory; client-side filtering is enough. |
| Live pipeline status on the page | The site is a record of what is known, not a dashboard of our cron job. |
| Ranking labs by "who is winning" | The data cannot support it, as §1.2 shows. |
