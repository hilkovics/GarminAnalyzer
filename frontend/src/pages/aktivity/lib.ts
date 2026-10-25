// Small display helpers of the Aktivity pages: split values for stat tiles, zone bound labels (as
// ui-streamlit/components/format.py fmt_zone_range). Formatting only, no metrics.
import { DASH, fmtNum, fmtPace, fmtPaceS, valid } from "@/lib/format";

/** [value, unit] of the average speed: "4:43" + "/km" for running, "30,2" + "km/h" for cycling. */
export function speedParts(speed: number | null | undefined, sport: string | null | undefined): [string, string] {
  if (!valid(speed) || speed <= 0) return [DASH, ""];
  return sport === "bike" ? [fmtNum(speed * 3.6, 1), "km/h"] : [fmtPaceS(1000 / speed), "/km"];
}

/** Zone bounds → "130–150 bpm" (hr) or "5:30–4:50/km" (pace; bounds are m/s, the lower one is the slower). */
export function zoneRange(lower: number | null, upper: number | null, kind: "hr" | "pace"): string {
  if (kind === "pace") {
    if (!valid(lower) || lower <= 0) return valid(upper) ? `pomalšie ako ${fmtPace(upper)}` : DASH;
    if (!valid(upper)) return `rýchlejšie ako ${fmtPace(lower)}`;
    return `${fmtPaceS(1000 / lower)}–${fmtPace(upper)}`;
  }
  if (!valid(lower) && !valid(upper)) return DASH;
  if (!valid(lower)) return `< ${fmtNum(upper, 0)} bpm`;
  if (!valid(upper)) return `> ${fmtNum(lower, 0)} bpm`;
  return `${fmtNum(lower, 0)}–${fmtNum(upper, 0)} bpm`;
}

export const FEEL_LABELS: Record<number, string> = { 1: "veľmi zle", 2: "zle", 3: "normálne", 4: "dobre", 5: "výborne" };
export const SORENESS_LABELS: Record<number, string> = { 0: "žiadna", 1: "mierna", 2: "stredná", 3: "silná" };

export type ListSearch = { from?: string; to?: string; sport?: string; page?: number };
