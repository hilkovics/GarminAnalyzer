// Presentation of the §12 health metrics: values by unit, signed differences, categorical series colours.
import { DASH, fmtDuration, fmtNum, MINUS, valid } from "@/lib/format";

type Num = number | null | undefined;

/** Fixed categorical order for overlaid metrics (tokens --cat1…4, validated in both themes). */
export const SERIES_COLORS = ["var(--cat1)", "var(--cat2)", "var(--cat3)", "var(--cat4)"];

/** A metric value in its unit: seconds as h:mm, breaths with one decimal, everything else whole. */
export function fmtMetric(value: Num, unit: string): string {
  if (!valid(value)) return DASH;
  if (unit === "s") return `${fmtDuration(value)} h`;
  if (unit === "dych/min") return fmtNum(value, 1, "dych/min");
  if (unit === "bpm" || unit === "min" || unit === "TSS-ekv.") return fmtNum(value, 0, unit);
  return fmtNum(value, 0);
}

/** A signed difference in the metric's unit ("+0:12 h", "−3 bpm"). */
export function fmtMetricDiff(value: Num, unit: string): string {
  if (!valid(value)) return DASH;
  const sign = value > 0 ? "+" : value < 0 ? MINUS : "±";
  return `${sign}${fmtMetric(Math.abs(value), unit)}`;
}

/** Axis ticks: hours for seconds, plain numbers otherwise. */
export function axisTick(unit: string): (v: number) => string {
  return unit === "s" ? (v) => fmtNum(v / 3600, 1) : (v) => fmtNum(v, unit === "dych/min" ? 1 : 0);
}

export const axisUnit = (unit: string) => (unit === "s" ? "h" : unit);
