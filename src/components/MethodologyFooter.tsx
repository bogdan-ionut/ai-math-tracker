import { STATUS_META, STATUS_ORDER } from "@/lib/labs";
import type { Summary } from "@/types/result";
import { Card, CardTitle } from "./ui/primitives";

/**
 * Methodology — including the parts that do not flatter the dataset.
 *
 * Two things here used to be wrong, and both were the kind a reader has no way
 * to check:
 *
 *   1. It said `claimedAt` and `auditedAt` "are kept separate — an announcement
 *      is never shown as a confirmation". Every audited record has the two dates
 *      equal, so the split this project calls its spine was carrying no
 *      information at all.
 *   2. It said nothing about sources, while 12 of 17 audited records — the only
 *      tier allowed to be green — point at nothing.
 *
 * Both are now *derived from the data* rather than written down. If curation
 * later dates an audit properly, or backfills a source, this text changes on the
 * next build. It cannot drift back into being false while nobody is looking.
 */
export function MethodologyFooter({ summary }: { summary?: Summary | null }) {
  const dating = summary?.auditDating;
  const cover = summary?.sourceCoverage;
  const showCoverage = cover && cover.auditedWithoutSource > 0;
  const showDating = dating && !dating.splitIsInformative && dating.auditedRecords > 0;

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

      {(showCoverage || showDating) && (
        <div className="mt-5 rounded-lg border border-dashed border-rule p-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
            What this dataset does not establish
          </p>
          <ul className="mt-2 space-y-1.5 text-[11px] leading-relaxed text-ink-2">
            {showCoverage && (
              <li>
                <span className="mono text-ink">
                  {cover.auditedWithoutSource} of {cover.auditedTotal}
                </span>{" "}
                audited records carry no source link, and{" "}
                <span className="mono text-ink">
                  {cover.recordsWithoutSource} of{" "}
                  {cover.recordsWithSource + cover.recordsWithoutSource}
                </span>{" "}
                records carry none at all. Audited means a curator judged the evidence
                sufficient — it does not mean you can follow a link and check.
              </li>
            )}
            {showDating && (
              <li>
                Every audited record is dated the day of its own claim (
                <span className="mono text-ink">
                  {dating.sameDayAsClaim}/{dating.auditedRecords}
                </span>
                ), so <span className="text-ink-2">auditedAt</span> currently tells you nothing
                that <span className="text-ink-2">claimedAt</span> did not. The schema keeps the
                two apart; the curation has not yet used the distinction.
              </li>
            )}
          </ul>
        </div>
      )}

      <div className="mt-5 space-y-2 text-[11px] leading-relaxed text-muted">
        <p>
          Every distinct problem is counted once. Batches (the 44 OEIS conjectures, the
          26-problem “Star Fleet” run) are single records with a count and, where identities
          are known, an expandable member list — so a handful of entries account for most of
          the problem total. Green is reserved for audited results only.
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
