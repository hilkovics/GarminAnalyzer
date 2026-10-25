import { describe, expect, it } from "vitest";

import { fmtDate, fmtDuration, fmtDurationHms, fmtKm, fmtLoad, fmtNum, fmtPace, fmtSigned, fmtSpeed, isoWeekLabel, parsePace } from "./format";

describe("Slovak number formatting (as ui-streamlit/components/format.py)", () => {
  it("uses a decimal comma, a real minus and thin grouping", () => {
    expect(fmtNum(1234.56, 1)).toBe("1 234,6");
    expect(fmtNum(-6.31, 1)).toBe("−6,3");
    expect(fmtNum(-0.04, 1)).toBe("0,0");
    expect(fmtNum(null)).toBe("–");
    expect(fmtSigned(2.04)).toBe("+2,0");
    expect(fmtSigned(-6.3)).toBe("−6,3");
  });

  it("formats pace, speed, durations and distances", () => {
    expect(fmtPace(1000 / 333)).toBe("5:33/km");
    expect(fmtPace(0)).toBe("–");
    expect(fmtSpeed(8.33, "bike")).toBe("30,0 km/h");
    expect(fmtDuration(4500)).toBe("1:15");
    expect(fmtDurationHms(3725)).toBe("1:02:05");
    expect(fmtDurationHms(300)).toBe("5:00");
    expect(fmtKm(12345, 2)).toBe("12,35 km");
  });

  it("dates and ISO weeks", () => {
    expect(fmtDate("2026-10-23")).toBe("23. 10. 2026");
    expect(isoWeekLabel("2026-10-23")).toBe("T43/2026");
    expect(isoWeekLabel("2027-01-01")).toBe("T53/2026");
  });

  it("load: unknown is not zero", () => {
    expect(fmtLoad(87.2, "hrtss")).toBe("87 (hrTSS)");
    expect(fmtLoad(null)).toBe("⚠ neznáma");
    expect(fmtLoad(50, null, true)).toBe("⚠ 50");
  });

  it("parses a typed pace", () => {
    expect(parsePace("4:10")).toBeCloseTo(4, 5);
    expect(parsePace("5:33/km")).toBeCloseTo(1000 / 333, 5);
    expect(() => parsePace("4:70")).toThrow("Sekundy");
    expect(() => parsePace("abc")).toThrow("m:ss");
  });
});
