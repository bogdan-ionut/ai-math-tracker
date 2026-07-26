import type { EvidenceTier, Signal, SignalFeed } from "@/types/signal";
import { Eyebrow } from "@/components/ui/primitives";

/**
 * Unverified automated signals.
 *
 * Rendered deliberately *unlike* the tracker: dashed rule, no card chrome,
 * monospaced and small, below the methodology. Nothing here is counted in any
 * figure on the page, and none of it uses `--good` — green means audited, and
 * an audited claim is the one thing a signal can never be.
 *
 * The panel disappears entirely when there are no signals rather than showing
 * an empty state, because an empty box implies the pipeline is running and
 * finding nothing, which is a stronger claim than we can make.
 */

const TIER_LABEL: Record<EvidenceTier, string> = {
  published: "DOI or arXiv",
  registered: "known problem",
  referenced: "code link only",
  none: "no reference",
};

const TIER_TOKEN: Record<EvidenceTier, string> = {
  published: "--ink-2",
  registered: "--muted",
  referenced: "--muted",
  none: "--muted",
};

function ids(signal: Signal): string {
  const parts = Object.entries(signal.externalIds || {}).flatMap(([kind, values]) =>
    (values || []).map((v) => `${kind}:${v}`),
  );
  return parts.join("  ") || "—";
}

function SignalRow({ signal }: { signal: Signal }) {
  return (
    <li className="border-t border-dashed border-rule py-3 first:border-t-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-sm text-ink-2">{signal.canonicalName || signal.id}</span>
        <span
          className="mono text-[10px] uppercase tracking-wider"
          style={{ color: `rgb(var(${TIER_TOKEN[signal.evidenceTier]}))` }}
          title="What kind of external reference was found — not a verdict on the claim"
        >
          {TIER_LABEL[signal.evidenceTier]}
        </span>
      </div>
      <p className="mono mt-1 text-[11px] leading-relaxed text-muted">
        {ids(signal)}
        {signal.modelName ? `  ·  ${signal.modelName}` : ""}
        {signal.organization ? `  ·  ${signal.organization}` : ""}
        {`  ·  ${signal.observationCount} post${signal.observationCount === 1 ? "" : "s"}`}
      </p>
      {signal.sources.length > 0 && (
        <p className="mt-1 text-[11px] text-muted">
          {signal.sources.slice(0, 2).map((href) => (
            <a
              key={href}
              href={href}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="mr-3 underline decoration-dotted underline-offset-2 hover:text-ink-2"
            >
              source
            </a>
          ))}
        </p>
      )}
    </li>
  );
}

export function SignalsPanel({ feed }: { feed: SignalFeed | null }) {
  if (!feed || feed.signals.length === 0) return null;

  return (
    <section className="mt-14 border-t border-dashed border-rule pt-8">
      <Eyebrow>Not part of the tracker</Eyebrow>
      <h2 className="display mt-2 text-lg font-bold tracking-tight text-ink-2">
        Unverified automated signals
      </h2>
      <p className="mt-2 max-w-prose text-xs leading-relaxed text-muted">
        {feed.disclaimer} They are posts a scraper grouped by problem, shown here so the
        pipeline&rsquo;s working set is visible rather than hidden. A signal becomes a result
        only after a human reviews it and merges a pull request — never automatically.
      </p>

      <ul className="mt-5">
        {feed.signals.slice(0, 25).map((s) => (
          <SignalRow key={s.id} signal={s} />
        ))}
      </ul>

      {feed.signals.length > 25 && (
        <p className="mono mt-3 text-[11px] text-muted">
          + {feed.signals.length - 25} more not shown
        </p>
      )}
    </section>
  );
}
