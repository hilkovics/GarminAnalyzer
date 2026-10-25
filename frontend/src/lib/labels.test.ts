import { describe, expect, it } from "vitest";

import type { Schemas } from "@/api/client";

import { expandSteps, repeatSpans, statusBadge, stepLines } from "./labels";

type Step = Schemas["WorkoutStepDTO"];
const step = (over: Partial<Step>): Step => ({ type: "work", duration_s: 600, target_kind: "hr_zone", zone: 3, low_mps: null, high_mps: null, repeat: null, group: null, ...over });

const SWEET_SPOT: Step[] = [
  step({ type: "warmup", duration_s: 900, zone: 2 }),
  step({ type: "work", duration_s: 1200, zone: 3, repeat: 2, group: 0 }),
  step({ type: "recovery", duration_s: 300, zone: 1, repeat: 2, group: 0 }),
  step({ type: "cooldown", duration_s: 600, zone: 1 }),
];

describe("workout steps", () => {
  it("reads like the Streamlit lines", () => {
    expect(stepLines(SWEET_SPOT)).toEqual(["Rozcvička 15 min Z2", "2× (20 min Z3 / 5 min Z1)", "Vychladenie 10 min Z1"]);
  });

  it("unrolls repeats in play order", () => {
    const played = expandSteps(SWEET_SPOT);
    expect(played.map((p) => p.step.type)).toEqual(["warmup", "work", "recovery", "work", "recovery", "cooldown"]);
    expect(played[played.length - 1].end).toBe(900 + 2 * 1500 + 600);
    expect(repeatSpans(SWEET_SPOT)).toEqual([{ count: 2, start: 900, end: 3900 }]);
  });

  it("status badges", () => {
    const planned = { status: "planned", missed: false, sport: "run" } as Schemas["PlannedWorkoutDTO"];
    expect(statusBadge(null, "rest").text).toBe("voľno");
    expect(statusBadge({ ...planned, status: "done" }).text).toBe("hotovo");
    expect(statusBadge({ ...planned, missed: true }).tone).toBe("red");
    expect(statusBadge({ ...planned, status: "pushed" }).text).toBe("odoslané do Garminu");
  });
});
