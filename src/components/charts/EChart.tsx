import { useEffect, useRef } from "react";
import type { EChartsCoreOption } from "echarts/core";
import { echarts } from "@/lib/echarts";

/**
 * Thin React wrapper around an ECharts SVG instance. Re-applies options when
 * `option` or `themeKey` changes, and resizes with its container.
 */
export function EChart({
  option,
  themeKey,
  height = 320,
  className = "",
  ariaLabel,
}: {
  option: EChartsCoreOption;
  themeKey: string; // bump to force a full re-init (e.g. on theme switch)
  height?: number;
  className?: string;
  ariaLabel?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "svg" });
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [themeKey]);

  useEffect(() => {
    chart.current?.setOption(option, true);
  }, [option]);

  return (
    <div
      ref={ref}
      role="img"
      aria-label={ariaLabel}
      className={className}
      style={{ width: "100%", height }}
    />
  );
}
