import { STATUS_META, STATUS_ORDER } from "@/lib/labs";
import { Card, CardTitle } from "./ui/primitives";

export function MethodologyFooter() {
  return (
    <Card className="bg-transparent">
      <CardTitle title="Methodology" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {STATUS_ORDER.map((s) => (
          <div key={s} className="rounded-lg border border-rule p-3">
            <div className="mb-1 flex items-center gap-2">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ background: `rgb(var(${STATUS_META[s].token}))` }}
              />
              <span className="text-sm font-semibold text-ink">{STATUS_META[s].label}</span>
            </div>
            <p className="text-xs leading-relaxed text-muted">{STATUS_META[s].blurb}</p>
          </div>
        ))}
      </div>
      <div className="mt-5 space-y-2 text-[11px] leading-relaxed text-muted">
        <p>
          Every distinct problem is counted once. Batches (the 44 OEIS conjectures, the
          26-problem “Star Fleet” run) are single records with a count and, where identities
          are known, an expandable member list. <span className="text-ink-2">claimedAt</span> and{" "}
          <span className="text-ink-2">auditedAt</span> are kept separate — an announcement is
          never shown as a confirmation. Green is reserved for audited results only.
        </p>
        <p>
          Excluded to avoid double-counting and over-claiming: partial results,
          rediscoveries, literature identifications, benchmark batches (FirstProof), and
          duplicate listings. Graffiti 154 is treated as disputed (a community note dates the
          refutation to June 2026). Data is curated and validated by a Python/Pydantic
          pipeline; the July 22–24 items are provisional and not yet independently verified.
        </p>
      </div>
    </Card>
  );
}
