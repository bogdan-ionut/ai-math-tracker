import { useMemo } from "react";
import type { MathResult } from "@/types/result";
import { LABS, LAB_ORDER, labColor } from "@/lib/labs";
import { doy } from "@/lib/format";
import { Card, CardTitle } from "../ui/primitives";

const W = 1000;
const PL = 92;
const PR = 980;
const LANE_H = 34;
const TOP = 24;
const D0 = 1;
const D1 = 213; // Jan 1 .. Aug 1

const MONTHS: [string, number][] = [
  ["Jan", 1], ["Feb", 32], ["Mar", 60], ["Apr", 91],
  ["May", 121], ["Jun", 152], ["Jul", 182], ["Aug", 213],
];

const X = (d: number) => PL + ((d - D0) * (PR - PL)) / (D1 - D0);

export function LabLanes({
  rows,
  themeKey,
  onSelect,
}: {
  rows: MathResult[];
  themeKey: string;
  onSelect: (r: MathResult) => void;
}) {
  const labs = useMemo(() => LAB_ORDER.filter((l) => rows.some((r) => r.labKey === l)), [rows]);
  const H = TOP + labs.length * LANE_H + 30;

  return (
    <Card>
      <CardTitle
        title="Who landed what, when"
        sub="One row per lab across 2026. Dot area scales with the number of problems; faded dots are not yet audited. Click any dot for detail."
      />
      <div className="overflow-x-auto">
        <svg
          key={themeKey}
          viewBox={`0 0 ${W} ${H}`}
          className="w-full min-w-[680px]"
          role="img"
          aria-label="Per-lab timeline of AI math results in 2026"
        >
          {/* month gridlines + labels */}
          {MONTHS.map(([name, d]) => (
            <g key={name}>
              {d > D0 && (
                <line
                  x1={X(d)}
                  x2={X(d)}
                  y1={TOP - 6}
                  y2={TOP + labs.length * LANE_H}
                  stroke="rgb(var(--rule))"
                  strokeWidth={1}
                  opacity={0.7}
                />
              )}
              <text
                x={X(d)}
                y={TOP + labs.length * LANE_H + 18}
                textAnchor={d === D0 ? "start" : "middle"}
                fontSize={10.5}
                fill="rgb(var(--muted))"
              >
                {name}
              </text>
            </g>
          ))}

          {labs.map((lab, i) => {
            const yc = TOP + i * LANE_H + LANE_H / 2;
            // group this lab's rows by (day, audited?)
            const groups = new Map<string, { day: number; aud: boolean; n: number; rows: MathResult[] }>();
            for (const r of rows) {
              if (r.labKey !== lab) continue;
              const key = `${r.claimedAt}:${r.status === "audited"}`;
              const g = groups.get(key) ?? { day: doy(r.claimedAt), aud: r.status === "audited", n: 0, rows: [] };
              g.n += r.count;
              g.rows.push(r);
              groups.set(key, g);
            }
            const total = rows.filter((r) => r.labKey === lab).reduce((a, b) => a + b.count, 0);
            return (
              <g key={lab}>
                <line x1={PL} x2={PR} y1={yc} y2={yc} stroke="rgb(var(--rule))" strokeWidth={1} />
                <text x={4} y={yc - 6} fontSize={11} fontWeight={600} fill="rgb(var(--ink-2))">
                  {LABS[lab].short}
                </text>
                <text x={4} y={yc + 8} fontSize={10} className="tnum" fill="rgb(var(--muted))">
                  {total}
                </text>
                {[...groups.values()].map((g, gi) => {
                  const r0 = Math.min(4 + 1.7 * Math.sqrt(g.n), 13);
                  const cx = X(g.day);
                  return (
                    <g key={gi} className="cursor-pointer" onClick={() => onSelect(g.rows[0])}>
                      <circle
                        cx={cx}
                        cy={yc}
                        r={r0}
                        fill={labColor(lab)}
                        stroke="rgb(var(--panel))"
                        strokeWidth={2}
                        opacity={g.aud ? 1 : 0.45}
                      >
                        <title>
                          {`${LABS[lab].name} · ${g.rows[0].claimedAt} — ${g.n} problem${g.n > 1 ? "s" : ""}`}
                        </title>
                      </circle>
                      {g.n >= 4 && (
                        <text
                          x={g.aud ? cx : cx + r0 + 3}
                          y={g.aud ? yc + 3.5 : yc - r0 + 2}
                          textAnchor={g.aud ? "middle" : "start"}
                          fontSize={10}
                          fontWeight={700}
                          fill={g.aud ? (lab === "oa" ? "#fff" : "#0b0b0b") : "rgb(var(--ink-2))"}
                          pointerEvents="none"
                        >
                          {g.n}
                        </text>
                      )}
                    </g>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>
    </Card>
  );
}
