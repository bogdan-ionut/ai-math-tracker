import { useMemo } from "react";
import type { MathResult } from "@/types/result";
import { labColor } from "@/lib/labs";
import { fmtDate } from "@/lib/format";
import { Card, CardTitle } from "../ui/primitives";

/**
 * Unit "waffle" of the most recent window: one square per problem, colored by
 * lab, faded when not audited. Expands batch records into their members so the
 * squares add up to the real count.
 */
export function FortnightGrid({
  rows,
  themeKey,
  onSelect,
}: {
  rows: MathResult[];
  themeKey: string;
  onSelect: (r: MathResult) => void;
}) {
  const { days, byDay, windowLabel, count } = useMemo(() => {
    type Unit = { r: MathResult; label: string };
    const empty = new Map<string, Unit[]>();
    if (rows.length === 0) return { days: [] as string[], byDay: empty, windowLabel: "", count: 0 };
    const maxDate = rows.reduce((m, r) => (r.claimedAt > m ? r.claimedAt : m), rows[0].claimedAt);
    const end = new Date(maxDate + "T00:00:00Z");
    const start = new Date(end);
    start.setUTCDate(start.getUTCDate() - 14); // 15-day window
    const startIso = start.toISOString().slice(0, 10);

    const map = new Map<string, Unit[]>();
    let total = 0;
    for (const r of rows) {
      if (r.claimedAt < startIso) continue;
      const units =
        r.members && r.members.length === r.count
          ? r.members
          : Array.from({ length: r.count }, (_, i) => (r.count > 1 ? `${r.title} (${i + 1})` : r.title));
      const arr = map.get(r.claimedAt) ?? [];
      units.forEach((label) => arr.push({ r, label }));
      map.set(r.claimedAt, arr);
      total += r.count;
    }

    const dayList: string[] = [];
    for (let d = new Date(start); d <= end; d.setUTCDate(d.getUTCDate() + 1)) {
      dayList.push(d.toISOString().slice(0, 10));
    }
    return {
      days: dayList,
      byDay: map,
      windowLabel: `${fmtDate(startIso)} – ${fmtDate(maxDate)}`,
      count: total,
    };
  }, [rows]);

  if (days.length === 0) {
    return (
      <Card>
        <CardTitle title="The recent window" sub="No results in the current selection." />
      </Card>
    );
  }

  const SQ = 12;
  const GAP = 2;

  const maxStack = Math.max(1, ...days.map((d) => (byDay.get(d)?.length ?? 0)));
  const rowsHigh = Math.min(maxStack, 14);
  const svgH = 40 + rowsHigh * (SQ + GAP) + 34;

  return (
    <Card>
      <CardTitle
        title={`The recent window · ${windowLabel}`}
        sub={`Each square is one problem, colored by lab — faded squares are not yet audited. ${count} in the last 15 days.`}
      />
      <div className="overflow-x-auto">
        <svg
          key={themeKey}
          viewBox={`0 0 480 ${svgH}`}
          className="w-full min-w-[420px]"
          role="img"
          aria-label="Unit chart of problems in the most recent window"
        >
          {days.map((d, i) => {
            const stack = byDay.get(d) ?? [];
            const cx = 6 + (i + 0.5) * ((480 - 12) / days.length);
            const wide = stack.length > 8;
            const perCol = wide ? Math.ceil(stack.length / 2) : stack.length;
            const baseY = svgH - 30;
            return (
              <g key={d}>
                {stack.length > 0 && (
                  <text
                    x={cx}
                    y={baseY - perCol * (SQ + GAP) - 5}
                    textAnchor="middle"
                    fontSize={9}
                    fontWeight={600}
                    fill="rgb(var(--muted))"
                  >
                    {stack.length}
                  </text>
                )}
                {stack.map((u, j) => {
                  const row = wide ? Math.floor(j / 2) : j;
                  const xx = wide ? cx - SQ - 1 + (j % 2) * (SQ + 2) : cx - SQ / 2;
                  const y = baseY - (row + 1) * (SQ + GAP) + GAP;
                  return (
                    <rect
                      key={j}
                      x={xx}
                      y={y}
                      width={SQ}
                      height={SQ}
                      rx={2.5}
                      fill={labColor(u.r.labKey)}
                      opacity={u.r.status === "audited" ? 1 : 0.45}
                      className="cursor-pointer"
                      onClick={() => onSelect(u.r)}
                    >
                      <title>{`${u.label} · ${u.r.model} · ${u.r.status}`}</title>
                    </rect>
                  );
                })}
                <line x1={cx - 8} x2={cx + 8} y1={baseY + 0.5} y2={baseY + 0.5} stroke="rgb(var(--rule))" />
                {(i === 0 || i === days.length - 1 || days.length <= 16) && (
                  <text x={cx} y={baseY + 14} textAnchor="middle" fontSize={9} className="tnum" fill="rgb(var(--muted))">
                    {d.slice(8)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
    </Card>
  );
}
