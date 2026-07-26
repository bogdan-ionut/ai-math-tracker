import { useEffect, useState } from "react";
import type { SignalFeed } from "@/types/signal";

const base = import.meta.env.BASE_URL;

/** Load the automated signal feed.
 *
 * A missing or malformed feed is *not* an error state. Signals are an optional
 * secondary surface, and the tracker must render perfectly without them —
 * failing the whole page because an unverified sidebar is unavailable would let
 * the least trustworthy data take the most important page down.
 */
export function useSignals(): SignalFeed | null {
  const [feed, setFeed] = useState<SignalFeed | null>(null);

  useEffect(() => {
    let alive = true;
    fetch(`${base}data/signals.json`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: SignalFeed | null) => {
        if (!alive || !data || !Array.isArray(data.signals)) return;
        setFeed(data);
      })
      .catch(() => {
        /* silent by design — see above */
      });
    return () => {
      alive = false;
    };
  }, []);

  return feed;
}
