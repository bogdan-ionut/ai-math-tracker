import { useEffect, useState } from "react";
import type { MathResult, Summary } from "@/types/result";

interface DatasetState {
  results: MathResult[] | null;
  summary: Summary | null;
  error: string | null;
  loading: boolean;
}

const base = import.meta.env.BASE_URL; // respects Vite `base` on GitHub Pages

export function useDataset(): DatasetState {
  const [state, setState] = useState<DatasetState>({
    results: null,
    summary: null,
    error: null,
    loading: true,
  });

  useEffect(() => {
    let alive = true;
    Promise.all([
      fetch(`${base}data/conjectures.json`).then((r) => {
        if (!r.ok) throw new Error(`conjectures.json ${r.status}`);
        return r.json();
      }),
      fetch(`${base}data/summary.json`).then((r) => {
        if (!r.ok) throw new Error(`summary.json ${r.status}`);
        return r.json();
      }),
    ])
      .then(([results, summary]) => {
        if (!alive) return;
        setState({ results, summary, error: null, loading: false });
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setState({
          results: null,
          summary: null,
          error: e instanceof Error ? e.message : "Failed to load data",
          loading: false,
        });
      });
    return () => {
      alive = false;
    };
  }, []);

  return state;
}
