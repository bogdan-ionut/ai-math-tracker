import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

/**
 * Owns the colour theme. The value is lifted to App so that changing it
 * re-renders the charts too — ECharts reads CSS tokens at init time, so it
 * must be re-initialised when the palette swaps.
 */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(
    () => (document.documentElement.getAttribute("data-theme") as Theme) || "dark",
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("theme", theme);
    } catch {
      /* storage may be unavailable — the attribute is what matters */
    }
  }, [theme]);

  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return [theme, toggle];
}
