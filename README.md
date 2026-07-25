# The Year the Theorems Fell — AI × Mathematics tracker

A living, static web app that tracks open mathematics problems solved, refuted, or
advanced with AI in 2026 — **tiered by how well each claim is verified** (audited /
reported / provisional / disputed). Built to run on GitHub Pages with zero backend.

## Stack

- **Frontend:** Vite · React · TypeScript · Tailwind · Apache ECharts (SVG) · Motion
- **Data pipeline:** Python · Pydantic (schema validation, dedup, metrics)
- **Hosting:** GitHub Pages via GitHub Actions

Charts are ECharts where a standard form fits (cumulative timeline, lab bars) and
bespoke React/SVG for the two signature views (per-lab timeline lanes, recent-window
waffle) so they keep the editorial look.

## What it grades

Two independent axes, because "an AI solved it" answers neither question on its own:

| Axis | Values | Question it answers |
|---|---|---|
| **Status** | audited · reported · provisional · disputed | *How well verified is this?* |
| **Impact** | 1–5, or unscored | *Did it actually change anything?* |

Every impact score carries a written `assessment` — the schema **rejects a score
without one**. Unjudged results stay `impact: null` and render as "not yet assessed",
never as low-impact. Disputed results (a rediscovery, or a claim whose underlying
conjecture doesn't exist) are kept on the record but excluded from headline totals.

## Data model

The source of truth is [`data/results.json`](data/results.json), validated against
[`scripts/schema.py`](scripts/schema.py). Each record is one distinct problem (a batch,
like the 44 OEIS conjectures, is one record with a `count` and optional `members`).

Invariants the pipeline enforces:

- an **audited** result must carry an `auditedAt` date — an announcement is never
  rendered as a confirmation;
- an **impact** score must carry an `assessment`;
- a **disputed** result must say why (`auditNotes` or `supersededBy`);
- `members`, when listed, must account for `count`;
- ids are unique.

## Two data layers, and what may write to each

| Layer | Owner | Written by |
|---|---|---|
| `data/results.json` — the curated registry the site renders | **human curator** | people only |
| `data/automation/**` — observations, candidates, review queue | discovery pipeline | automation |

**Automation can never write the curated registry.** Not a field, not a record, not the
ordering. `policy.assert_registry_untouched` fails the run if the file moves at all, and a
test asserts the whole decision sweep leaves it byte-identical.

### Updating the curated registry (human)

1. Edit `data/results.json` — add results, promote provisional → audited, record a dispute.
2. `python scripts/build_data.py` — validates and regenerates `public/data/*.json`.
3. Commit & push to `main` → GitHub Actions rebuilds and redeploys.

### The discovery pipeline (automated)

A daily workflow searches X for AI-mathematics claims, extracts them with Gemini, matches
them against the registry, and files them as **candidates** or **review-queue entries**.
Candidates are proposals: they are never presented as verified, never counted in any
headline metric, and never promoted into the registry without a human.

A social post with no external identifier (arXiv, DOI, OEIS, Erdős number, Lean or GitHub
artifact) does not become a candidate at all — it goes to review. That gate exists because
the base rate was measured: of 20 live tweets matching our queries, **3 carried any external
identifier**.

> **Status: the scheduled run does not write yet.** `schedule.dryRunOnSchedule` is `true`
> while the pipeline is calibrated end to end. See
> [docs/automation/CURRENT_STATUS.md](docs/automation/CURRENT_STATUS.md).

Design, verification and roadmap live in [`docs/automation/`](docs/automation/).

## Develop

```bash
pnpm install
python -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
.venv/bin/python scripts/build_data.py   # generates public/data/
pnpm dev
```

## Deploy to GitHub Pages

1. Push this repo to GitHub (repo name becomes the base path).
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**.
3. Push to `main` (or run the workflow manually). The site publishes to
   `https://<user>.github.io/<repo>/`.

If your repo name differs from `ai-math-tracker`, the workflow already sets
`VITE_BASE=/<repo>/` automatically; for local production previews, pass it yourself.
