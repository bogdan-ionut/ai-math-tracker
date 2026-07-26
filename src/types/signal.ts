/** An unverified automated signal.
 *
 * Deliberately a *different type* from `MathResult`, not a subset of it. They
 * are never mixed in a list, never summed into a metric, and the compiler will
 * complain if anyone tries — which is the point. A signal is something the
 * pipeline noticed; a result is something the tracker stands behind.
 */
export type EvidenceTier = "published" | "registered" | "referenced" | "none";

export interface Signal {
  id: string;
  canonicalName: string | null;
  family: string | null;
  externalIds: Record<string, string[]>;
  sources: string[];
  firstSeenAt: string | null;
  lastSeenAt: string | null;
  problemRef: string | null;
  claimCount: number;
  observationCount: number;
  modelName: string | null;
  organization: string | null;
  resultType: string | null;
  claimedAt: string | null;
  evidenceTier: EvidenceTier;
}

export interface SignalFeed {
  generatedAt: string;
  count: number;
  disclaimer: string;
  signals: Signal[];
}
