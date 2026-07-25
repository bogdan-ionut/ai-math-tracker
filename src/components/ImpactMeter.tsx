import { IMPACT_LABELS } from "@/lib/impact";

/** Five ticks, filled to the score. One hue, more-is-brighter — never a rainbow. */
export function ImpactMeter({
  value,
  size = "sm",
  showLabel = false,
}: {
  value: number | null | undefined;
  size?: "sm" | "lg";
  showLabel?: boolean;
}) {
  if (!value) {
    return (
      <span className="text-[11px] italic text-muted" title="Not yet assessed">
        —
      </span>
    );
  }
  const w = size === "lg" ? 7 : 5;
  const h = size === "lg" ? 20 : 13;
  return (
    <span
      className="inline-flex items-center gap-2"
      title={`Impact ${value}/5 — ${IMPACT_LABELS[value]}`}
    >
      <span className="inline-flex items-end gap-[2px]">
        {[1, 2, 3, 4, 5].map((i) => (
          <span
            key={i}
            style={{
              width: w,
              height: Math.round(h * (0.45 + 0.14 * i)),
              background:
                i <= value ? `rgb(var(--ink) / ${0.45 + 0.11 * value})` : "rgb(var(--rule))",
            }}
            className="rounded-[1px]"
          />
        ))}
      </span>
      {showLabel && (
        <span className="text-[11px] text-ink-2">{IMPACT_LABELS[value]}</span>
      )}
    </span>
  );
}
