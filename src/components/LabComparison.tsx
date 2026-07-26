import type { MathResult } from "@/types/result";
import { labShapes } from "@/lib/evidence";
import { LABS, labColor } from "@/lib/labs";
import type { LabKey } from "@/types/result";
import { Card, CardTitle } from "./ui/primitives";

/**
 * Who claimed, and who verified — in the two units that disagree.
 *
 * This replaces "Problems credited per lab", which was the most misleading
 * thing on the page. It plotted problems and read as a league table:
 *
 *     DeepMind   53 of 53 audited   (100%)
 *     OpenAI     15 of 57 audited   (26%)
 *
 * Arithmetically true, and almost the reverse of what happened. DeepMind has
 * **four entries**; one is 44 OEIS conjectures audited as a single unit, and 52
 * of its 53 audited problems carry no source link. OpenAI has 23 entries and 11
 * separate audits — nearly three times as many verification decisions.
 *
 * So this leads with entries, shows problems underneath, and says out loud when
 * a lab's problem total rests on one row. A reader should not have to reconstruct
 * that from a bar chart; it is the whole story.
 */
export function LabComparison({ rows }: { rows: MathResult[] }) {
  const labs = labShapes(rows).filter((l) => l.records > 0);
  if (!labs.length) return null;

  const maxRecords = Math.max(...labs.map((l) => l.records));
  const maxProblems = Math.max(...labs.map((l) => l.problems));

  return (
    <Card>
      <CardTitle
        title="Who claimed, and who verified"
        sub="Entries first — one entry is one thing somebody wrote down, and one audit is one decision a curator made. Problem totals are shown underneath, because a single batch entry can carry dozens of them."
      />

      <ul className="space-y-5">
        {labs.map((l) => {
          const colour = labColor(l.key as LabKey);
          const name = LABS[l.key as LabKey]?.name ?? l.key;
          return (
            <li key={l.key}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <span className="text-sm font-semibold text-ink">{name}</span>
                <span className="mono text-[11px] text-muted">
                  <span className="text-ink">{l.auditedRecords}</span>/{l.records} entries
                  audited · <span className="text-ink">{l.auditedProblems}</span>/{l.problems}{" "}
                  problems
                </span>
              </div>

              <Track
                label="entries"
                total={l.records}
                audited={l.auditedRecords}
                auditedUnsourced={l.auditedUnsourcedRecords}
                scale={maxRecords}
                colour={colour}
              />
              <Track
                label="problems"
                total={l.problems}
                audited={l.auditedProblems}
                auditedUnsourced={l.auditedUnsourcedProblems}
                scale={maxProblems}
                colour={colour}
              />

              {l.dominatedByOneEntry && l.largest && (
                <p className="mt-1.5 text-[11px] leading-relaxed text-muted">
                  One entry — <span className="text-ink-2">{l.largest.title}</span> —{" "}
                  is <span className="mono text-ink">{Math.round(l.largest.share * 100)}%</span>{" "}
                  of this lab&rsquo;s problem total.
                </p>
              )}
              {l.auditedUnsourcedRecords > 0 && (
                <p className="text-[11px] leading-relaxed text-muted">
                  <span className="mono text-ink">{l.auditedUnsourcedRecords}</span> of its{" "}
                  <span className="mono text-ink">{l.auditedRecords}</span> audited entries have
                  no source link, covering{" "}
                  <span className="mono text-ink">{l.auditedUnsourcedProblems}</span> of{" "}
                  <span className="mono text-ink">{l.auditedProblems}</span> audited problems.
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function Track({
  label,
  total,
  audited,
  auditedUnsourced = 0,
  scale,
  colour,
}: {
  label: string;
  total: number;
  audited: number;
  auditedUnsourced?: number;
  scale: number;
  colour: string;
}) {
  const width = scale ? (total / scale) * 100 : 0;
  const sourced = Math.max(audited - auditedUnsourced, 0);
  const pct = (n: number) => (total ? (n / total) * 100 : 0);

  return (
    <div className="mt-1.5 flex items-center gap-2">
      <span className="w-14 flex-none text-[10px] uppercase tracking-wider text-muted">
        {label}
      </span>
      <div className="h-2.5 flex-1 overflow-hidden rounded-sm bg-[rgb(var(--rule)/0.5)]">
        <div className="flex h-full" style={{ width: `${width}%` }}>
          {/* Audited with a source, then audited without one — hatched, the same
              mark absence gets everywhere on this page — then the remainder. */}
          <span style={{ width: `${pct(sourced)}%`, background: colour }} />
          <span
            style={{
              width: `${pct(auditedUnsourced)}%`,
              background: `repeating-linear-gradient(45deg, ${colour} 0 3px, transparent 3px 7px)`,
            }}
          />
          <span
            style={{ width: `${pct(total - audited)}%`, background: colour, opacity: 0.25 }}
          />
        </div>
      </div>
      <span className="mono w-8 flex-none text-right text-[11px] text-ink-2">{total}</span>
    </div>
  );
}
