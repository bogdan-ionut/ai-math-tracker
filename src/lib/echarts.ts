import * as echarts from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkAreaComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkAreaComponent,
  SVGRenderer, // SVG default: crisp text/lines for a few thousand points
]);

export { echarts };

/** Read a CSS token ("R G B") off :root and return an rgb() / rgba() string. */
export function token(name: string, alpha = 1): string {
  if (typeof window === "undefined") return "#888";
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!raw) return "#888";
  return alpha >= 1 ? `rgb(${raw})` : `rgba(${raw} / ${alpha})`;
}

export interface ChartTheme {
  ink: string;
  ink2: string;
  muted: string;
  line: string;
  surface: string;
  axis: string;
  fontSans: string;
  fontMono: string;
}

export function chartTheme(): ChartTheme {
  return {
    ink: token("--ink"),
    ink2: token("--ink-2"),
    muted: token("--muted"),
    line: token("--rule"),
    surface: token("--panel"),
    axis: token("--rule"),
    fontSans: "'Inter Variable', Inter, system-ui, sans-serif",
    fontMono: "'JetBrains Mono', ui-monospace, monospace",
  };
}

/** Shared tooltip chrome used across ECharts instances. */
export function tooltipStyle(t: ChartTheme) {
  return {
    backgroundColor: t.surface,
    borderColor: token("--rule"),
    borderWidth: 1,
    padding: [8, 11] as [number, number],
    textStyle: { color: t.ink2, fontFamily: t.fontSans, fontSize: 12 },
    extraCssText: "border-radius:8px; box-shadow:0 6px 24px rgba(0,0,0,.18);",
  };
}
