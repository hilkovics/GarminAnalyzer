// Geometry and labels of the mini ρ axis (as ui-streamlit/components/rho.py). Pure functions, no React.
import type { Schemas } from "@/api/client";
import { DASH, fmtSigned, valid } from "@/lib/format";

export type Finding = Schemas["CorrelationDTO"];

export const RHO_WIDTH = 300;
export const RHO_HEIGHT = 38;
export const RHO_PAD = 14;
export const RHO_AXIS_Y = 12;

/** (ρ, CI low, CI high) of the headline statistic: the partial ρ if there is one, else the raw ρ. */
export function headline(f: Finding): { rho: number | null; low: number | null; high: number | null } {
  if (valid(f.partial_rho)) return { rho: f.partial_rho, low: f.partial_ci_low, high: f.partial_ci_high };
  return { rho: f.rho, low: f.ci_low, high: f.ci_high };
}

/** ρ ∈ [−1, 1] (clamped) → x in the SVG viewBox. */
export function rhoX(value: number): number {
  const clamped = Math.max(-1, Math.min(1, value));
  return RHO_PAD + ((clamped + 1) / 2) * (RHO_WIDTH - 2 * RHO_PAD);
}

/** "+0,35" or "+0,35 [95 % CI −0,10; +0,55]"; missing → "–". */
export function fmtRho(rho: number | null | undefined, low?: number | null, high?: number | null): string {
  if (!valid(rho)) return DASH;
  const ci = valid(low) && valid(high) ? ` [95 % CI ${fmtSigned(low, 2)}; ${fmtSigned(high, 2)}]` : "";
  return fmtSigned(rho, 2) + ci;
}

/** "n = 51 · parciálne ρ = … · surové ρ = …" (the statistics line under a finding). */
export function statsLine(f: Finding): string {
  const raw = `ρ = ${fmtRho(f.rho, f.ci_low, f.ci_high)}`;
  if (valid(f.partial_rho)) return `n = ${f.n} · parciálne ρ = ${fmtRho(f.partial_rho, f.partial_ci_low, f.partial_ci_high)} · surové ${raw}`;
  return `n = ${f.n} · ${raw}`;
}

/** Colour of the dot / whisker: muted when uncertain, accent for positive ρ, orange for negative. */
export function rhoColor(rho: number, uncertain: boolean): string {
  if (uncertain) return "var(--neutral)";
  return rho >= 0 ? "var(--accent)" : "var(--bike)";
}
