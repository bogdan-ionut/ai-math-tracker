import { useMemo, useState } from "react";
import type { MathResult } from "@/types/result";
import { useDataset } from "@/hooks/useDataset";
import { useFilters } from "@/hooks/useFilters";
import { useSignals } from "@/hooks/useSignals";
import { useTheme } from "@/hooks/useTheme";
import { applyFilters, computeMetrics } from "@/lib/filters";
import { Masthead } from "@/components/Masthead";
import { FilterBar } from "@/components/FilterBar";
import { Landmarks } from "@/components/Landmarks";
import { ImpactConstellation } from "@/components/charts/ImpactConstellation";
import { CumulativeTimeline } from "@/components/charts/CumulativeTimeline";
import { LabBars } from "@/components/charts/LabBars";
import { LabLanes } from "@/components/charts/LabLanes";
import { FortnightGrid } from "@/components/charts/FortnightGrid";
import { Ledger } from "@/components/Ledger";
import { ResultDrawer } from "@/components/ResultDrawer";
import { MethodologyFooter } from "@/components/MethodologyFooter";
import { SignalsPanel } from "@/components/SignalsPanel";
import { Card, CardTitle } from "@/components/ui/primitives";

export function App() {
  const { results, summary, error, loading } = useDataset();
  const [filters, update, reset] = useFilters();
  const [selected, setSelected] = useState<MathResult | null>(null);

  const signals = useSignals();
  const [theme, toggleTheme] = useTheme();
  const themeKey = theme;

  const filtered = useMemo(
    () => (results ? applyFilters(results, filters) : []),
    [results, filters],
  );
  const metrics = useMemo(() => computeMetrics(filtered), [filtered]);
  const families = useMemo(
    () => (results ? [...new Set(results.map((r) => r.family))].sort() : []),
    [results],
  );

  return (
    <div className="paper-ground min-h-screen">
      <div className="mx-auto max-w-6xl px-5 pb-16 sm:px-8">
        {loading && <SkeletonState />}

        {error && (
          <div className="mt-16 rounded-xl2 border border-[rgb(var(--lab-dm)/0.5)] bg-panel p-6 text-sm text-ink-2">
            <p className="font-semibold text-ink">Couldn’t load the dataset.</p>
            <p className="mt-1 text-muted">{error}</p>
            <p className="mt-2 text-xs text-muted">
              Run <code className="mono">python scripts/build_data.py</code> to regenerate{" "}
              <code className="mono">public/data</code>, then reload.
            </p>
          </div>
        )}

        {results && !error && (
          <>
            <Masthead
              m={metrics}
              rangeEnd={summary?.rangeEnd}
              generatedAt={summary?.generatedAt}
              theme={theme}
              onToggleTheme={toggleTheme}
            />

            <FilterBar
              filters={filters}
              update={update}
              reset={reset}
              families={families}
              shown={metrics.total}
              total={summary?.total ?? metrics.total}
            />

            <div className="space-y-10">
              <Landmarks rows={filtered} onSelect={setSelected} />

              <Card>
                <CardTitle
                  title="The impact constellation"
                  sub="Every result by date and assessed impact. Circle area is the number of problems covered; filled marks are audited, hollow marks are not. The story of 2026 is the shape of this cloud — dense at the bottom, sparse at the top."
                />
                <ImpactConstellation rows={filtered} onSelect={setSelected} />
              </Card>

              <CumulativeTimeline rows={filtered} themeKey={themeKey} />

              <LabLanes rows={filtered} themeKey={themeKey} onSelect={setSelected} />

              <div className="grid gap-6 lg:grid-cols-2">
                <FortnightGrid rows={filtered} themeKey={themeKey} onSelect={setSelected} />
                <LabBars m={metrics} themeKey={themeKey} />
              </div>

              <Ledger rows={filtered} onSelect={setSelected} />
              <MethodologyFooter />

              <SignalsPanel feed={signals} />
            </div>

            <footer className="mt-12 border-t border-rule pt-5 text-[11px] leading-relaxed text-muted">
              Built with Vite · React · ECharts, over a Python/Pydantic data pipeline.
              Curated and versioned; deployed statically to GitHub Pages. Impact scores are
              editorial judgements, not measurements — every one carries its reasoning.
            </footer>
          </>
        )}

        <ResultDrawer result={selected} onClose={() => setSelected(null)} />
      </div>
    </div>
  );
}

function SkeletonState() {
  return (
    <div className="animate-pulse space-y-6 pt-24">
      <div className="h-24 w-2/3 rounded-xl2 bg-panel" />
      <div className="grid gap-3 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-52 rounded-xl2 border border-rule bg-panel" />
        ))}
      </div>
      <div className="h-96 rounded-xl2 border border-rule bg-panel" />
    </div>
  );
}
