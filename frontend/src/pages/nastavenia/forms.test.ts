import { describe, expect, it } from "vitest";

import { athleteValues, buildAthleteIn, buildThresholdIn, fmtZoneRange, parseField, proposalChange, proposalGarmin, proposalValue } from "./forms";

const NOBODY = athleteValues(null);

describe("athlete form → AthleteIn", () => {
  it("sends empty fields as null (= unchanged) and the split as a share", () => {
    expect(buildAthleteIn({ ...NOBODY, maxHr: "188", split: "55", weight: "72,5" }, 2026)).toEqual({
      sex: null,
      birth_year: null,
      max_hr: 188,
      rest_hr_override: null,
      clear_rest_hr_override: false,
      weight_kg: 72.5,
      run_bike_split: 0.55,
    });
  });

  it("the clear checkbox wins over a typed rest HR", () => {
    const body = buildAthleteIn({ ...NOBODY, restHr: "47", clearRest: true }, 2026);
    expect(body.rest_hr_override).toBeNull();
    expect(body.clear_rest_hr_override).toBe(true);
  });

  it("prefills from the DTO without float noise and with a decimal comma", () => {
    const v = athleteValues({
      sex: "male",
      birth_year: 1991,
      max_hr: 188,
      rest_hr_override: null,
      rest_hr_current: 47,
      weight_kg: 72.5,
      run_bike_split: 0.55,
    });
    expect(v).toMatchObject({ sex: "male", birthYear: "1991", weight: "72,5", maxHr: "188", restHr: "", split: "55" });
  });

  it("rejects bad input with Slovak messages", () => {
    expect(() => parseField("abc", "Hmotnosť")).toThrow("Hmotnosť: zadaj číslo.");
    expect(() => buildAthleteIn({ ...NOBODY, split: "120" }, 2026)).toThrow("Podiel behu: najviac 100.");
    expect(() => buildAthleteIn({ ...NOBODY, birthYear: "2027" }, 2026)).toThrow("Rok narodenia: najviac 2 026.");
    expect(() => buildAthleteIn({ ...NOBODY, birthYear: "1991,5" }, 2026)).toThrow("celé číslo");
  });
});

describe("threshold form → ThresholdIn", () => {
  const base = { sport: "run", lthr: "170", pace: "4:10", validFrom: "2026-10-25" };

  it("converts the typed m:ss pace to m/s", () => {
    const body = buildThresholdIn(base);
    expect(body.threshold_speed).toBeCloseTo(1000 / 250, 10);
    expect(body).toMatchObject({ sport: "run", lthr: 170, valid_from: "2026-10-25", source: "manual" });
  });

  it("a bike threshold and an empty run pace carry no speed", () => {
    expect(buildThresholdIn({ ...base, sport: "bike" }).threshold_speed).toBeNull();
    expect(buildThresholdIn({ ...base, pace: "  " }).threshold_speed).toBeNull();
  });

  it("uses the Slovak validation errors of parsePace", () => {
    expect(() => buildThresholdIn({ ...base, pace: "250" })).toThrow("Tempo zadaj ako m:ss, napr. 4:10.");
    expect(() => buildThresholdIn({ ...base, pace: "4:75" })).toThrow("Sekundy musia byť v rozsahu 0–59.");
    expect(() => buildThresholdIn({ ...base, pace: "1:00" })).toThrow("Tempo musí byť medzi 2:00 a 15:00 min/km.");
    expect(() => buildThresholdIn({ ...base, lthr: "" })).toThrow("Zadaj LTHR.");
  });
});

describe("zone bounds and proposals", () => {
  it("formats HR bounds, open ends included", () => {
    expect(fmtZoneRange(130, 150, "hr")).toBe("130–150 bpm");
    expect(fmtZoneRange(null, 130, "hr")).toBe("< 130 bpm");
    expect(fmtZoneRange(170, null, "hr")).toBe("> 170 bpm");
    expect(fmtZoneRange(null, null, "hr")).toBe("–");
  });

  it("formats pace bounds slow–fast", () => {
    expect(fmtZoneRange(1000 / 330, 1000 / 290, "pace")).toBe("5:30–4:50/km");
    expect(fmtZoneRange(null, 1000 / 330, "pace")).toBe("pomalšie ako 5:30/km");
    expect(fmtZoneRange(1000 / 250, null, "pace")).toBe("rýchlejšie ako 4:10/km");
  });

  it("formats proposal values, change and Garmin hints per field", () => {
    expect(proposalValue("lthr", 168.4)).toBe("168 bpm");
    expect(proposalValue("threshold_speed", 1000 / 250)).toBe("4:10/km");
    expect(proposalValue("lthr", null)).toBe("–");
    expect(proposalChange({ field: "lthr", change: -4, garmin_lthr: null, garmin_lt_speed: null, garmin_vo2max: null })).toBe("−4 bpm");
    expect(proposalChange({ field: "threshold_speed", change: 0.032, garmin_lthr: null, garmin_lt_speed: null, garmin_vo2max: null })).toBe("+3,2 %");
    expect(proposalGarmin({ field: "lthr", change: null, garmin_lthr: 171, garmin_lt_speed: 3.4, garmin_vo2max: 52 })).toBe("LT tep 171 bpm · VO2max 52");
    expect(proposalGarmin({ field: "lthr", change: null, garmin_lthr: null, garmin_lt_speed: null, garmin_vo2max: null })).toBe("–");
  });
});
