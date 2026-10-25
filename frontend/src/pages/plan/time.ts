// Parsing of the goal form's target time (as ui-streamlit/components/format.py parse_time_hms).

/** "h:mm:ss" or "m:ss" → seconds; blank → null; throws an Error with a Slovak message. */
export function parseTimeHms(text: string): number | null {
  const raw = text.trim();
  if (!raw) return null;
  const parts = raw.split(":").map((p) => p.trim());
  if ((parts.length !== 2 && parts.length !== 3) || !parts.every((p) => /^\d+$/.test(p))) {
    throw new Error("Cieľový čas zadaj ako h:mm:ss, napr. 0:40:00.");
  }
  const [secs, minutes, hours = 0] = parts.map(Number).reverse();
  if (minutes >= 60 || secs >= 60) throw new Error("Minúty a sekundy musia byť v rozsahu 0–59.");
  const total = hours * 3600 + minutes * 60 + secs;
  if (total <= 0) throw new Error("Cieľový čas musí byť kladný.");
  return total;
}
