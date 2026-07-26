// Mirrors scripts/schema.py (MathematicalResult). Kept in sync by hand; the
// pipeline emits public/data/schema.json as the authoritative contract.

export type ResultType =
  | "proof"
  | "refutation"
  | "counterexample"
  | "improved-bound"
  | "formalization"
  | "correction";

export type Status = "audited" | "reported" | "provisional" | "disputed";

export type LabKey = "oa" | "dm" | "cg" | "ax" | "an" | "xa" | "pk";

export interface MathResult {
  id: string;
  title: string;
  family: string;
  description: string;
  resultType: ResultType;
  status: Status;
  claimedAt: string; // ISO date
  auditedAt: string | null;
  lab: string;
  labKey: LabKey;
  model: string;
  humanCollaborators?: string[] | null;
  count: number;
  members?: string[] | null;
  isOpenProblem: boolean;
  yearsOpen?: number | null;
  erdosNumber?: string | null;
  sources: string[];
  paperUrl?: string | null;
  artifactUrl?: string | null;
  leanArtifactUrl?: string | null;
  confidence: number;
  auditNotes?: string | null;
  supersededBy?: string | null;
  /** 1–5, or null when nobody has assessed it yet. Never defaults to a number. */
  impact?: number | null;
  assessment?: string | null;
  resolution?: string | null;
  resolutionNote?: string | null;
  provenanceNote?: string | null;
}

export interface Summary {
  generatedAt: string;
  rangeStart: string;
  rangeEnd: string;
  total: number;
  byStatus: Record<string, number>;
  byLab: Record<string, number>;
  byLabAudited: Record<string, number>;
  erdosCount: number;
  largestDay: { date: string; count: number };
  oldestYearsOpen: number;
  modelFamilies: number;
  assessed: number;
  byImpact: Record<string, number>;
  landmarks: string[];

  /** F1. How much of the registry points at anything. Counted in *records*: a
   *  44-problem batch carries one source URL or none. */
  sourceCoverage: {
    recordsWithSource: number;
    recordsWithoutSource: number;
    auditedWithoutSource: number;
    auditedTotal: number;
    byStatus: Record<string, { withSource: number; withoutSource: number }>;
  };

  /** F1. Whether `auditedAt` says anything `claimedAt` did not. When
   *  `splitIsInformative` is false, the methodology text must not claim it does. */
  auditDating: {
    auditedRecords: number;
    sameDayAsClaim: number;
    laterThanClaim: number;
    missingAuditDate: number;
    splitIsInformative: boolean;
  };
}
