// Formatting – the only place where internal units become display strings (as ui-streamlit/components/format.py).
// Internal units: seconds, metres, m/s. Slovak conventions: decimal comma, real minus sign, "–" for missing.

export const DASH = "–";
export const MINUS = "−";

export const SPORT_LABELS: Record<string, string> = { run: "Beh", bike: "Bicykel", other: "Iné", all: "Spolu", rest: "Voľno" };
export const LOAD_METHOD_LABELS: Record<string, string> = { hrtss: "hrTSS", rtss: "rTSS", trimp: "TRIMP" };

type Num = number | null | undefined;

export function valid(x: Num): x is number {
  return x !== null && x !== undefined && Number.isFinite(x);
}

export function sportLabel(sport: string | null | undefined): string {
  return sport ? (SPORT_LABELS[sport] ?? sport) : DASH;
}

/** "1234.5" → "1 234,5"; negative with "−"; −0.04 at one decimal → "0,0". */
export function fmtNum(x: Num, digits = 0, unit = ""): string {
  if (!valid(x)) return DASH;
  let value = Number(x.toFixed(digits));
  if (value === 0) value = 0; // no "−0"
  const [int, frac] = Math.abs(value).toFixed(digits).split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const text = (value < 0 ? MINUS : "") + grouped + (frac ? `,${frac}` : "");
  return unit ? `${text} ${unit}` : text;
}

export function fmtSigned(x: Num, digits = 1): string {
  if (!valid(x)) return DASH;
  const text = fmtNum(x, digits);
  return Number(x.toFixed(digits)) > 0 ? `+${text}` : text;
}

export function fmtPct(share: Num, digits = 0): string {
  return valid(share) ? `${fmtNum(share * 100, digits)} %` : DASH;
}

export function fmtPctSigned(share: Num, digits = 1): string {
  return valid(share) ? `${fmtSigned(share * 100, digits)} %` : DASH;
}

/** Seconds per km → "m:ss". */
export function fmtPaceS(secondsPerKm: number): string {
  const total = Math.round(secondsPerKm);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** m/s → "m:ss/km". */
export function fmtPace(speed: Num): string {
  return valid(speed) && speed > 0 ? `${fmtPaceS(1000 / speed)}/km` : DASH;
}

export function fmtSpeedKmh(speed: Num): string {
  return valid(speed) && speed >= 0 ? fmtNum(speed * 3.6, 1, "km/h") : DASH;
}

/** Pace for running (and anything not a bike), km/h for cycling. */
export function fmtSpeed(speed: Num, sport: string | null | undefined): string {
  return sport === "bike" ? fmtSpeedKmh(speed) : fmtPace(speed);
}

/** Seconds → "h:mm" (nearest minute). */
export function fmtDuration(seconds: Num): string {
  if (!valid(seconds) || seconds < 0) return DASH;
  const minutes = Math.round(seconds / 60);
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

/** Seconds → "m:ss" below an hour, "h:mm:ss" from an hour. */
export function fmtDurationHms(seconds: Num): string {
  if (!valid(seconds) || seconds < 0) return DASH;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

/** Race time → "h:mm:ss" (always with hours). */
export function fmtTimeHms(seconds: Num): string {
  if (!valid(seconds) || seconds < 0) return DASH;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  return `${h}:${m}:${String(total % 60).padStart(2, "0")}`;
}

/** Window length → "5 min" or "45 s". */
export function fmtWindow(seconds: Num): string {
  if (!valid(seconds) || seconds <= 0) return DASH;
  return seconds % 60 === 0 ? `${seconds / 60} min` : `${Math.round(seconds)} s`;
}

export function fmtKm(metres: Num, digits = 1): string {
  return valid(metres) && metres >= 0 ? fmtNum(metres / 1000, digits, "km") : DASH;
}

export function fmtHours(seconds: Num, digits = 1): string {
  return valid(seconds) && seconds >= 0 ? fmtNum(seconds / 3600, digits, "h") : DASH;
}

/** "2026-10-23" (an API date) → a local Date at midnight, without a UTC shift. */
export function parseDate(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function isoDate(date: Date): string {
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${m}-${d}`;
}

/** "2026-10-23" → "23. 10. 2026". */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const date = parseDate(iso);
  return `${String(date.getDate()).padStart(2, "0")}. ${String(date.getMonth() + 1).padStart(2, "0")}. ${date.getFullYear()}`;
}

/** "2026-10-23" → "23. 10." (chart ticks). */
export function fmtDayMonth(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const date = parseDate(iso);
  return `${date.getDate()}. ${date.getMonth() + 1}.`;
}

const WEEKDAYS_LONG = ["Nedeľa", "Pondelok", "Utorok", "Streda", "Štvrtok", "Piatok", "Sobota"];
export const WEEKDAY_SHORT: Record<string, string> = { mon: "Po", tue: "Ut", wed: "St", thu: "Št", fri: "Pi", sat: "So", sun: "Ne" };

/** "2026-10-23" → "Piatok 23. 10. 2026". */
export function fmtLongDate(iso: string): string {
  const date = parseDate(iso);
  return `${WEEKDAYS_LONG[date.getDay()]} ${date.getDate()}. ${date.getMonth() + 1}. ${date.getFullYear()}`;
}

/** A UTC timestamp → local "23. 10. 2026 6:01". */
export function fmtDateTime(iso: string | null | undefined, sep = " "): string {
  if (!iso) return DASH;
  const t = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return `${t.getDate()}. ${t.getMonth() + 1}. ${t.getFullYear()}${sep}${t.getHours()}:${String(t.getMinutes()).padStart(2, "0")}`;
}

/** ISO week "T43/2026". */
export function isoWeekLabel(iso: string): string {
  const date = parseDate(iso);
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const day = (target.getDay() + 6) % 7;
  target.setDate(target.getDate() - day + 3);
  const firstThursday = new Date(target.getFullYear(), 0, 4);
  const week = 1 + Math.round(((target.getTime() - firstThursday.getTime()) / 86400000 - 3 + ((firstThursday.getDay() + 6) % 7)) / 7);
  return `T${week}/${target.getFullYear()}`;
}

/** Load "87 (hrTSS)"; unknown load is "neznáma" (METRICS §2.1), flagged with ⚠ like low confidence. */
export function fmtLoad(load: Num, method?: string | null, lowConfidence = false): string {
  const unknown = !valid(load);
  const text = unknown ? "neznáma" : fmtNum(load, 0) + (method ? ` (${LOAD_METHOD_LABELS[method] ?? method})` : "");
  return unknown || lowConfidence ? `⚠ ${text}` : text;
}

/** "m:ss" or "m:ss/km" → m/s; throws an Error with a Slovak message. */
export function parsePace(text: string): number {
  const raw = text.trim().toLowerCase().replace(/\/km$/, "").trim();
  const match = /^(\d+):(\d+)$/.exec(raw);
  if (!match) throw new Error("Tempo zadaj ako m:ss, napr. 4:10.");
  const minutes = Number(match[1]);
  const secs = Number(match[2]);
  if (secs >= 60) throw new Error("Sekundy musia byť v rozsahu 0–59.");
  const total = minutes * 60 + secs;
  if (total < 120 || total > 900) throw new Error("Tempo musí byť medzi 2:00 a 15:00 min/km.");
  return 1000 / total;
}
