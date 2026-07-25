import { Moon, Sun } from "lucide-react";
import type { Metrics } from "@/lib/filters";
import type { Theme } from "@/hooks/useTheme";

export function Masthead({
  m,
  rangeEnd,
  generatedAt,
  theme,
  onToggleTheme: toggle,
}: {
  m: Metrics;
  rangeEnd?: string;
  generatedAt?: string;
  theme: Theme;
  onToggleTheme: () => void;
}) {

  return (
    <header className="pb-8 pt-2">
      <div className="flex items-start justify-between gap-6">
        <p className="eyebrow">
          AI × Mathematics — a ledger of machine-made proofs · 2026
        </p>
        <button
          onClick={toggle}
          aria-label="Toggle colour theme"
          className="flex-none rounded-lg border border-rule p-2 text-muted transition-colors hover:text-ink"
        >
          {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </div>

      <h1 className="display mt-5 max-w-[15ch] text-[clamp(44px,8vw,92px)] leading-[0.92] text-ink">
        The Year the Theorems Fell
      </h1>

      <div className="mt-7 flex flex-col gap-6 border-t border-rule pt-6 lg:flex-row lg:items-end lg:justify-between">
        <p className="max-w-[54ch] text-[13.5px] leading-relaxed text-ink-2">
          In 2026, AI systems were credited with settling more open mathematics than in any
          year on record. This tracks every claim — and, more importantly, grades them:
          how well each one is verified, and how much it actually changed.
          <span className="text-ink"> Most did not. A few changed everything.</span>
        </p>

        <dl className="flex flex-none gap-8">
          <Stat value={m.total} label="claimed" />
          <Stat value={m.byStatus.audited} label="audited" accent />
          <Stat value={m.byImpact[5] ?? 0} label="field-shaping" />
        </dl>
      </div>

      {(rangeEnd || generatedAt) && (
        <p className="mono mt-4 text-[10px] text-muted">
          {rangeEnd && <>data through {rangeEnd}</>}
          {rangeEnd && generatedAt && " · "}
          {generatedAt && (
            <>built {new Date(generatedAt).toISOString().slice(0, 16).replace("T", " ")}Z</>
          )}
        </p>
      )}
    </header>
  );
}

function Stat({
  value,
  label,
  accent = false,
}: {
  value: number;
  label: string;
  accent?: boolean;
}) {
  return (
    <div>
      <dd
        className={`display text-[44px] leading-none ${accent ? "text-good" : "text-ink"}`}
      >
        {value}
      </dd>
      <dt className="eyebrow mt-1.5">{label}</dt>
    </div>
  );
}
