// Display-only axis helpers of the Progres charts (as ui-streamlit/components/pace_axis.py):
// m/s → s/km for the pace axes and "nice" tick positions. No metric is computed here.
import { fmtPaceS, parseDate, valid } from "@/lib/format";

export const PACE_CAP_S = 900; // slower than 15:00/km is not drawn

/** m/s → s/km for display; missing, non-positive or slower than the cap → null. */
export function paceS(speed: number | null | undefined): number | null {
  if (!valid(speed) || speed <= 0) return null;
  const pace = 1000 / speed;
  return pace <= PACE_CAP_S ? pace : null;
}

/** Tick positions (s/km) every 15 / 30 / 60 s depending on the range, covering all values. */
export function paceTicks(values: (number | null | undefined)[]): number[] {
  const v = values.filter(valid);
  if (!v.length) return [];
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const span = hi - lo;
  const step = span > 300 ? 60 : span > 90 ? 30 : 15;
  const ticks: number[] = [];
  for (let t = Math.floor(lo / step) * step; ; t += step) {
    ticks.push(t);
    if (t >= hi) break;
  }
  return ticks;
}

/** Y axis props of a pace chart: faster on top, m:ss labels, domain = outermost ticks. */
export function paceAxis(values: (number | null | undefined)[]) {
  const ticks = paceTicks(values);
  return {
    reversed: true,
    ticks,
    domain: ticks.length ? ([ticks[0], ticks[ticks.length - 1]] as [number, number]) : (["auto", "auto"] as [string, string]),
    tickFormatter: (t: number) => fmtPaceS(t),
  };
}

/** An API date → a numeric x value (local midnight) for a time axis. */
export const dateX = (iso: string): number => parseDate(iso).getTime();

/** `count` evenly spaced timestamps from min to max (inclusive) for date axes. */
export function dateTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (max <= min) return [min];
  return Array.from({ length: count }, (_, i) => Math.round(min + ((max - min) * i) / (count - 1)));
}

/** Ticks at multiples of `step` covering [lo, hi]; the step grows (x2) until there are at most `max` ticks. */
export function niceTicks(lo: number, hi: number, step: number, max = 6): number[] {
  let s = step;
  while (Math.ceil(hi / s) - Math.floor(lo / s) + 1 > max) s *= 2;
  const out: number[] = [];
  for (let t = Math.floor(lo / s) * s; t <= Math.ceil(hi / s) * s; t += s) out.push(t);
  return out;
}
