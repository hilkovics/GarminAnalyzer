// Shared presentation pieces of the Kokpit design. No data fetching, no formulas.
import type { ReactNode } from "react";

import type { ApiError } from "@/api/client";

export function cx(...names: (string | false | null | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}

export function Card({
  title,
  right,
  children,
  className,
  padded = true,
}: {
  title?: ReactNode;
  right?: ReactNode;
  children?: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={cx("rounded-xl border border-line bg-card", padded && "p-4 sm:p-5", className)}>
      {(title || right) && (
        <header className="mb-3 flex items-start justify-between gap-3">
          {title ? <h2 className="label">{title}</h2> : <span />}
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export type Tone = "green" | "yellow" | "red" | "blue" | "gray" | "orange";

const TONES: Record<Tone, string> = {
  green: "bg-good/15 text-good ring-good/40",
  yellow: "bg-warn/15 text-warn ring-warn/40",
  red: "bg-bad/15 text-bad ring-bad/40",
  blue: "bg-accent/15 text-accent ring-accent/40",
  gray: "bg-muted/10 text-muted ring-line-strong",
  orange: "bg-bike/15 text-bike ring-bike/40",
};

export function Badge({ tone = "gray", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={cx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ring-1", TONES[tone])}>
      {children}
    </span>
  );
}

/** A metric tile: small caps label with an optional colour dash, a big number, unit and badge. */
export function Stat({
  label,
  value,
  unit,
  color,
  badge,
  hint,
  valueClass,
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  color?: string;
  badge?: ReactNode;
  hint?: string;
  valueClass?: string;
}) {
  return (
    <div className="min-w-0" title={hint}>
      <div className="label flex items-center gap-1.5">
        {color && <span className="inline-block h-0.5 w-2.5 rounded" style={{ background: color }} />}
        {label}
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-1.5">
        <span className={cx("num text-3xl font-semibold leading-none", valueClass)}>{value}</span>
        {unit && <span className="text-xs text-muted">{unit}</span>}
        {badge}
      </div>
    </div>
  );
}

export function Meta({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div className="num mt-0.5 text-lg font-semibold leading-tight">{children}</div>
    </div>
  );
}

export function Loading({ label = "Načítavam…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-muted" role="status">
      <span className="h-3 w-3 animate-pulse rounded-full bg-accent" />
      {label}
    </div>
  );
}

export function ErrorBox({ error, children }: { error?: ApiError | Error | null; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad" role="alert">
      {children ?? error?.message ?? "Chyba"}
    </div>
  );
}

export function Notice({ tone = "gray", children }: { tone?: "gray" | "yellow" | "red" | "green"; children: ReactNode }) {
  const styles = {
    gray: "border-line bg-card-2 text-muted",
    yellow: "border-warn/40 bg-warn/10 text-warn",
    red: "border-bad/40 bg-bad/10 text-bad",
    green: "border-good/40 bg-good/10 text-good",
  }[tone];
  return <div className={cx("rounded-lg border px-3 py-2 text-sm", styles)}>{children}</div>;
}

/** Query state in one place: spinner, error or the content. */
export function QueryState<T>({
  query,
  children,
  loading,
}: {
  query: { data?: T; error: ApiError | null; isPending: boolean };
  children: (data: T) => ReactNode;
  loading?: string;
}) {
  if (query.isPending) return <Loading label={loading} />;
  if (query.error || query.data === undefined) return <ErrorBox error={query.error} />;
  return <>{children(query.data)}</>;
}

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-line bg-card-2 p-0.5 text-xs">
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            "rounded-md px-2.5 py-1 font-medium transition-colors",
            o.value === value ? "bg-card text-text shadow-sm ring-1 ring-line-strong" : "text-muted hover:text-text",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  type = "button",
  className,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  const styles = {
    primary: "bg-accent text-accent-text hover:brightness-110",
    secondary: "border border-line-strong bg-card text-text hover:bg-card-2",
    ghost: "text-accent hover:underline",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50",
        styles,
        className,
      )}
    >
      {children}
    </button>
  );
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h1 className="text-2xl font-bold sm:text-3xl">{title}</h1>
        {subtitle && <span className="text-sm text-muted">{subtitle}</span>}
      </div>
      {right}
    </div>
  );
}

export function Table({ head, rows, align }: { head: ReactNode[]; rows: ReactNode[][]; align?: ("left" | "right")[] }) {
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full min-w-max border-collapse text-sm">
        <thead>
          <tr className="border-b border-line-strong text-left text-xs text-muted">
            {head.map((h, i) => (
              <th key={i} className={cx("px-1 py-1.5 font-medium", align?.[i] === "right" && "text-right")}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="border-b border-line last:border-0">
              {row.map((cell, i) => (
                <td key={i} className={cx("num px-1 py-1.5", align?.[i] === "right" && "text-right")}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
