// Nastavenia: parsing of typed form values into the API bodies (AthleteIn, ThresholdIn) and the text of zone
// bounds / proposals. Only unit conversion and formatting live here (m:ss → m/s, % → share); everything else is
// validated by the service and its message is shown.
import type { Schemas } from "@/api/client";
import { DASH, fmtNum, fmtPace, fmtPaceS, fmtPctSigned, fmtSigned, parsePace, valid } from "@/lib/format";

type Athlete = Schemas["AthleteDTO"];

export const SEX_LABELS: Record<string, string> = { male: "Muž", female: "Žena" };
export const SOURCE_LABELS: Record<string, string> = { manual: "ručne", proposal: "návrh" };
export const FIELD_LABELS: Record<string, string> = { threshold_speed: "Prahové tempo", lthr: "LTHR" };

export const sourceLabel = (source: string | null | undefined): string => (source ? (SOURCE_LABELS[source] ?? source) : DASH);

/** A number as typed in a Slovak input: decimal comma, no grouping ("72,5", "1991"). */
export function inputText(x: number | null | undefined): string {
  return valid(x) ? String(Math.round(x * 1e6) / 1e6).replace(".", ",") : "";
}

/** "" → null (leave unchanged); "72,5" / "72.5" → 72.5; anything else throws a Slovak message. */
export function parseField(text: string, label: string, opts: { min?: number; max?: number; integer?: boolean } = {}): number | null {
  const raw = text.trim().replace(/\s/g, "").replace(",", ".");
  if (!raw) return null;
  const value = Number(raw);
  if (!/^-?\d+(\.\d+)?$/.test(raw) || !Number.isFinite(value)) throw new Error(`${label}: zadaj číslo.`);
  if (opts.integer && !Number.isInteger(value)) throw new Error(`${label}: zadaj celé číslo.`);
  if (opts.min !== undefined && value < opts.min) throw new Error(`${label}: najmenej ${fmtNum(opts.min, 0)}.`);
  if (opts.max !== undefined && value > opts.max) throw new Error(`${label}: najviac ${fmtNum(opts.max, 0)}.`);
  return value;
}

export type AthleteValues = {
  sex: string;
  birthYear: string;
  weight: string;
  maxHr: string;
  restHr: string;
  split: string;
  clearRest: boolean;
};

export function athleteValues(a: Athlete | null): AthleteValues {
  const share = a?.run_bike_split;
  return {
    sex: a?.sex ?? "",
    birthYear: inputText(a?.birth_year),
    weight: inputText(a?.weight_kg),
    maxHr: inputText(a?.max_hr),
    restHr: inputText(a?.rest_hr_override),
    split: inputText(valid(share) ? Math.round(share * 1000) / 10 : null),
    clearRest: false,
  };
}

/** Typed values → AthleteIn (empty field = null = unchanged; the run:bike split is typed in %, sent as a share). */
export function buildAthleteIn(v: AthleteValues, thisYear: number): Schemas["AthleteIn"] {
  const split = parseField(v.split, "Podiel behu", { min: 0, max: 100 });
  return {
    sex: v.sex || null,
    birth_year: parseField(v.birthYear, "Rok narodenia", { min: 1900, max: thisYear, integer: true }),
    max_hr: parseField(v.maxHr, "Maximálny tep", { min: 1 }),
    rest_hr_override: v.clearRest ? null : parseField(v.restHr, "Pokojový tep", { min: 1 }),
    clear_rest_hr_override: v.clearRest,
    weight_kg: parseField(v.weight, "Hmotnosť", { min: 1 }),
    run_bike_split: split === null ? null : split / 100,
  };
}

export type ThresholdValues = { sport: string; lthr: string; pace: string; validFrom: string };

/** Typed values → ThresholdIn; the pace is typed as m:ss (run only) and converted to m/s. */
export function buildThresholdIn(v: ThresholdValues): Schemas["ThresholdIn"] {
  const lthr = parseField(v.lthr, "LTHR", { min: 1 });
  if (lthr === null) throw new Error("Zadaj LTHR.");
  if (!v.validFrom) throw new Error("Zadaj dátum, od ktorého prah platí.");
  const speed = v.sport === "run" && v.pace.trim() ? parsePace(v.pace) : null;
  return { sport: v.sport, valid_from: v.validFrom, lthr, threshold_speed: speed, source: "manual" };
}

/** "130–150 bpm", "< 130 bpm", "> 170 bpm"; pace bounds are m/s and read slow–fast: "5:30–4:50/km". */
export function fmtZoneRange(lower: number | null | undefined, upper: number | null | undefined, kind: "hr" | "pace"): string {
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

type Proposal = Pick<
  Schemas["ProposalDTO"],
  "field" | "change" | "garmin_lthr" | "garmin_lt_speed" | "garmin_vo2max"
>;

/** A proposal value: pace for threshold_speed, bpm for lthr. */
export function proposalValue(field: string, x: number | null | undefined): string {
  if (!valid(x)) return DASH;
  return field === "threshold_speed" ? fmtPace(x) : fmtNum(x, 0, "bpm");
}

/** Relative change in % for pace, bpm for LTHR. */
export function proposalChange(p: Proposal): string {
  if (!valid(p.change)) return DASH;
  return p.field === "threshold_speed" ? fmtPctSigned(p.change) : `${fmtSigned(p.change, 0)} bpm`;
}

/** Garmin's own estimates next to the proposal: "LT tep 171 bpm · VO2max 52". */
export function proposalGarmin(p: Proposal): string {
  const parts: string[] = [];
  if (p.field === "lthr" && valid(p.garmin_lthr)) parts.push(`LT tep ${fmtNum(p.garmin_lthr, 0)} bpm`);
  if (p.field === "threshold_speed" && valid(p.garmin_lt_speed)) parts.push(`LT tempo ${fmtPace(p.garmin_lt_speed)}`);
  if (valid(p.garmin_vo2max)) parts.push(`VO2max ${fmtNum(p.garmin_vo2max, 0)}`);
  return parts.join(" · ") || DASH;
}
