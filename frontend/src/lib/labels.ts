// Code → Slovak label / badge tone maps (as ui-streamlit/components/badges.py and plan.py). No decisions here.
import type { Schemas } from "@/api/client";
import type { Tone } from "@/components/ui";

import { fmtPace, fmtWindow } from "./format";

export type Badge = { text: string; tone: Tone };

const UNKNOWN: Badge = { text: "–", tone: "gray" };

export const ACWR_BADGES: Record<string, Badge> = {
  under: { text: "nízka záťaž", tone: "blue" },
  optimal: { text: "optimum", tone: "green" },
  caution: { text: "pozor", tone: "orange" },
  danger: { text: "riziko", tone: "red" },
};
export const READINESS_BADGES: Record<string, Badge> = {
  green: { text: "zelená", tone: "green" },
  yellow: { text: "žltá", tone: "yellow" },
  red: { text: "červená", tone: "red" },
};
export const SANITY_BADGES: Record<string, Badge> = {
  good: { text: "dobrá zhoda", tone: "green" },
  fair: { text: "prijateľná zhoda", tone: "orange" },
  warning: { text: "slabá zhoda, skontroluj LTHR", tone: "red" },
  insufficient: { text: "málo dát", tone: "gray" },
};

export const acwrBadge = (band?: string | null): Badge => ACWR_BADGES[band ?? ""] ?? UNKNOWN;
export const readinessBadge = (band?: string | null): Badge => READINESS_BADGES[band ?? ""] ?? UNKNOWN;
export const sanityBadge = (status?: string | null): Badge => SANITY_BADGES[status ?? ""] ?? UNKNOWN;

export const PHASE_LABELS: Record<string, string> = { base: "Základ", build: "Budovanie", peak: "Vrchol", taper: "Ladenie" };
export const PHASE_COLORS: Record<string, string> = { base: "var(--run)", build: "var(--bike)", peak: "var(--red)", taper: "var(--green)" };
export const ROLE_SHORT: Record<string, string> = { rest: "V", easy: "Ľ", long: "D", q1: "K1", q2: "K2" };
export const ROLE_LABELS: Record<string, string> = { rest: "Voľno", easy: "Ľahký", long: "Dlhý", q1: "Kvalita 1", q2: "Kvalita 2" };
// coach "Kondícia" menu items (METRICS §11.1)
export const FITNESS_SLOT_SHORT: Record<string, string> = { k: "K", d: "D", e: "Ľ" };
export const FITNESS_SLOT_LABELS: Record<string, string> = { k: "Kvalita", d: "Dlhší beh", e: "Ľahký beh" };
export const STEP_LABELS: Record<string, string> = {
  warmup: "Rozcvička",
  work: "Záťaž",
  recovery: "Oddych",
  cooldown: "Vychladenie",
  steady: "Rovnomerne",
};

export const SPORT_COLORS: Record<string, string> = { run: "var(--run)", bike: "var(--bike)", other: "var(--other)" };
export const ZONE_COLORS = ["var(--z1)", "var(--z1)", "var(--z2)", "var(--z3)", "var(--z4)", "var(--z5)"];

export function phaseText(phase: string, recovery = false): string {
  const label = PHASE_LABELS[phase] ?? phase;
  return recovery ? `${label} (regeneračný týždeň)` : label;
}

type Step = Schemas["WorkoutStepDTO"];
type Planned = Schemas["PlannedWorkoutDTO"];

function target(step: Step): string {
  if (step.target_kind === "open") return `úsilie Z${step.zone}`;
  if (step.target_kind === "pace_range") {
    const span = step.low_mps && step.high_mps ? ` ${fmtPace(step.low_mps).replace("/km", "")}–${fmtPace(step.high_mps)}` : "";
    return `Z${step.zone} tempo${span}`;
  }
  return `Z${step.zone}`;
}

const short = (step: Step) => `${fmtWindow(step.duration_s)} ${target(step)}`;

/** Readable lines: "Rozcvička 15 min Z2", "5× (6 min Z4 / 2 min Z1)". */
export function stepLines(steps: Step[]): string[] {
  const lines: string[] = [];
  const seen = new Set<number>();
  for (const step of steps) {
    if (step.group === null || step.group === undefined) {
      lines.push(`${STEP_LABELS[step.type] ?? step.type} ${short(step)}`);
    } else if (!seen.has(step.group)) {
      seen.add(step.group);
      const body = steps.filter((s) => s.group === step.group).map(short).join(" / ");
      lines.push(`${step.repeat}× (${body})`);
    }
  }
  return lines;
}

/** (step, start, end) in play order, repeat blocks unrolled. */
export function expandSteps(steps: Step[]): { step: Step; start: number; end: number }[] {
  const out: { step: Step; start: number; end: number }[] = [];
  let clock = 0;
  const done = new Set<number>();
  for (const step of steps) {
    if (step.group === null || step.group === undefined) {
      out.push({ step, start: clock, end: clock + step.duration_s });
      clock += step.duration_s;
    } else if (!done.has(step.group)) {
      done.add(step.group);
      const block = steps.filter((s) => s.group === step.group);
      for (let i = 0; i < (step.repeat ?? 1); i++) {
        for (const inner of block) {
          out.push({ step: inner, start: clock, end: clock + inner.duration_s });
          clock += inner.duration_s;
        }
      }
    }
  }
  return out;
}

/** Repeat blocks that run more than once: (count, start, end). */
export function repeatSpans(steps: Step[]): { count: number; start: number; end: number }[] {
  const spans: { count: number; start: number; end: number }[] = [];
  let clock = 0;
  const done = new Set<number>();
  for (const step of steps) {
    if (step.group === null || step.group === undefined) {
      clock += step.duration_s;
    } else if (!done.has(step.group)) {
      done.add(step.group);
      const block = steps.filter((s) => s.group === step.group);
      const length = block.reduce((sum, s) => sum + s.duration_s, 0) * (step.repeat ?? 1);
      if ((step.repeat ?? 1) > 1) spans.push({ count: step.repeat ?? 1, start: clock, end: clock + length });
      clock += length;
    }
  }
  return spans;
}

/** done / skipped / missed / planned / rest; no plan on a template rest day is "voľno". */
export function statusBadge(planned: Planned | null | undefined, role?: string | null): Badge {
  if (!planned) return role === "rest" ? { text: "voľno", tone: "gray" } : { text: "bez plánu", tone: "gray" };
  if (planned.status === "done") return { text: "hotovo", tone: "green" };
  if (planned.status === "skipped") return { text: "vynechané", tone: "gray" };
  if (planned.missed) return { text: "zmeškané", tone: "red" };
  if (planned.sport === "rest") return { text: "voľno", tone: "gray" };
  return planned.status === "pushed" ? { text: "odoslané do Garminu", tone: "blue" } : { text: "plánované", tone: "blue" };
}
