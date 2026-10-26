// Small helpers shared by the Plán blocks: types, form control classes, the flash message, date stepping.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type ApiError, type Schemas } from "@/api/client";
import { Notice } from "@/components/ui";
import { isoDate, parseDate } from "@/lib/format";

export type Planned = Schemas["PlannedWorkoutDTO"];
export type Decision = Schemas["DailyDecisionDTO"];
export type WeekPlan = Schemas["WeekPlanDTO"];
export type Season = Schemas["SeasonDTO"];
export type Goal = Schemas["GoalDTO"];
export type PushResult = Schemas["PushResultDTO"];

export const inputClass =
  "w-full rounded-lg border border-line-strong bg-card-2 px-3 py-2 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-accent disabled:opacity-50";

export type Flash = { tone: "green" | "red" | "gray"; text: string } | null;

/** One message line (success or the service's error text); `null` renders nothing. */
export function FlashNotice({ flash }: { flash: Flash }) {
  return flash ? (
    <div role={flash.tone === "red" ? "alert" : "status"}>
      <Notice tone={flash.tone}>{flash.text}</Notice>
    </div>
  ) : null;
}

export function useFlash() {
  const [flash, setFlash] = useState<Flash>(null);
  return {
    flash,
    clear: () => setFlash(null),
    ok: (text: string) => setFlash({ tone: "green", text }),
    info: (text: string) => setFlash({ tone: "gray", text }),
    fail: (error: Error | ApiError) => setFlash({ tone: "red", text: error.message }),
  };
}

/** DELETE /plan/goal – useApiMutation only knows POST and PUT, so this one calls `api` directly. */
export function useClearGoal() {
  const client = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: () => api<void>("/plan/goal", { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries(),
  });
}

const WEEKDAY_CODES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

/** "2026-10-27" → "tue" (the WEEKDAY_SHORT key). */
export function parseDateWeekday(iso: string): string {
  return WEEKDAY_CODES[parseDate(iso).getDay()];
}

export function addDays(iso: string, days: number): string {
  const date = parseDate(iso);
  date.setDate(date.getDate() + days);
  return isoDate(date);
}
