import type { LabKey, MathResult, Status } from "@/types/result";
import { LAB_ORDER } from "./labs";

export interface Filters {
  from: string | null; // ISO date inclusive
  to: string | null; // ISO date inclusive
  labs: LabKey[]; // empty = all
  statuses: Status[]; // empty = all
  families: string[]; // empty = all
  impacts: number[]; // empty = all; assessed levels only
  query: string;
}

export const EMPTY_FILTERS: Filters = {
  from: null,
  to: null,
  labs: [],
  statuses: [],
  families: [],
  impacts: [],
  query: "",
};

export function applyFilters(rows: MathResult[], f: Filters): MathResult[] {
  const q = f.query.trim().toLowerCase();
  return rows.filter((r) => {
    if (f.from && r.claimedAt < f.from) return false;
    if (f.to && r.claimedAt > f.to) return false;
    if (f.labs.length && !f.labs.includes(r.labKey)) return false;
    if (f.statuses.length && !f.statuses.includes(r.status)) return false;
    if (f.families.length && !f.families.includes(r.family)) return false;
    if (f.impacts.length && !(r.impact && f.impacts.includes(r.impact))) return false;
    if (q) {
      const hay = `${r.title} ${r.description} ${r.model} ${r.lab} ${r.family}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

export interface Metrics {
  total: number;
  byStatus: Record<Status, number>;
  byLab: Record<LabKey, number>;
  byLabAudited: Record<LabKey, number>;
  erdosCount: number;
  oldest: number;
  modelFamilies: number;
  largestDay: { date: string; count: number } | null;
  records: number;
  byImpact: Record<number, number>;
  assessed: number;
}

const MODEL_FAMILY_KEYS = [
  "GPT-5.2", "GPT-5.4", "GPT-5.5", "GPT-5.6 Pro", "GPT-5.6 Sol", "GPT-5.6",
  "internal", "Codex", "Aristotle", "Aletheia", "AlphaProof", "AxiomProver",
  "Fable", "MathDyad", "Devin", "Grok",
];

export function computeMetrics(rows: MathResult[]): Metrics {
  const byStatus = { audited: 0, reported: 0, provisional: 0, disputed: 0 } as Record<Status, number>;
  const byLab = Object.fromEntries(LAB_ORDER.map((l) => [l, 0])) as Record<LabKey, number>;
  const byLabAudited = Object.fromEntries(LAB_ORDER.map((l) => [l, 0])) as Record<LabKey, number>;
  const byDay = new Map<string, number>();
  const erdos = new Set<string>();
  const byImpact: Record<number, number> = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
  let assessed = 0;
  const fams = new Set<string>();
  let total = 0;
  let oldest = 0;

  for (const r of rows) {
    // Disputed results are shown but never counted in the headline total.
    if (r.status !== "disputed") total += r.count;
    byStatus[r.status] += r.count;
    byLab[r.labKey] += r.count;
    if (r.status === "audited") byLabAudited[r.labKey] += r.count;
    if (r.status !== "disputed") byDay.set(r.claimedAt, (byDay.get(r.claimedAt) ?? 0) + r.count);
    if (r.family === "Erdős") {
      if (r.members) r.members.forEach((m) => erdos.add(m));
      else if (r.erdosNumber) erdos.add(r.erdosNumber);
    }
    if (r.description.includes("Unit-distance")) erdos.add("#90");
    if (r.yearsOpen && r.yearsOpen > oldest) oldest = r.yearsOpen;
    if (r.impact) {
      byImpact[r.impact] += 1;
      assessed += 1;
    }
    for (const k of MODEL_FAMILY_KEYS) if (r.model.toLowerCase().includes(k.toLowerCase())) fams.add(k);
  }

  let largestDay: Metrics["largestDay"] = null;
  for (const [date, count] of byDay) {
    if (!largestDay || count > largestDay.count) largestDay = { date, count };
  }

  return {
    total,
    byStatus,
    byLab,
    byLabAudited,
    erdosCount: erdos.size,
    oldest,
    modelFamilies: fams.size,
    largestDay,
    records: rows.length,
    byImpact,
    assessed,
  };
}

// ---- URL <-> Filters ----
export function filtersFromParams(p: URLSearchParams): Filters {
  const list = (k: string) => (p.get(k) ? p.get(k)!.split(",").filter(Boolean) : []);
  return {
    from: p.get("from"),
    to: p.get("to"),
    labs: list("lab") as LabKey[],
    statuses: list("status") as Status[],
    families: list("family"),
    impacts: list("impact").map(Number).filter((n) => n >= 1 && n <= 5),
    query: p.get("q") ?? "",
  };
}

export function filtersToParams(f: Filters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.from) p.set("from", f.from);
  if (f.to) p.set("to", f.to);
  if (f.labs.length) p.set("lab", f.labs.join(","));
  if (f.statuses.length) p.set("status", f.statuses.join(","));
  if (f.families.length) p.set("family", f.families.join(","));
  if (f.impacts.length) p.set("impact", f.impacts.join(","));
  if (f.query.trim()) p.set("q", f.query.trim());
  return p;
}

export function isActive(f: Filters): boolean {
  return !!(
    f.from ||
    f.to ||
    f.labs.length ||
    f.statuses.length ||
    f.families.length ||
    f.impacts.length ||
    f.query.trim()
  );
}
