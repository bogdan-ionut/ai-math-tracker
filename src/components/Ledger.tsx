import { useMemo, useState } from "react";
import { ArrowUpDown, ExternalLink } from "lucide-react";
import type { MathResult } from "@/types/result";
import { LABS, STATUS_META } from "@/lib/labs";
import { fmtDate } from "@/lib/format";
import { Card, CardTitle } from "./ui/primitives";
import { ImpactMeter } from "./ImpactMeter";

type SortKey = "date" | "count" | "status" | "lab" | "impact";

const STATUS_RANK = { audited: 0, reported: 1, provisional: 2, disputed: 3 };

export function Ledger({
  rows,
  onSelect,
}: {
  rows: MathResult[];
  onSelect: (r: MathResult) => void;
}) {
  const [sort, setSort] = useState<SortKey>("date");
  const [dir, setDir] = useState<1 | -1>(-1);

  const sorted = useMemo(() => {
    const s = [...rows];
    s.sort((a, b) => {
      let d = 0;
      if (sort === "date") d = a.claimedAt.localeCompare(b.claimedAt);
      else if (sort === "count") d = a.count - b.count;
      else if (sort === "status") d = STATUS_RANK[a.status] - STATUS_RANK[b.status];
      else if (sort === "lab") d = a.lab.localeCompare(b.lab);
      else if (sort === "impact") d = (a.impact ?? -1) - (b.impact ?? -1);
      return d * dir;
    });
    return s;
  }, [rows, sort, dir]);

  const setSortKey = (k: SortKey) => {
    if (k === sort) setDir((x) => (x === 1 ? -1 : 1));
    else {
      setSort(k);
      setDir(k === "date" || k === "count" || k === "impact" ? -1 : 1);
    }
  };

  return (
    <Card>
      <CardTitle
        title="The full ledger"
        sub="Click a row for sources, artifacts, and audit notes. Dates marked ~ are approximate."
      />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-[rgb(var(--ink-2)/0.3)] text-left">
              <Th onClick={() => setSortKey("date")} active={sort === "date"}>Date</Th>
              <th className="px-3 py-2 text-[10.5px] font-semibold uppercase tracking-wider text-muted">
                Problem(s)
              </th>
              <Th onClick={() => setSortKey("count")} active={sort === "count"} align="right">№</Th>
              <th className="px-3 py-2 text-[10.5px] font-semibold uppercase tracking-wider text-muted">
                Resolution
              </th>
              <Th onClick={() => setSortKey("impact")} active={sort === "impact"}>Impact</Th>
              <th className="px-3 py-2 text-[10.5px] font-semibold uppercase tracking-wider text-muted">
                System
              </th>
              <Th onClick={() => setSortKey("lab")} active={sort === "lab"}>Lab</Th>
              <Th onClick={() => setSortKey("status")} active={sort === "status"}>Status</Th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr
                key={r.id}
                onClick={() => onSelect(r)}
                className="cursor-pointer border-b border-rule transition-colors hover:bg-panel-2"
              >
                <td className="whitespace-nowrap px-3 py-2 tnum text-muted">{fmtDate(r.claimedAt)}</td>
                <td className="px-3 py-2 font-medium text-ink">
                  <span
                    className={`flex items-center gap-1.5 ${
                      r.status === "disputed" ? "text-muted line-through" : ""
                    }`}
                  >
                    {r.title}
                    {r.sources.length > 0 && <ExternalLink size={11} className="text-muted" />}
                  </span>
                </td>
                <td className="px-3 py-2 text-right tnum font-semibold text-ink">{r.count}</td>
                <td className="whitespace-nowrap px-3 py-2 text-ink-2">{r.resolution}</td>
                <td className="whitespace-nowrap px-3 py-2">
                  <ImpactMeter value={r.impact} />
                </td>
                <td className="px-3 py-2 text-ink-2">{r.model}</td>
                <td className="whitespace-nowrap px-3 py-2 text-ink-2">
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{ background: `rgb(var(${LABS[r.labKey].token}))` }}
                    />
                    {LABS[r.labKey].name}
                  </span>
                </td>
                <td className="whitespace-nowrap px-3 py-2">
                  <StatusPill status={r.status} />
                </td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-10 text-center text-muted">
                  No results match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Th({
  children,
  onClick,
  active,
  align = "left",
}: {
  children: React.ReactNode;
  onClick: () => void;
  active: boolean;
  align?: "left" | "right";
}) {
  return (
    <th
      className={`px-3 py-2 text-[10.5px] font-semibold uppercase tracking-wider ${
        align === "right" ? "text-right" : "text-left"
      }`}
    >
      <button
        onClick={onClick}
        className={`inline-flex items-center gap-1 ${active ? "text-ink" : "text-muted"} hover:text-ink`}
      >
        {children}
        <ArrowUpDown size={10} />
      </button>
    </th>
  );
}

export function StatusPill({ status }: { status: MathResult["status"] }) {
  const meta = STATUS_META[status];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium"
      style={{
        color: `rgb(var(${meta.token}))`,
        borderColor: `rgb(var(${meta.token}) / 0.4)`,
      }}
    >
      {status === "audited" && "✓ "}
      {meta.label}
    </span>
  );
}
