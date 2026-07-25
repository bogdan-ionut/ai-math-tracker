import { AnimatePresence, motion } from "motion/react";
import { ExternalLink, X } from "lucide-react";
import type { MathResult } from "@/types/result";
import { LABS } from "@/lib/labs";
import { fmtDateLong } from "@/lib/format";
import { StatusPill } from "./Ledger";
import { ImpactMeter } from "./ImpactMeter";
import { IMPACT_BLURB, IMPACT_LABELS } from "@/lib/impact";

function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function ResultDrawer({
  result,
  onClose,
}: {
  result: MathResult | null;
  onClose: () => void;
}) {
  return (
    <AnimatePresence>
      {result && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-black/50"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-rule bg-panel p-6"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 320, damping: 34 }}
            role="dialog"
            aria-modal="true"
            aria-label={result.title}
          >
            <div className="mb-4 flex items-start justify-between gap-4">
              <div className="flex items-center gap-2">
                <span
                  className="h-3 w-3 rounded-full"
                  style={{ background: `rgb(var(${LABS[result.labKey].token}))` }}
                />
                <span className="text-xs font-medium text-ink-2">{result.lab}</span>
                <StatusPill status={result.status} />
              </div>
              <button
                onClick={onClose}
                aria-label="Close"
                className="rounded-md p-1 text-muted hover:bg-panel-2 hover:text-ink"
              >
                <X size={18} />
              </button>
            </div>

            <h3 className="display text-2xl font-bold leading-tight text-ink">{result.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-ink-2">{result.description}</p>

            {/* Impact assessment — the editorial judgement, front and centre */}
            <div className="mt-5 rounded-lg border border-rule bg-panel-2 p-4">
              <div className="flex items-center justify-between gap-3">
                <span className="eyebrow">Assessed impact</span>
                <ImpactMeter value={result.impact} size="lg" />
              </div>
              {result.impact ? (
                <>
                  <p className="display mt-2 text-lg leading-tight text-ink">
                    {result.impact}/5 · {IMPACT_LABELS[result.impact]}
                  </p>
                  <p className="mt-0.5 text-[11px] italic text-muted">
                    {IMPACT_BLURB[result.impact]}
                  </p>
                  <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink-2">
                    {result.assessment}
                  </p>
                </>
              ) : (
                <p className="mt-2 text-[12.5px] italic leading-relaxed text-muted">
                  Not yet assessed. This result is counted, but no impact judgement has been
                  recorded for it — it is not implied to be low-impact.
                </p>
              )}
            </div>

            <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <Field label="Claimed">{fmtDateLong(result.claimedAt)}</Field>
              <Field label="Audited">
                {result.auditedAt ? fmtDateLong(result.auditedAt) : "—"}
              </Field>
              <Field label="Family">{result.family}</Field>
              <Field label="Resolution">{result.resolution ?? result.resultType}</Field>
              <Field label="System">{result.model}</Field>
              <Field label="Count">
                <span className="tnum">{result.count}</span>
              </Field>
              {result.yearsOpen ? <Field label="Years open">{result.yearsOpen}</Field> : null}
              <Field label="Confidence">
                <span className="tnum">{Math.round(result.confidence * 100)}%</span>
              </Field>
            </dl>

            {result.members && result.members.length > 1 && (
              <div className="mt-5">
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
                  {result.members.length} problems in this batch
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {result.members.map((m) => (
                    <span
                      key={m}
                      className="rounded border border-rule px-1.5 py-0.5 font-mono text-[11px] text-ink-2"
                    >
                      {m}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {result.provenanceNote && (
              <p className="mt-5 rounded-lg border border-[rgb(var(--lab-dm)/0.4)] p-3 text-xs leading-relaxed text-ink-2">
                <span className="font-semibold text-ink">Provenance · </span>
                {result.provenanceNote}
              </p>
            )}

            {result.auditNotes && (
              <p className="mt-5 rounded-lg border border-rule bg-panel-2 p-3 text-xs leading-relaxed text-ink-2">
                {result.auditNotes}
              </p>
            )}

            <div className="mt-6">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
                Sources
              </p>
              {result.sources.length ? (
                <ul className="space-y-1.5">
                  {result.sources.map((s) => (
                    <li key={s}>
                      <a
                        href={s}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1.5 text-xs text-lab-oa hover:underline"
                      >
                        <ExternalLink size={12} />
                        {hostname(s)}
                      </a>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs italic text-muted">Source pending verification.</p>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wider text-muted">{label}</dt>
      <dd className="mt-0.5 text-ink">{children}</dd>
    </div>
  );
}
