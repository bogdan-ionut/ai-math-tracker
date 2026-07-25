import { useMemo, useState } from "react";
import type { MathResult } from "@/types/result";
import { LABS, labColor } from "@/lib/labs";
import { fmtDate } from "@/lib/format";
import { IMPACT_LABELS } from "@/lib/impact";

/**
 * The signature view: every result placed by date (x) against assessed impact
 * (y), sized by how many problems it covers and colored by lab. Filled marks
 * are audited; hollow marks are not.
 *
 * This is the page's argument — the volume of claims sits at the bottom, and
 * only a handful reach the top. Unassessed results are parked in a separate
 * band below the axis so they are visible but never implied to be low-impact.
 */
const W = 1000;
const H = 462;
const PL = 128;
const PR = 968;
const TOP = 66;   // headroom for stacked landmark labels
const ROW = 62; // vertical distance between impact levels
const UNASSESSED_Y = TOP + 5 * ROW + 40;

function xScale(iso: string, min: number, max: number): number {
  const t = new Date(iso + "T00:00:00Z").getTime();
  if (max === min) return (PL + PR) / 2;
  return PL + ((t - min) / (max - min)) * (PR - PL);
}

const yFor = (impact: number) => TOP + (5 - impact) * ROW;

export function ImpactConstellation({
  rows,
  onSelect,
}: {
  rows: MathResult[];
  onSelect: (r: MathResult) => void;
}) {
  const [hover, setHover] = useState<MathResult | null>(null);

  const { pts, months } = useMemo(() => {
    if (!rows.length) return { pts: [], months: [] as { x: number; label: string }[] };
    const times = rows.map((r) => new Date(r.claimedAt + "T00:00:00Z").getTime());
    const min = Math.min(...times);
    const max = Math.max(...times);

    const placed = rows.map((r) => ({
      r,
      x: xScale(r.claimedAt, min, max),
      y: r.impact ? yFor(r.impact) : UNASSESSED_Y,
      radius: Math.min(5 + 2.1 * Math.sqrt(r.count), 20),
    }));

    // Nudge apart marks that would sit on top of each other.
    for (let i = 0; i < placed.length; i++) {
      for (let j = 0; j < i; j++) {
        const a = placed[i];
        const b = placed[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const need = a.radius + b.radius + 3;
        const dist = Math.hypot(dx, dy) || 0.01;
        if (dist < need) {
          const push = (need - dist) / 2;
          const ux = dx / dist;
          const uy = dy / dist;
          a.x += ux * push;
          a.y += uy * push * 0.45;
          b.x -= ux * push;
          b.y -= uy * push * 0.45;
        }
      }
    }

    // Month ticks
    const mo: { x: number; label: string }[] = [];
    const d = new Date(min);
    d.setUTCDate(1);
    while (d.getTime() <= max) {
      const t = d.getTime();
      if (t >= min) {
        mo.push({
          x: PL + ((t - min) / (max - min)) * (PR - PL),
          label: d.toLocaleDateString("en-US", { month: "short", timeZone: "UTC" }),
        });
      }
      d.setUTCMonth(d.getUTCMonth() + 1);
    }
    return { pts: placed, months: mo };
  }, [rows]);

  if (!rows.length) {
    return (
      <p className="py-16 text-center text-sm text-muted">
        No results match the current filters.
      </p>
    );
  }

  return (
    <div className="relative">
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full min-w-[720px]"
          role="img"
          aria-label="Impact constellation: each AI math result placed by date and assessed impact"
        >
          {/* impact bands */}
          {[5, 4, 3, 2, 1].map((lvl) => (
            <g key={lvl}>
              <line
                x1={PL - 8}
                x2={PR}
                y1={yFor(lvl)}
                y2={yFor(lvl)}
                stroke="rgb(var(--rule))"
                strokeWidth={1}
              />
              <text
                x={PL - 18}
                y={yFor(lvl) - 6}
                textAnchor="end"
                className="mono"
                fontSize={16}
                fontWeight={600}
                fill={lvl >= 4 ? "rgb(var(--ink))" : "rgb(var(--ink-2))"}
              >
                {lvl}
              </text>
              <text
                x={PL - 18}
                y={yFor(lvl) + 8}
                textAnchor="end"
                fontSize={9.5}
                fill="rgb(var(--muted))"
              >
                {IMPACT_LABELS[lvl]}
              </text>
            </g>
          ))}

          {/* unassessed band */}
          <line
            x1={PL - 8}
            x2={PR}
            y1={UNASSESSED_Y}
            y2={UNASSESSED_Y}
            stroke="rgb(var(--rule))"
            strokeWidth={1}
            strokeDasharray="none"
            opacity={0.7}
          />
          <text
            x={PL - 18}
            y={UNASSESSED_Y + 4}
            textAnchor="end"
            fontSize={9.5}
            fill="rgb(var(--muted))"
          >
            not yet assessed
          </text>

          {/* month ticks */}
          {months.map((m) => (
            <text
              key={m.label + m.x}
              x={m.x}
              y={H - 8}
              textAnchor="middle"
              className="mono"
              fontSize={9.5}
              fill="rgb(var(--muted))"
            >
              {m.label}
            </text>
          ))}

          {/* marks */}
          {pts.map(({ r, x, y, radius }) => {
            const audited = r.status === "audited";
            const dim = r.status === "disputed";
            const isHover = hover?.id === r.id;
            return (
              <g
                key={r.id}
                className="cursor-pointer"
                onMouseEnter={() => setHover(r)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onSelect(r)}
                tabIndex={0}
                onFocus={() => setHover(r)}
                onBlur={() => setHover(null)}
                onKeyDown={(e) => e.key === "Enter" && onSelect(r)}
              >
                <circle
                  cx={x}
                  cy={y}
                  r={Math.max(radius, 13)}
                  fill="transparent"
                />
                <circle
                  cx={x}
                  cy={y}
                  r={radius}
                  fill={audited ? labColor(r.labKey) : "transparent"}
                  stroke={labColor(r.labKey)}
                  strokeWidth={audited ? 0 : 1.6}
                  opacity={dim ? 0.3 : isHover ? 1 : 0.88}
                />
                {isHover && (
                  <circle
                    cx={x}
                    cy={y}
                    r={radius + 5}
                    fill="none"
                    stroke={labColor(r.labKey)}
                    strokeWidth={1}
                    opacity={0.5}
                  />
                )}
                {r.count > 3 && (
                  <text
                    x={x}
                    y={y + 4}
                    textAnchor="middle"
                    className="mono"
                    fontSize={10}
                    fontWeight={700}
                    fill={audited ? "rgb(var(--void))" : labColor(r.labKey)}
                    pointerEvents="none"
                  >
                    {r.count}
                  </text>
                )}
              </g>
            );
          })}

          {/* Label the landmarks. Labels are wide, so stagger them vertically
              whenever two sit close together on the x-axis — never let them collide. */}
          {(() => {
            const marks = pts
              .filter((p) => p.r.impact === 5)
              .sort((a, b) => a.x - b.x);
            let lastX = -Infinity;
            let tier = 0;
            return marks.map(({ r, x, y, radius }) => {
              if (x - lastX < 190) tier += 1;
              else tier = 0;
              lastX = x;
              const label = r.title.length > 30 ? r.title.slice(0, 29) + "…" : r.title;
              const ty = y - radius - 10 - tier * 14;
              // keep the centred label inside the plot; leader line still points at the mark
              const half = label.length * 2.9;
              const tx = Math.min(Math.max(x, PL + half), PR - half);
              return (
                <g key={"lbl" + r.id} pointerEvents="none">
                  {(tier > 0 || Math.abs(tx - x) > 2) && (
                    <line
                      x1={x}
                      x2={tx}
                      y1={y - radius - 3}
                      y2={ty + 3}
                      stroke="rgb(var(--rule))"
                      strokeWidth={1}
                    />
                  )}
                  <text
                    x={tx}
                    y={ty}
                    textAnchor="middle"
                    fontSize={10.5}
                    fontWeight={600}
                    fill="rgb(var(--ink))"
                  >
                    {label}
                  </text>
                </g>
              );
            });
          })()}
        </svg>
      </div>

      {/* hover readout — fixed slot, so nothing jumps */}
      <div className="mt-1 flex min-h-[46px] items-start gap-3 border-t border-rule pt-2.5">
        {hover ? (
          <>
            <span
              className="mt-1 h-2.5 w-2.5 flex-none rounded-full"
              style={{ background: labColor(hover.labKey) }}
            />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ink">
                {hover.title}
                <span className="ml-2 font-normal text-muted">
                  {hover.resolution} · {LABS[hover.labKey].name} · {fmtDate(hover.claimedAt)}
                </span>
              </p>
              <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-ink-2">
                {hover.assessment ?? hover.description}
              </p>
            </div>
          </>
        ) : (
          <p className="text-xs text-muted">
            Hover or focus a mark for its assessment · click to open the full record ·
            circle area = problems covered · filled = audited
          </p>
        )}
      </div>
    </div>
  );
}
