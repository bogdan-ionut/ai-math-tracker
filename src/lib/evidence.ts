import type { MathResult, Status } from "@/types/result";

/**
 * Evidence strength, and the batch distortion.
 *
 * Two facts about this dataset are load-bearing and neither was visible:
 *
 * 1. `audited` is the only tier allowed to be green, and most of it has no
 *    source link. "A curator judged the evidence sufficient" and "you can
 *    follow a link and check" are different claims, and the page was making
 *    the second by implication.
 *
 * 2. It is 40 records, not 121 problems. Four batch entries supply about two
 *    thirds of the problem count, so every per-problem figure is really a
 *    per-batch figure wearing a disguise.
 *
 * Everything here counts **records** as the primary unit for exactly that
 * reason, and carries the problem count alongside so both are always reachable.
 */

export type EvidenceKey =
  | "audited-sourced"
  | "audited-unsourced"
  | "reported"
  | "provisional"
  | "disputed";

export interface EvidenceSegment {
  key: EvidenceKey;
  label: string;
  /** What this segment does and does not license the reader to believe. */
  meaning: string;
  records: number;
  problems: number;
  /** CSS custom property. Green belongs to audited and to nothing else. */
  token: string;
  /** Absence of evidence gets one consistent treatment across the whole page. */
  hatched: boolean;
}

const ORDER: { key: EvidenceKey; label: string; meaning: string; token: string; hatched: boolean }[] = [
  {
    key: "audited-sourced",
    label: "Audited, sourced",
    meaning: "A curator judged the evidence sufficient, and you can follow a link and check.",
    token: "--good",
    hatched: false,
  },
  {
    key: "audited-unsourced",
    label: "Audited, no source link",
    meaning:
      "A curator judged the evidence sufficient. Nothing on this page lets you verify that yourself.",
    token: "--good",
    hatched: true,
  },
  {
    key: "reported",
    label: "Reported",
    meaning: "In a chronology, not independently audited.",
    token: "--ink-2",
    hatched: false,
  },
  {
    key: "provisional",
    label: "Provisional",
    meaning: "A public claim still waiting on artifacts.",
    token: "--muted",
    hatched: false,
  },
  {
    key: "disputed",
    label: "Disputed",
    meaning: "Contested or superseded. Never counted in the headline total.",
    token: "--lab-dm",
    hatched: false,
  },
];

function keyFor(r: MathResult): EvidenceKey {
  if (r.status === "audited") {
    return r.sources && r.sources.length > 0 ? "audited-sourced" : "audited-unsourced";
  }
  return r.status as Exclude<EvidenceKey, "audited-sourced" | "audited-unsourced">;
}

export function evidenceSegments(rows: MathResult[]): EvidenceSegment[] {
  const byKey = new Map<EvidenceKey, { records: number; problems: number }>();
  for (const r of rows) {
    const k = keyFor(r);
    const acc = byKey.get(k) ?? { records: 0, problems: 0 };
    acc.records += 1;
    acc.problems += r.count;
    byKey.set(k, acc);
  }
  return ORDER.map((spec) => ({
    ...spec,
    records: byKey.get(spec.key)?.records ?? 0,
    problems: byKey.get(spec.key)?.problems ?? 0,
  })).filter((s) => s.records > 0);
}

export interface BatchShape {
  records: number;
  problems: number;
  /** The headline convention: disputed results are recorded, never counted. */
  problemsExcludingDisputed: number;
  disputedProblems: number;
  /** Records standing for more than one problem, largest first. */
  batches: { id: string; title: string; count: number; status: Status }[];
  /** Problems supplied by batch records. */
  batchProblems: number;
  /** How many records it takes to reach half the problem count. */
  recordsForHalf: number;
}

export function batchShape(rows: MathResult[]): BatchShape {
  const problems = rows.reduce((n, r) => n + r.count, 0);
  const batches = rows
    .filter((r) => r.count > 1)
    .sort((a, b) => b.count - a.count)
    .map((r) => ({ id: r.id, title: r.title, count: r.count, status: r.status }));

  let running = 0;
  let recordsForHalf = 0;
  for (const r of [...rows].sort((a, b) => b.count - a.count)) {
    running += r.count;
    recordsForHalf += 1;
    if (running * 2 >= problems) break;
  }

  const disputedProblems = rows
    .filter((r) => r.status === "disputed")
    .reduce((n, r) => n + r.count, 0);

  return {
    records: rows.length,
    problems,
    problemsExcludingDisputed: problems - disputedProblems,
    disputedProblems,
    batches,
    batchProblems: batches.reduce((n, b) => n + b.count, 0),
    recordsForHalf: problems > 0 ? recordsForHalf : 0,
  };
}

export interface LabShape {
  key: string;
  /** Entries. The count of separate things somebody wrote down. */
  records: number;
  /** Entries a curator audited. The count of separate verification decisions. */
  auditedRecords: number;
  problems: number;
  auditedProblems: number;
  /** Audited problems on records with no source link. */
  auditedUnsourcedProblems: number;
  /** Audited *entries* with no source link. Tracked separately because a bar
   *  that shows audits as solid implies a sourcing they do not have. */
  auditedUnsourcedRecords: number;
  /** The single biggest entry, and what share of the lab it carries. */
  largest: { id: string; title: string; count: number; share: number } | null;
  /** True when one entry supplies more than half this lab's problems. */
  dominatedByOneEntry: boolean;
}

/**
 * Per-lab shape, in the two units that disagree.
 *
 * The old chart plotted problems per lab and read as an institutional league
 * table: DeepMind 53 of 53 audited, OpenAI 15 of 57. That is arithmetically
 * true and almost the opposite of what happened.
 *
 * DeepMind has **four entries**. One of them is 44 OEIS conjectures audited as
 * a single unit, and 52 of its 53 audited problems carry no source link.
 * OpenAI has 23 entries and 11 separate audits. Counted as verification
 * decisions rather than problem totals, OpenAI made nearly three times as many
 * as DeepMind — which is the reverse of the impression the chart gave.
 *
 * So records come first here, and problems second.
 */
export function labShapes(rows: MathResult[]): LabShape[] {
  const by = new Map<string, MathResult[]>();
  for (const r of rows) {
    by.set(r.labKey, [...(by.get(r.labKey) ?? []), r]);
  }

  return [...by.entries()]
    .map(([key, rs]) => {
      const problems = rs.reduce((n, r) => n + r.count, 0);
      const audited = rs.filter((r) => r.status === "audited");
      const biggest = [...rs].sort((a, b) => b.count - a.count)[0];
      const share = problems ? biggest.count / problems : 0;
      return {
        key,
        records: rs.length,
        auditedRecords: audited.length,
        problems,
        auditedProblems: audited.reduce((n, r) => n + r.count, 0),
        auditedUnsourcedProblems: audited
          .filter((r) => !r.sources || r.sources.length === 0)
          .reduce((n, r) => n + r.count, 0),
        auditedUnsourcedRecords: audited.filter(
          (r) => !r.sources || r.sources.length === 0,
        ).length,
        largest:
          biggest.count > 1
            ? { id: biggest.id, title: biggest.title, count: biggest.count, share }
            : null,
        dominatedByOneEntry: biggest.count > 1 && share > 0.5,
      };
    })
    .sort((a, b) => b.records - a.records || b.problems - a.problems);
}
