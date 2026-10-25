import { describe, expect, it } from "vitest";

import { dateTicks, dateX, niceTicks, paceAxis, paceS, paceTicks } from "./axes";

describe("pace axis helpers (display only)", () => {
  it("converts m/s to s/km and drops what cannot be drawn", () => {
    expect(paceS(1000 / 300)).toBeCloseTo(300);
    expect(paceS(0)).toBeNull();
    expect(paceS(null)).toBeNull();
    expect(paceS(1)).toBeNull(); // 16:40/km, slower than the 15:00 cap
  });

  it("picks the tick step from the range", () => {
    expect(paceTicks([301, 322])).toEqual([300, 315, 330]);
    expect(paceTicks([290, 400])).toEqual([270, 300, 330, 360, 390, 420]);
    expect(paceTicks([200, 600])).toEqual([180, 240, 300, 360, 420, 480, 540, 600]);
    expect(paceTicks([null])).toEqual([]);
  });

  it("builds a reversed axis labelled m:ss with the outer ticks as domain", () => {
    const axis = paceAxis([301, 322]);
    expect(axis.reversed).toBe(true);
    expect(axis.domain).toEqual([300, 330]);
    expect(axis.ticks.map(axis.tickFormatter)).toEqual(["5:00", "5:15", "5:30"]);
  });

  it("spreads date ticks evenly between the first and last point", () => {
    const a = dateX("2026-01-01");
    const b = dateX("2026-01-05");
    const ticks = dateTicks(a, b, 5);
    expect(ticks).toHaveLength(5);
    expect(ticks[0]).toBe(a);
    expect(ticks[4]).toBe(b);
    expect(dateTicks(a, a)).toEqual([a]);
  });

  it("keeps the number of value ticks small", () => {
    expect(niceTicks(-17, 14, 5)).toEqual([-20, -10, 0, 10, 20]);
    expect(niceTicks(0, 11, 5)).toEqual([0, 5, 10, 15]);
  });
});
