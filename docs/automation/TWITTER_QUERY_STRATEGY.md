# Twitter/X discovery — query strategy

**Status:** implemented and calibrated (Sprint 1.5, 2026-07-25).
**Config:** [`config/twitter_discovery.json`](../../config/twitter_discovery.json) — editable
without touching pipeline code.
**Tools:** `python -m scripts.automation.query_builder` (inspect) ·
`python -m scripts.automation.calibrate` (measure).

---

## 1. Verified search syntax — measured, not assumed

The brief was right to insist on this: an operator working on the public X website is no
evidence that TwitterAPI.io supports it. Every operator below was probed against the live
API (`.github/workflows/probe-twitter-syntax.yml`, run **30155078770**).

| Operator | Verdict | Evidence |
|---|---|---|
| quoted phrase `"open problem"` | ✅ supported | 19/20 results contained the literal phrase |
| `OR` | ✅ supported | 20 results |
| parentheses + implicit `AND` | ✅ supported | 16/20 contained terms from **both** groups |
| `-term` negation | ✅ supported | 0/20 contained the excluded term |
| `-filter:retweets` | ✅ supported | 0/20 were retweets |
| `lang:en` | ✅ supported | 20 results |
| `url:arxiv.org` | ✅ supported | 20 results |
| `since:YYYY-MM-DD` | ❌ **applied wrongly** | asked for 07-19…07-21, got 20 tweets all dated 07-22 — see §5c |
| `since_time:`/`until_time:` (unix) | ✅ supported | past window returned only in-window dates; a future window returned nothing |
| Unicode (`Erdős`) | ✅ supported | 20 results — no ASCII folding needed |
| ≥ 513-character query | accepted, **0 results** | see §5b — the silent limit |

Pagination returns **20 tweets per page**; `queryType` is `Latest` or `Top`.

### The finding that changed the client

The first probe fired 37 calls back-to-back and **~40% returned HTTP 429**, on alternating
requests. Retrying alone would have masked this; the daily run issues ~14 queries and would
have hit the same wall intermittently, losing whole families at random.

The client now **paces** requests (`minRequestIntervalSeconds`, default 1.5s) and escalates
the pause specifically on 429. Re-probing with pacing: **36 calls, zero 429s.**

---

## 2. Taxonomy

One configuration file rather than the nine proposed. At this size a single file is easier
to review in a diff and cannot drift out of sync with itself; the requirement that matters
— *keywords editable without changing ingestion logic* — is met either way.

**Clusters** (reusable term groups): `ai`, `systems`, `provers`, `objects`,
`resolutionVerbs`, `academicPhrases`, `verificationTerms`, `disputeTerms`, `registries`,
`publication`, `negative`.

**Families** combine clusters via a small template grammar:

```json
{ "template": { "all": ["disputeTerms"], "any": ["ai", "systems"] } }
```

`all` → each cluster becomes its own AND-ed OR-group. `any` → the listed clusters are
merged into **one** OR-group. `andAny` → a second merged group.

> **A bug this grammar caught.** The disputes family was first written as
> `any: ["ai","systems","objects"]`, which merges *objects* into the AI group — so
> "already known theorem" would have matched with no AI involvement at all. Tightened to
> `any: ["ai","systems"]`. The same fix applied to `problem-registries`.

### System names are reconciled against the data

The `systems` cluster was seeded by hand and then checked against the `model` field of
every record in `data/results.json`. That reconciliation added **Fable, MathDyad, Rethlas,
Archon, Harmonic** — whose absence caused a gold-set dispute post to be missed entirely.

**Whenever a new system is added to `results.json`, re-run the calibration.**

---

## 3. Query families

14 queries per run, one API call each.

| Family | Tier | Cap | Purpose |
|---|---|---|---|
| `explicit-ai-solution` | 1 | 40 | Explicit "AI solved/proved/disproved X" claims |
| `formal-verification` | 1 | 40 | Lean/Coq/Isabelle verification — strongest corroboration |
| `disputes-and-corrections` | 1 | 40 | **Wrong, withdrawn, rediscovered, already known** |
| `problem-registries` | 1 | 40 | Erdős / OEIS / MathOverflow — carries identifiers |
| `academic-announcement` | 2 | 30 | "we prove…", "suggested by…" — no buzzwords |
| `artifact-release` | 2 | 30 | Preprint/repo posts — evidence, not a claim |
| `arxiv-linked` | 2 | 30 | `url:arxiv.org` — high corroboration by construction |
| `named-systems` | 2 | 30 | Named systems + mathematical language |
| `broad-recall` | 3 | 20 | Safety net for unanticipated wording |
| `account-*` (×5) | 1 | 40 | Probe-verified trusted accounts |

### The dispute family is the most important addition

Sprint 1 searched only for **success claims**. That was a real hole: this project's two
`disputed` records exist precisely because a claim was *wrong* or *already known* —

- `alleged-roll-conjecture` — the underlying conjecture does not appear in the literature;
- `graffiti-conjecture-154` — a rediscovery of a witness published a month earlier.

Neither would have been discoverable by the Sprint 1 query set. Dispute observations are
routed to the **review queue** (`routesTo`), never straight to candidates.

---

## 4. Trusted accounts — verified, not remembered

Sprint 1 shipped six handles written from memory. The probe checked each with `from:`:

| Handle | Verdict | Enabled |
|---|---|---|
| `octonion` | ✅ VERIFIED | yes — cited in `results.json` |
| `imjaredz` | ✅ VERIFIED | yes — cited in `results.json` |
| `GoogleDeepMind` | ✅ VERIFIED | yes |
| `OpenAI` | ✅ VERIFIED | yes |
| `leanprover` | ✅ VERIFIED | yes |
| `erdosproblems` | ⚠️ no results | **no** |
| `teorth` | ⚠️ no results | **no** |
| `XenaProject` | ⚠️ no results | **no** |

Unverified handles are kept in config **disabled** rather than deleted, so the record shows
they were considered and not silently invented. A test enforces that no account can be
enabled without a `verifiedOn` date.

`teorth` (Terence Tao) and `erdosproblems` are high-value if the correct handles exist —
worth confirming by hand. They may exist but be quiet, or the handle may differ.

---

## 5. Calibration

`python -m scripts.automation.calibrate` — offline, zero API calls. It asks: *would today's
queries have found the events we already know about?*

**Gold set:** 12 positives (drawn from records in `data/results.json`, two with **verbatim**
captured post text and a cited source; the rest labelled `verbatim: false` as faithful
reconstructions of the wording pattern — never presented as real quotations) and 10
realistic negatives (homework, benchmarks, olympiad scores, proof-of-work, zero-knowledge
proofs, AI-explains-a-known-proof, vague hype).

**Current result:**

```
queries built     : 14
gold-set recall   : 12/12  (100%)
false positives   : 3/10   (30%)
```

Both are locked in by tests: recall must stay complete, and the noise rate is a **ratchet**
capped at 40% so it cannot quietly worsen.

### What calibration caught that review would not have

1. `academic-announcement` matched **nothing** — its AI group listed only generic words, so
   "we prove … suggested by output from **GPT-5.4 Pro**" fell through. Rebuilt to include
   system names.
2. Account queries appeared to match **everything** — the offline matcher treated `from:`
   as neutral. Fixed to model authorship; this also corrected the per-query statistics.
3. Missing system names (§2), found by reconciling against `results.json`.

### Remaining false positives — deliberately accepted

| Negative | Matched by | Why it is allowed through |
|---|---|---|
| `poc-software` | `arxiv-linked`, `broad-recall` | "counterexample" + "AI" in a software context |
| `security-proof` | `formal-verification` | genuinely machine-checked, just not AI or mathematics |
| `vague-hype` | `arxiv-linked`, `broad-recall` | "theorem" + "AI" with no claim |

These are the intended division of labour: **recall in the search layer, precision in the
classifier**. Excluding them by keyword would cost real signal — `-counterexample` or
`-"machine-checked"` would remove two of the best families. Gemini relevance filtering
(Sprint 2) is the right place to reject them.

---

## 5b. K10 — solved: TwitterAPI.io silently truncates at 512 characters

**Status: solved, fixed and verified live.**

Any query longer than **512 characters** returns HTTP 200 with an empty tweet list. No
error, no warning, no truncation notice. The failure is indistinguishable from "nobody
posted about this today", which is why it survived two live runs, an external review and a
232-test suite while emptying six of fourteen queries.

### The measurement

A length sweep held the term set broad — padding one OR-group with junk alternatives, which
can only widen a disjunction — so any drop to zero had to be the limit rather than a change
in what matches:

```
chars   returned
  …512        20
   513         0     ← and every length above it
```

Monotone, exact, and 512 is a round backend buffer.

### Two wrong answers on the way, and what killed each

**Query length "definitively ruled out."** The earlier bisect walked 462 → 67 chars and
found no cutoff, because every length it tested was already under 512 except one; the single
`417 → 0` reading was noise I built a conclusion around.

**An OR-term cap at 37.** A term-by-term walk showed 36 terms returning results and 37
returning none, monotonically, and that rule reproduced all 14 production queries. It was
still wrong: term count and length moved together in that walk. The live run over the first
sharded query set falsified it within the hour — a 34-term query returned 20 results and a
32-term one returned none, while length separated all 16 observations with no overlap. The
lesson worth keeping is that the rule fitting 14 of 14 observations was not evidence it was
the *right* variable, only that it correlated with one.

What did settle it was a **witness test**: search one group alone, take a post the API
itself just returned, verify from its text that it satisfies the second group too, then ask
for the conjunction. Post `2081117415794987476` contains both `"independently verified"` and
`AI`, is demonstrably indexed, and the conjunction returned nothing — even narrowed to
`from:` its own author. That excluded "the window is genuinely empty" and left only the
query shape.

### The fix — shard, never trim

`(A) AND (b1 OR b2)` is exactly `[(A) AND b1] OR [(A) AND b2]`, so a long query is split
into shards whose union is the original. It costs extra calls and loses nothing. Chunks are
packed greedily against real assembled length, since terms differ in width, and a term that
cannot fit at all is flagged `over_cap` rather than dropped.

This also replaced the old behaviour above `MAX_QUERY_CHARS`, which dropped whole OR-groups
to make a query fit — silently changing what the query meant, the same class of invisible
loss as K10 itself.

**14 queries became 23**, longest 497 characters against a ship cap of 500 and a measured
limit of 512.

### Verified live

| | before | after |
|---|---|---|
| queries returning results | 8 / 14 | **22 / 23** |
| tweets fetched | 35 | **209** |

The single remaining zero is `academic-announcement#4` at 403 characters — comfortably under
the cap, so that one is a genuine empty result rather than the bug. `disputes-and-corrections`,
added precisely because both `disputed` records here are dispute signals, returns posts again.

Measured corroboration before the fix: **3/20 and 4/35 — 11–15%**. The external-reference
gate is doing most of the filtering, exactly as designed.

## 5c. R2 — the window has to be the server's job

Until now the lookback was applied **after** the API had already chosen its 20 newest
all-time matches. A query with more than 20 matches ever could therefore hand back 20 stale
tweets and contribute nothing, while newer matching posts existed and were never requested.
Retrieval was capped at "20 per query, ever" and then filtered down from there.

`since_time:<unix> until_time:<unix>` is now appended at fetch time.

**The date form is not used.** The syntax probe had recorded `since:YYYY-MM-DD` as supported
because it returned 20 results — but so does an operator the backend ignores, and on this API
silently doing nothing is the characteristic failure. Re-probed properly, `since:`/`until:`
turns out not to be ignored but *wrong*: a request for 2026-07-19…07-21 returned twenty
tweets **all dated 07-22**, zero inside the window. The unix form was exact on the same
check — in-window dates for a past window, nothing at all for a future one — and second
precision is what a 30-hour lookback needs anyway.

The two operators cost **44 characters**, out of the same 512-character budget as everything
else. Sharding therefore builds against `MAX_QUERY_CHARS - TIME_WINDOW_CHARS`; without that
reserve, appending the window would have pushed queries back over the limit and re-opened
K10 while fixing R2.

**Measured after the change:** every query returned exactly what it kept — `returned == kept`
for all 28, against a previous pattern of fetching 20 and discarding most of them.

## 5c-bis. Pagination, chosen over window bisection

The roadmap called for splitting a saturated window (30h → 15h + 15h, recursively) when a
query fills a page. Pagination reaches the same goal with a better instrument: the cursor
walks exactly the window we asked for, while bisection re-runs the query and re-fetches the
overlap between halves.

It also fixed a quieter mismatch. Pages hold 20 results and `max_pages` was 1, while tier 1
is configured for `maxResultsPerRun: 40` — the config asked for twice what the fetch could
ever return, and nothing said so. Pages are now requested to cover each tier's own cap.

Telemetry gains `saturated`: the window held at least as much as we were willing to take, so
there may be more in it we never saw. That is the signal that would justify bisection, and
until it fires there is nothing to justify.

## 5d. R11 — the cap was a preference, not a cap

`deduped[:maxObservationsPerRun]` took the first N in query order. Whichever families were
built first always got in; the ones built last were dropped whenever a day was busy, and the
only trace was a single `overflowDeferred` count that never said *which*.

Selection is now round-robin across queries — a cap of 50 across 28 queries costs each of
them the same — and the surplus is carried in `data/automation/ingest_backlog.json` instead
of being discarded. Those records are already fetched and already paid for.

The backlog is deduplicated against both the fresh fetch and the observation store, because
the lookback window overlaps deliberately: without that, each run would refill the backlog
with copies of what it just processed and it would grow without bound. Verified to drain —
25 processed / 15 carried, then 15 consumed / 0 remaining, then a no-op.

**First live run with both:** 28 queries, 205 tweets, 157 after dedupe, 50 processed and
**107 carried** — a surplus that would previously have been silently thrown away.

## 6. Telemetry

Each run writes `data/automation/query_telemetry.json`:

```json
{ "queryId": "explicit-ai-solution", "tier": 1, "returned": 20,
  "keptInWindow": 12, "cappedAt": 40, "uniqueFirstSeen": 4 }
```

`uniqueFirstSeen` is the number this family surfaced **before any other family did** — the
figure that identifies redundant queries. A family with sustained `uniqueFirstSeen: 0` is a
candidate for retirement; disable it in config, no code change.

---

## 7. Known blind spots

Stated plainly, because a recall figure against our own gold set is not recall against X:

1. **Non-English posts.** `lang:en` is applied. A result announced only in French, German
   or Chinese is invisible. Deliberate — it cuts significant noise — and revisitable.
2. **Image-only and thread-tail announcements.** A claim made in a screenshot, or in reply
   ten posts down a thread, is not matched by text search.
3. **Novel system names.** A model released tomorrow is unknown until someone adds it. The
   `broad-recall` family is the partial safety net; the reconciliation habit in §2 is the fix.
4. **Paraphrase without keywords.** "It finally cracked the thing Erdős asked about in 1946"
   contains no cluster term.
5. **Gold-set circularity.** The positives were chosen from events we already know about,
   so the taxonomy is fitted to wordings we have seen. 100% recall here is a floor, not proof.
6. **The measured base rate.** The live smoke test found **only 3 of 20 tweets carried any
   external identifier**. High recall means more unverifiable material, which is exactly why
   the corroboration gate exists.

---

## 8. Cost

14 queries × 1 page/day ≈ **14 API calls/day** (~430/month), paced at 1.5s apart —
roughly 21 seconds of wall-clock. Per-tier caps bound the observation count before any
Gemini call is made. Extraction is capped separately (`maxCallsPerRun: 50`) and cached on
`(observationId, promptVersion, modelVersion)`, so a steady state costs a handful of calls
per day.

---

## 9. How to change the query set

- **Add a term** → edit the cluster in `config/twitter_discovery.json`, run
  `python -m scripts.automation.calibrate`, confirm recall did not drop.
- **Add a family** → append to `families` with an `id`, `tier`, `purpose` and template.
- **Retire a noisy family** → set `"enabled": false`. No code change; telemetry is the evidence.
- **Add a trusted account** → add it **disabled**, run the probe workflow, and enable it
  only if it reports `VERIFIED`. A test enforces this.
- **Add a new AI system** → add to the `systems` cluster **and** re-run calibration.

---

## Revision history

| Version | Date | Change |
|---|---|---|
| 1 | 2026-07-25 | Sprint 1: 14 hand-written queries, 6 unverified handles, success claims only. |
| 2 | 2026-07-25 | Syntax probed against the live API; request pacing added after measuring 429s; taxonomy + template grammar; dispute/verification/registry/arXiv families added; handles probe-verified; gold-set calibration at 100% recall / 30% noise; per-query telemetry. |
