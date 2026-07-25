import { useMemo } from "react";
import type { EChartsCoreOption } from "echarts/core";
import type { MathResult } from "@/types/result";
import { chartTheme, token, tooltipStyle } from "@/lib/echarts";
import { Card, CardTitle } from "../ui/primitives";
import { EChart } from "./EChart";

export function CumulativeTimeline({
  rows,
  themeKey,
}: {
  rows: MathResult[];
  themeKey: string;
}) {
  const option = useMemo<EChartsCoreOption>(() => {
    const t = chartTheme();
    // aggregate per day
    const byDay = new Map<string, { all: number; aud: number }>();
    for (const r of rows) {
      if (r.status === "disputed") continue;
      const e = byDay.get(r.claimedAt) ?? { all: 0, aud: 0 };
      e.all += r.count;
      if (r.status === "audited") e.aud += r.count;
      byDay.set(r.claimedAt, e);
    }
    const dates = [...byDay.keys()].sort();
    let ca = 0;
    let cd = 0;
    const allPts: [string, number][] = [];
    const audPts: [string, number][] = [];
    for (const d of dates) {
      const e = byDay.get(d)!;
      ca += e.all;
      cd += e.aud;
      allPts.push([d, ca]);
      audPts.push([d, cd]);
    }

    return {
      grid: { top: 16, right: 20, bottom: 54, left: 40 },
      textStyle: { fontFamily: t.fontSans },
      tooltip: {
        trigger: "axis",
        ...tooltipStyle(t),
        axisPointer: { type: "line", lineStyle: { color: token("--rule") } },
        valueFormatter: (v: number | string) => String(v),
      },
      legend: {
        data: ["All claims", "Audited"],
        right: 8,
        top: 0,
        textStyle: { color: t.ink2, fontSize: 11 },
        itemWidth: 18,
        itemHeight: 3,
        icon: "roundRect",
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: token("--rule") } },
        axisLabel: { color: t.muted, fontSize: 10, hideOverlap: true },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: token("--rule"), width: 1 } },
        axisLabel: { color: t.muted, fontSize: 10 },
      },
      dataZoom: [
        { type: "inside", filterMode: "none" },
        {
          type: "slider",
          height: 20,
          bottom: 12,
          borderColor: token("--rule"),
          fillerColor: token("--ink", 0.06),
          handleStyle: { color: token("--ink-2") },
          dataBackground: { lineStyle: { color: token("--rule") }, areaStyle: { color: token("--rule") } },
          textStyle: { color: t.muted, fontSize: 9 },
        },
      ],
      series: [
        {
          name: "All claims",
          type: "line",
          step: "end",
          showSymbol: false,
          symbol: "circle",
          symbolSize: 7,
          lineStyle: { width: 2, color: t.ink },
          itemStyle: { color: t.ink, borderColor: t.surface, borderWidth: 2 },
          areaStyle: { color: token("--ink", 0.05) },
          emphasis: { focus: "series" },
          data: allPts,
        },
        {
          name: "Audited",
          type: "line",
          step: "end",
          showSymbol: false,
          lineStyle: { width: 2, color: t.muted },
          itemStyle: { color: t.muted },
          emphasis: { focus: "series" },
          data: audPts,
        },
      ],
    };
  }, [rows, themeKey]);

  return (
    <Card>
      <CardTitle
        title="Cumulative problems settled, day by day"
        sub="Bold line: all claims. Thin line: audited results only. Drag the handles or scroll to zoom the timeline."
      />
      <EChart
        option={option}
        themeKey={themeKey}
        height={340}
        ariaLabel="Cumulative timeline of AI-settled math problems"
      />
    </Card>
  );
}
