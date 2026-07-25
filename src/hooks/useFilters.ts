import { useCallback, useEffect, useState } from "react";
import { type Filters, filtersFromParams, filtersToParams } from "@/lib/filters";

/**
 * Filter state backed by the URL query string, so any view is shareable
 * (?status=audited&lab=oa&from=2026-05-01). Back/forward buttons work too.
 */
export function useFilters(): [Filters, (next: Partial<Filters>) => void, () => void] {
  const [filters, setFilters] = useState<Filters>(() =>
    filtersFromParams(new URLSearchParams(window.location.search)),
  );

  useEffect(() => {
    const onPop = () => setFilters(filtersFromParams(new URLSearchParams(window.location.search)));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const update = useCallback((next: Partial<Filters>) => {
    setFilters((prev) => {
      const merged = { ...prev, ...next };
      const params = filtersToParams(merged);
      const qs = params.toString();
      const url = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
      window.history.replaceState(null, "", url);
      return merged;
    });
  }, []);

  const reset = useCallback(() => {
    window.history.replaceState(null, "", window.location.pathname);
    setFilters(filtersFromParams(new URLSearchParams()));
  }, []);

  return [filters, update, reset];
}
