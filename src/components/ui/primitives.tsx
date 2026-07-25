import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl2 border border-rule bg-panel p-5 sm:p-6 ${className}`}
    >
      {children}
    </section>
  );
}

export function CardTitle({ title, sub }: { title: string; sub?: string }) {
  return (
    <header className="mb-4">
      <h2 className="display text-xl font-bold tracking-tight text-ink">{title}</h2>
      {sub && <p className="mt-1 max-w-prose text-xs leading-relaxed text-muted">{sub}</p>}
    </header>
  );
}

export function Dot({ token: t, size = 10 }: { token: string; size?: number }) {
  return (
    <span
      className="inline-block flex-none rounded-full"
      style={{ width: size, height: size, background: `rgb(var(${t}))` }}
    />
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
      {children}
    </p>
  );
}
