import { useMemo } from "react";
import type { EChartsCoreOption } from "echarts/core";
import type { Metrics } from "@/lib/filters";
import { LABS, LAB_ORDER, labColor } from "@/lib/labs";
import { chartTheme, token, tooltipStyle } from "@/lib/echarts";
import { Card, CardTitle } from "../ui/primitives";
import { EChart } from "./EChart";

export function LabBars({ m, themeKey }: { m: Metrics; themeKey: string }) {
  const labs = useMemo(
    () => LAB_ORDER.filter((l) => m.byLab[l] > 0).sort((a, b) => m.byLab[b] - m.byLab[a]),
    [m],
  );

  const option = useMemo<EChartsCoreOption>(() => {
    const t = chartTheme();
    const cats = labs.map((l) => LABS[l].name).reverse();
    const audited = labs.map((l) => m.byLabAudited[l]).reverse();
    const rest = labs.map((l) => m.byLab[l] - m.byLabAudited[l]).reverse();
    const colors = labs.map((l) => labColor(l)).reverse();

    return {
      grid: { top: 8, right: 34, bottom: 8, left: 96 },
      textStyle: { fontFamily: t.fontSans },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow", shadowStyle: { color: token("--ink", 0.04) } },
        ...tooltipStyle(t),
      },
      xAxis: {
        type: "value",
        splitLine: { lineStyle: { color: token("--rule") } },
        axisLabel: { color: t.muted, fontSize: 10 },
      },
      yAxis: {
        type: "category",
        data: cats,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: t.ink2, fontSize: 12, fontWeight: 600 },
      },
      series: [
        {
          name: "Audited",
          type: "bar",
          stack: "x",
          barWidth: 16,
          itemStyle: {
            color: (p: { dataIndex: number }) => colors[p.dataIndex],
            borderRadius: [0, 0, 0, 0],
          },
          data: audited,
        },
        {
          name: "Reported / provisional",
          type: "bar",
          stack: "x",
          barWidth: 16,
          itemStyle: {
            color: (p: { dataIndex: number }) => colors[p.dataIndex],
            opacity: 0.4,
            borderRadius: [0, 4, 4, 0],
          },
          label: {
            show: true,
            position: "right",
            formatter: (p: { dataIndex: number }) =>
              String(m.byLab[labs.slice().reverse()[p.dataIndex]]),
            color: t.ink,
            fontSize: 11,
            fontWeight: 600,
          },
          data: rest,
        },
      ],
    };
  }, [labs, m, themeKey]);

  return (
    <Card>
      <CardTitle
        title="Problems credited per lab"
        sub="Solid segment = audited; faded = reported or provisional."
      />
      <EChart
        option={option}
        themeKey={themeKey}
        height={Math.max(labs.length * 42, 120)}
        ariaLabel="Bar chart of problems credited per lab"
      />
    </Card>
  );
}
