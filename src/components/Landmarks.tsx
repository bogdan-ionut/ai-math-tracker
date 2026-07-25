import { motion } from "motion/react";
import { ArrowUpRight } from "lucide-react";
import type { MathResult } from "@/types/result";
import { LABS, labColor } from "@/lib/labs";
import { fmtDateLong } from "@/lib/format";
import { ImpactMeter } from "./ImpactMeter";

/**
 * The three (or however many) results judged field-shaping. These carry the
 * page: everything else is volume, these are the ones that changed something.
 */
export function Landmarks({
  rows,
  onSelect,
}: {
  rows: MathResult[];
  onSelect: (r: MathResult) => void;
}) {
  const landmarks = rows
    .filter((r) => r.impact === 5)
    .sort((a, b) => a.claimedAt.localeCompare(b.claimedAt));

  if (!landmarks.length) return null;

  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="eyebrow">Landmark results · impact 5</h2>
        <span className="text-[11px] text-muted">
          {landmarks.length} of {rows.length} records
        </span>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {landmarks.map((r, i) => (
          <motion.button
            key={r.id}
            onClick={() => onSelect(r)}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, delay: i * 0.08 }}
            className="group panel relative overflow-hidden p-5 text-left transition-colors hover:bg-panel-2"
          >
            {/* lab hue rides the top edge */}
            <span
              className="absolute inset-x-0 top-0 h-[2px]"
              style={{ background: labColor(r.labKey) }}
            />
            <div className="flex items-start justify-between gap-3">
              <span className="eyebrow">{r.resolution}</span>
              <ArrowUpRight
                size={15}
                className="flex-none text-muted transition-colors group-hover:text-ink"
              />
            </div>
            <h3 className="display mt-2 text-[26px] leading-[1.12] text-ink">{r.title}</h3>
            <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink-2">{r.assessment}</p>
            <div className="mt-4 flex items-center justify-between border-t border-rule pt-3">
              <span className="flex items-center gap-2 text-[11px] text-muted">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: labColor(r.labKey) }}
                />
                {LABS[r.labKey].name}
                {r.yearsOpen ? ` · open ${r.yearsOpen} yrs` : ""}
              </span>
              <ImpactMeter value={r.impact} />
            </div>
            <p className="mono mt-2 text-[10px] text-muted">{fmtDateLong(r.claimedAt)}</p>
          </motion.button>
        ))}
      </div>
    </section>
  );
}
