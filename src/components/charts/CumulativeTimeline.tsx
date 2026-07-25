import { useMemo } from "react";
import type { EChartsCoreOption } from "echarts/core";
import type { MathResult } from "@/types/result";
import { chartTheme, token, tooltipStyle } from "@/lib/echarts";
import { Card } from "../ui/primitives";
import { EChart } from "./EChart";

/**
 * The verification deficit.
 *
 * Two stacked bands on one honest linear scale: audited results in green at the
 * base, and the unverified remainder stacked above them — so the *height of the
 * grey band is literally the number of unverified claims*, and the top edge of
 * the stack is the total. No log axis, no broken axis: the vertical distance
 * between the lines is itself the quantity this site is about, and any
 * transform would destroy it.
 *
 * The shape tells the story: a hairline wedge through spring (verification kept
 * pace, even with a 51-problem batch in May, because that batch was audited),
 * which tears open in July when large unaudited batches land.
 */

interface Point {
  date: string;
  all: number;
  aud: number;
}

function buildSeries(rows: MathResult[]): Point[] {
  const byDay = new Map<string, { all: number; aud: number }>();
  for (const r of rows) {
    if (r.status === "disputed") continue; // recorded, never counted
    const e = byDay.get(r.claimedAt) ?? { all: 0, aud: 0 };
    e.all += r.count;
    if (r.status === "audited") e.aud += r.count;
    byDay.set(r.claimedAt, e);
  }
  let ca = 0;
  let cd = 0;
  return [...byDay.keys()]
    .sort()
    .map((date) => {
      const e = byDay.get(date)!;
      ca += e.all;
      cd += e.aud;
      return { date, all: ca, aud: cd };
    });
}

/**
 * Pick a round tick interval that yields ~4-6 gridlines, then snap the max to
 * it — so the axis ends just above the data with no dead space and every label
 * is a clean number.
 */
function niceAxis(v: number): { max: number; interval: number } {
  for (const interval of [5, 10, 20, 25, 50, 100, 200, 500]) {
    const max = Math.ceil(v / interval) * interval;
    const ticks = max / interval;
    if (ticks >= 4 && ticks <= 6) return { max, interval };
  }
  const interval = Math.pow(10, Math.floor(Math.log10(Math.max(v, 1))));
  return { max: Math.ceil(v / interval) * interval, interval };
}

export function CumulativeTimeline({
  rows,
  themeKey,
}: {
  rows: MathResult[];
  themeKey: string;
}) {
  const pts = useMemo(() => buildSeries(rows), [rows]);
  const last = pts[pts.length - 1];
  const gap = last ? last.all - last.aud : 0;

  const option = useMemo<EChartsCoreOption>(() => {
    const t = chartTheme();
    if (!pts.length) return {};

    const green = token("--good");
    const ink = token("--ink");

    // Find the day the deficit widens most — the turning point worth naming.
    let tear = pts[0];
    let worst = 0;
    for (let i = 1; i < pts.length; i++) {
      const d = pts[i].all - pts[i].aud - (pts[i - 1].all - pts[i - 1].aud);
      if (d > worst) {
        worst = d;
        tear = pts[i];
      }
    }

    const axis = niceAxis(last?.all ?? 0);
    const audData = pts.map((p) => [p.date, p.aud]);
    const gapData = pts.map((p) => [p.date, p.all - p.aud]);

    return {
      animationDuration: 700,
      animationEasing: "cubicOut",
      grid: { top: 54, right: 92, bottom: 28, left: 46 },
      textStyle: { fontFamily: t.fontSans },
      tooltip: {
        trigger: "axis",
        ...tooltipStyle(t),
        axisPointer: {
          type: "line",
          lineStyle: { color: token("--ink", 0.35), width: 1 },
        },
        formatter: (params: unknown) => {
          const arr = params as { axisValueLabel: string; data: [string, number] }[];
          if (!arr?.length) return "";
          const date = arr[0].data[0];
          const p = pts.find((x) => x.date === date);
          if (!p) return "";
          const d = new Date(date + "T00:00:00Z").toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            timeZone: "UTC",
          });
          const row = (label: string, value: number, colour: string) =>
            `<div style="display:flex;align-items:center;gap:7px;margin-top:3px">
               <span style="width:11px;height:3px;border-radius:2px;background:${colour}"></span>
               <span style="color:${t.ink};font-weight:600">${value}</span>
               <span>${label}</span>
             </div>`;
          return (
            `<div style="font-weight:650;color:${t.ink};font-size:12px">${d}, 2026</div>` +
            row("claimed", p.all, ink) +
            row("audited", p.aud, green) +
            `<div style="margin-top:5px;padding-top:4px;border-top:1px solid ${t.line};color:${t.muted};font-size:11px">` +
            `${p.all - p.aud} still unverified</div>`
          );
        },
      },
      xAxis: {
        type: "time",
        boundaryGap: false,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: t.muted, fontSize: 10, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: axis.max,
        interval: axis.interval,
        splitLine: { lineStyle: { color: token("--rule"), width: 1 } },
        axisLabel: { color: t.muted, fontSize: 10, fontFamily: t.fontMono },
      },
      // scroll/pinch to zoom; no slider brick
      dataZoom: [{ type: "inside", filterMode: "none", zoomOnMouseWheel: "shift" }],
      series: [
        {
          name: "Audited",
          type: "line",
          step: "end",
          stack: "deficit",
          showSymbol: false,
          smooth: false,
          lineStyle: { width: 2, color: green },
          itemStyle: { color: green },
          areaStyle: {
            color: {
              type: "linear",
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: token("--good", 0.34) },
                { offset: 1, color: token("--good", 0.06) },
              ],
            },
          },
          emphasis: { disabled: true },
          endLabel: {
            show: true,
            formatter: () => `${last.aud}`,
            color: green,
            fontFamily: t.fontMono,
            fontSize: 13,
            fontWeight: "bold",
            offset: [6, 0],
          },
          data: audData,
        },
        {
          name: "Unverified",
          type: "line",
          step: "end",
          stack: "deficit",
          showSymbol: false,
          lineStyle: { width: 2, color: ink },
          itemStyle: { color: token("--muted") },
          areaStyle: {
            color: {
              type: "linear",
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: token("--ink", 0.22) },
                { offset: 1, color: token("--ink", 0.04) },
              ],
            },
          },
          emphasis: { disabled: true },
          endLabel: {
            show: true,
            formatter: () => `${last.all}`,
            color: ink,
            fontFamily: t.fontMono,
            fontSize: 13,
            fontWeight: "bold",
            offset: [6, 0],
          },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: token("--ink", 0.28), width: 1, type: [4, 4] },
            label: {
              show: true,
              position: "end",
              formatter: "verification falls behind",
              color: t.ink2,
              fontSize: 10,
              fontWeight: 600,
              padding: [0, 0, 8, 0],
            },
            data: [{ xAxis: tear.date }],
          },
          data: gapData,
        },
      ],
    };
  }, [pts, last, themeKey]);

  return (
    <Card>
      <header className="mb-1 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="display text-xl text-ink">The verification deficit</h2>
          <p className="mt-1 max-w-[62ch] text-xs leading-relaxed text-muted">
            Cumulative problems, stacked: audited at the base, everything still unverified
            above it. The height of the grey band <em>is</em> the number of unverified
            claims. It stays hairline-thin through spring — then tears open in July.
          </p>
        </div>
        <div className="flex items-end gap-5">
          <Key colour="rgb(var(--good))" label="audited" value={last?.aud ?? 0} />
          <Key colour="rgb(var(--ink))" label="claimed" value={last?.all ?? 0} />
          <div className="border-l border-rule pl-5">
            <p className="display text-3xl leading-none text-ink">{gap}</p>
            <p className="eyebrow mt-1">unverified</p>
          </div>
        </div>
      </header>

      <EChart
        option={option}
        themeKey={themeKey}
        height={330}
        ariaLabel="Stacked cumulative timeline: audited results and the unverified remainder"
      />

      <p className="mt-1 text-[11px] text-muted">
        Shift + scroll to zoom the timeline · disputed claims are excluded
      </p>
    </Card>
  );
}

function Key({
  colour,
  label,
  value,
}: {
  colour: string;
  label: string;
  value: number;
}) {
  return (
    <div>
      <p className="mono text-lg leading-none text-ink">{value}</p>
      <p className="mt-1 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] text-muted">
        <span
          className="inline-block h-[3px] w-3 rounded-sm"
          style={{ background: colour }}
        />
        {label}
      </p>
    </div>
  );
}
