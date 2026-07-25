import type { LabKey, Status } from "@/types/result";

export const LAB_ORDER: LabKey[] = ["oa", "dm", "cg", "ax", "an", "xa", "pk"];

export const LABS: Record<LabKey, { name: string; short: string; token: string }> = {
  oa: { name: "OpenAI", short: "OpenAI", token: "--lab-oa" },
  dm: { name: "Google DeepMind", short: "DeepMind", token: "--lab-dm" },
  cg: { name: "Cognition", short: "Cognition", token: "--lab-cg" },
  ax: { name: "Axiom", short: "Axiom", token: "--lab-ax" },
  an: { name: "Anthropic", short: "Anthropic", token: "--lab-an" },
  xa: { name: "xAI", short: "xAI", token: "--lab-xa" },
  pk: { name: "PKU AI4Math", short: "PKU", token: "--lab-pk" },
};

export function labColor(key: LabKey): string {
  return `rgb(var(${LABS[key].token}))`;
}

export const STATUS_ORDER: Status[] = ["audited", "reported", "provisional", "disputed"];

export const STATUS_META: Record<
  Status,
  { label: string; blurb: string; token: string }
> = {
  audited: {
    label: "Audited",
    blurb: "Paper, Lean artifact, or expert confirmation",
    token: "--good",
  },
  reported: {
    label: "Reported",
    blurb: "In a chronology, not independently audited",
    token: "--ink-2",
  },
  provisional: {
    label: "Provisional",
    blurb: "Public claim awaiting artifacts",
    token: "--muted",
  },
  disputed: {
    label: "Disputed",
    blurb: "Contested or superseded by an earlier result",
    token: "--lab-dm",
  },
};
