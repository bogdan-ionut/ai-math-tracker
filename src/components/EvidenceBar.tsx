import { useState } from "react";
import type { MathResult } from "@/types/result";
import { evidenceSegments } from "@/lib/evidence";
import { Card, CardTitle } from "./ui/primitives";

/**
 * The whole corpus in one bar, ordered by how well it is known.
 *
 * Deliberately not a chart library: one stacked bar rendered as flex children is
 * exact, weightless, keyboard-reachable, and does not pull a 564 kB charting
 * runtime above the fold.
 *
 * Two rules of the page are enforced here rather than described:
 *
 *   Green means audited. Both audited segments are green, because both *are*
 *   audited — a missing source link does not undo a curator's judgement.
 *
 *   Absence has one look. The audited records with nothing to link to are
 *   hatched, and hatching means the same thing everywhere it appears: we are
 *   telling you something is not there.
 *
 * Widths are **records**, not problems. Four batch entries carry two thirds of
 * the problem count, so a problem-weighted bar would be a picture of those four
 * entries wearing the corpus as a costume. Both numbers are one hover away.
 */
export function EvidenceBar({ rows }: { rows: MathResult[] }) {
  const segments = evidenceSegments(rows);
  const [active, setActive] = useState<string | null>(null);
  const total = segments.reduce((n, s) => n + s.records, 0);
  if (!total) return null;

  const shown = segments.find((s) => s.key === active) ?? null;

  return (
    <Card>
      <CardTitle
        title="What is actually known"
        sub="Every record, ordered by the strength of its evidence. Widths are records — not problems — because four batch entries carry most of the problem count. Hover or focus a band for both figures."
      />

      <div
        className="flex h-11 w-full overflow-hidden rounded-md border border-rule"
        role="list"
        aria-label="Records by evidence strength"
      >
        {segments.map((s) => {
          const pct = (s.records / total) * 100;
          const colour = `rgb(var(${s.token}))`;
          return (
            <button
              key={s.key}
              role="listitem"
              aria-label={`${s.label}: ${s.records} records, ${s.problems} problems`}
              onMouseEnter={() => setActive(s.key)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(s.key)}
              onBlur={() => setActive(null)}
              style={{
                width: `${pct}%`,
                background: s.hatched
                  ? `repeating-linear-gradient(45deg, ${colour} 0 3px, transparent 3px 7px)`
                  : colour,
              }}
              className={`relative h-full border-r border-[rgb(var(--panel))] transition-opacity last:border-r-0 ${
                active && active !== s.key ? "opacity-40" : "opacity-100"
              }`}
            />
          );
        })}
      </div>

      {/* Reserve the row so hovering never reflows the page under the cursor. */}
      <p className="mt-3 min-h-[2.75rem] max-w-[68ch] text-xs leading-relaxed text-muted">
        {shown ? (
          <>
            <span className="mono text-ink">{shown.records}</span> record
            {shown.records === 1 ? "" : "s"} ·{" "}
            <span className="mono text-ink">{shown.problems}</span> problem
            {shown.problems === 1 ? "" : "s"} — <span className="text-ink-2">{shown.label}.</span>{" "}
            {shown.meaning}
          </>
        ) : (
          <>
            <span className="mono text-ink">{total}</span> records in view. The hatched band is
            audited work with no source link on file — judged sufficient by a curator, but not
            checkable from this page.
          </>
        )}
      </p>

      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
        {segments.map((s) => {
          const colour = `rgb(var(${s.token}))`;
          return (
            <li key={s.key} className="flex items-center gap-2 text-[11px] text-muted">
              <span
                className="h-2.5 w-2.5 flex-none rounded-[2px] border border-rule"
                style={{
                  background: s.hatched
                    ? `repeating-linear-gradient(45deg, ${colour} 0 2px, transparent 2px 4px)`
                    : colour,
                }}
              />
              {s.label}
              <span className="mono text-ink-2">{s.records}</span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
