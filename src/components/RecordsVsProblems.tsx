import type { MathResult } from "@/types/result";
import { batchShape } from "@/lib/evidence";
import { STATUS_META } from "@/lib/labs";
import { Card, CardTitle } from "./ui/primitives";

/**
 * Records versus problems — the disclaimer the headline number needs.
 *
 * "121 problems" is true and misleading in the same breath. It is 40 entries,
 * and a handful of batch records supply most of the count: one AlphaProof entry
 * alone is 44 OEIS conjectures, audited as a unit. Every per-problem figure on
 * this page — the lab comparison worst of all — is shaped by those few rows.
 *
 * This says so at the top, in the reader's first minute, rather than leaving it
 * to be discovered in the ledger. Nothing here is a correction of the data; the
 * batching is legitimate. What was missing was the reader knowing about it.
 */
export function RecordsVsProblems({ rows }: { rows: MathResult[] }) {
  const shape = batchShape(rows);
  if (!shape.records) return null;

  const singles = shape.records - shape.batches.length;
  const singleProblems = shape.problems - shape.batchProblems;
  const pctFromBatches = shape.problems
    ? Math.round((shape.batchProblems / shape.problems) * 100)
    : 0;

  return (
    <Card>
      <CardTitle
        title="Records, not problems"
        sub="The headline counts problems. The dataset is entries, and a few of them stand for many problems at once."
      />

      <div className="space-y-4">
        <Row
          label="Entries"
          value={shape.records}
          note={`${singles} single · ${shape.batches.length} batch`}
          segments={[
            { width: (singles / shape.records) * 100, token: "--ink-2", hatched: false },
            {
              width: (shape.batches.length / shape.records) * 100,
              token: "--ink",
              hatched: true,
            },
          ]}
        />
        <Row
          label="Problems"
          value={shape.problems}
          note={`${singleProblems} from single entries · ${shape.batchProblems} from batches`}
          segments={[
            { width: (singleProblems / shape.problems) * 100, token: "--ink-2", hatched: false },
            {
              width: (shape.batchProblems / shape.problems) * 100,
              token: "--ink",
              hatched: true,
            },
          ]}
        />
      </div>

      <p className="mt-4 max-w-[68ch] text-xs leading-relaxed text-muted">
        {shape.disputedProblems > 0 && (
          <>
            The masthead says{" "}
            <span className="mono text-ink">{shape.problemsExcludingDisputed}</span> because
            disputed results are recorded but never counted in the headline; the{" "}
            <span className="mono text-ink">{shape.problems}</span> above includes them.{" "}
          </>
        )}
        <span className="mono text-ink">{pctFromBatches}%</span> of the problem count comes from{" "}
        <span className="mono text-ink">{shape.batches.length}</span> batch{" "}
        {shape.batches.length === 1 ? "entry" : "entries"}, and{" "}
        <span className="mono text-ink">{shape.recordsForHalf}</span>{" "}
        {shape.recordsForHalf === 1 ? "entry accounts" : "entries account"} for half of it. Read
        every per-problem figure on this page with that in mind.
      </p>

      {shape.batches.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {shape.batches.slice(0, 5).map((b) => (
            <li key={b.id} className="flex items-baseline gap-3 text-[11px]">
              <span className="mono w-8 flex-none text-right text-ink">{b.count}</span>
              <span className="text-ink-2">{b.title}</span>
              <span
                className="mono text-[10px] uppercase tracking-wider"
                style={{ color: `rgb(var(${STATUS_META[b.status].token}))` }}
              >
                {STATUS_META[b.status].label}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Row({
  label,
  value,
  note,
  segments,
}: {
  label: string;
  value: number;
  note: string;
  segments: { width: number; token: string; hatched: boolean }[];
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-4">
        <span className="eyebrow">{label}</span>
        <span className="mono text-sm text-ink">{value}</span>
      </div>
      <div className="mt-1.5 flex h-3 w-full overflow-hidden rounded-sm border border-rule">
        {segments.map((s, i) => {
          const colour = `rgb(var(${s.token}))`;
          return (
            <span
              key={i}
              style={{
                width: `${s.width}%`,
                background: s.hatched
                  ? `repeating-linear-gradient(45deg, ${colour} 0 3px, transparent 3px 7px)`
                  : colour,
              }}
            />
          );
        })}
      </div>
      <p className="mt-1 text-[11px] text-muted">{note}</p>
    </div>
  );
}
