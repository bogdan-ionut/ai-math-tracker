import { Search, X } from "lucide-react";
import type { Filters } from "@/lib/filters";
import { isActive } from "@/lib/filters";
import { LABS, LAB_ORDER, STATUS_META, STATUS_ORDER } from "@/lib/labs";
import type { LabKey, Status } from "@/types/result";
import { IMPACT_LABELS } from "@/lib/impact";

const RANGE = "2026-01-01";
const RANGE_END = "2026-07-24";

const PRESETS: { label: string; from: string | null; to: string | null }[] = [
  { label: "All", from: null, to: null },
  { label: "H1", from: "2026-01-01", to: "2026-06-30" },
  { label: "July", from: "2026-07-01", to: RANGE_END },
  { label: "Last 14d", from: "2026-07-11", to: RANGE_END },
];

function toggle<T>(arr: T[], v: T): T[] {
  return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v];
}

export function FilterBar({
  filters,
  update,
  reset,
  families,
  shown,
  total,
}: {
  filters: Filters;
  update: (n: Partial<Filters>) => void;
  reset: () => void;
  families: string[];
  shown: number;
  total: number;
}) {
  const activePreset = PRESETS.find((p) => p.from === filters.from && p.to === filters.to);

  return (
    <div className="sticky top-0 z-20 -mx-4 mb-6 border-b border-rule bg-void/85 px-4 py-3 backdrop-blur-md sm:-mx-6 sm:px-6">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        {/* Date presets + custom */}
        <div className="flex items-center gap-1.5">
          {PRESETS.map((p) => {
            const on = activePreset?.label === p.label;
            return (
              <button
                key={p.label}
                onClick={() => update({ from: p.from, to: p.to })}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  on ? "bg-ink text-void" : "text-ink-2 hover:bg-panel-2"
                }`}
              >
                {p.label}
              </button>
            );
          })}
          <div className="ml-1 flex items-center gap-1 font-mono text-[11px] text-muted">
            <input
              type="date"
              value={filters.from ?? ""}
              min={RANGE}
              max={RANGE_END}
              onChange={(e) => update({ from: e.target.value || null })}
              className="rounded border border-rule bg-panel px-1.5 py-1 text-ink-2 [color-scheme:dark]"
              aria-label="From date"
            />
            <span>→</span>
            <input
              type="date"
              value={filters.to ?? ""}
              min={RANGE}
              max={RANGE_END}
              onChange={(e) => update({ to: e.target.value || null })}
              className="rounded border border-rule bg-panel px-1.5 py-1 text-ink-2 [color-scheme:dark]"
              aria-label="To date"
            />
          </div>
        </div>

        <Divider />

        {/* Status */}
        <div className="flex items-center gap-1.5">
          {STATUS_ORDER.map((s) => (
            <Chip
              key={s}
              on={filters.statuses.includes(s)}
              token={STATUS_META[s].token}
              label={STATUS_META[s].label}
              onClick={() => update({ statuses: toggle<Status>(filters.statuses, s) })}
            />
          ))}
        </div>

        <Divider />

        {/* Labs */}
        <div className="flex items-center gap-1.5">
          {LAB_ORDER.map((l) => (
            <Chip
              key={l}
              on={filters.labs.includes(l)}
              token={LABS[l].token}
              label={LABS[l].short}
              onClick={() => update({ labs: toggle<LabKey>(filters.labs, l) })}
            />
          ))}
        </div>

        <Divider />

        {/* Impact */}
        <div className="flex items-center gap-1">
          <span className="mr-1 text-[10px] uppercase tracking-wider text-muted">Impact</span>
          {[5, 4, 3, 2, 1].map((lvl) => {
            const on = filters.impacts.includes(lvl);
            return (
              <button
                key={lvl}
                onClick={() => update({ impacts: toggle(filters.impacts, lvl) })}
                title={IMPACT_LABELS[lvl]}
                className={`mono h-6 w-6 rounded text-[11px] transition-colors ${
                  on ? "bg-ink text-void" : "border border-rule text-ink-2 hover:bg-panel-2"
                }`}
              >
                {lvl}
              </button>
            );
          })}
        </div>

        {/* Search + count + reset pushed right */}
        <div className="ml-auto flex items-center gap-3">
          <label className="flex items-center gap-1.5 rounded-md border border-rule bg-panel px-2 py-1">
            <Search size={13} className="text-muted" />
            <input
              value={filters.query}
              onChange={(e) => update({ query: e.target.value })}
              placeholder="Search…"
              className="w-28 bg-transparent text-xs text-ink placeholder:text-muted focus:outline-none"
            />
          </label>
          <span className="hidden font-mono text-[11px] text-muted sm:inline">
            {shown === total ? `${total}` : `${shown} / ${total}`}
          </span>
          {isActive(filters) && (
            <button
              onClick={reset}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-ink-2 hover:bg-panel-2"
            >
              <X size={12} /> Clear
            </button>
          )}
        </div>
      </div>

      {/* Family row (only when there are several) */}
      {families.length > 1 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {families.map((f) => (
            <button
              key={f}
              onClick={() => update({ families: toggle(filters.families, f) })}
              className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
                filters.families.includes(f)
                  ? "border-ink bg-ink text-void"
                  : "border-rule text-ink-2 hover:bg-panel-2"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Divider() {
  return <span className="hidden h-5 w-px bg-rule sm:block" />;
}

function Chip({
  on,
  token,
  label,
  onClick,
}: {
  on: boolean;
  token: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors ${
        on ? "border-ink/40 bg-panel-2 text-ink" : "border-transparent text-ink-2 hover:bg-panel-2"
      }`}
    >
      <span
        className="h-2.5 w-2.5 flex-none rounded-full"
        style={{ background: `rgb(var(${token}))`, opacity: on ? 1 : 0.55 }}
      />
      {label}
    </button>
  );
}
