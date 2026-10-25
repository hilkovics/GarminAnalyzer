// "Preferované dni v týždni": weekday → role [+ sport] (METRICS §10.3), saved through PUT /settings/athlete.
import { useState } from "react";

import { useApiMutation, type ApiError, type Schemas } from "@/api/client";
import { Button, Card } from "@/components/ui";
import { WEEKDAY_SHORT } from "@/lib/format";
import { ROLE_LABELS } from "@/lib/labels";

import { FlashNotice, inputClass, useFlash } from "./shared";

type Report = { ok: (text: string) => void; fail: (error: Error | ApiError) => void; clear: () => void };
type Days = Record<string, Schemas["PreferredDayDTO"]>;

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const ROLES = ["rest", "easy", "long", "q1", "q2"];
// The coach's template (backend/training/coach/template.py DEFAULT_ROLES), shown while nothing is stored.
const DEFAULT_ROLES: Record<string, string> = { mon: "rest", tue: "q1", wed: "easy", thu: "q2", fri: "easy", sat: "long", sun: "easy" };
const COACH_SPORTS = [
  { value: "", label: "Podľa trénera" },
  { value: "run", label: "Beh" },
  { value: "bike", label: "Bicykel" },
];

function initial(current: Days | undefined): Record<string, { role: string; sport: string }> {
  return Object.fromEntries(
    WEEKDAYS.map((day) => [day, { role: current?.[day]?.role ?? DEFAULT_ROLES[day], sport: current?.[day]?.sport ?? "" }]),
  );
}

function Editor({ current, report }: { current: Days | undefined; report: Report }) {
  const [values, setValues] = useState(() => initial(current));
  const { ok, fail, clear } = report;
  const save = useApiMutation<{ preferred_days: Days; clear_rest_hr_override: boolean }, Schemas["AthleteDTO"]>("PUT", () => "/settings/athlete");
  const busy = save.isPending;

  const send = (days: Days, text: string) => {
    clear();
    // mutateAsync: the form remounts when the saved days arrive, which would drop per-call callbacks
    save.mutateAsync({ preferred_days: days, clear_rest_hr_override: false }).then(() => ok(text), fail);
  };
  const set = (day: string, patch: Partial<{ role: string; sport: string }>) => setValues((v) => ({ ...v, [day]: { ...v[day], ...patch } }));

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        send(Object.fromEntries(WEEKDAYS.map((d) => [d, { role: values[d].role, sport: values[d].role === "rest" || !values[d].sport ? null : values[d].sport }])), "Preferované dni uložené.");
      }}
    >
      <p className="text-xs text-muted">Rola dňa určuje typ tréningu; šport „Podľa trénera“ zvolí pravidlá (kvalita a dlhý = šport cieľa).</p>
      <div className="grid grid-cols-[2rem_minmax(0,1fr)_minmax(0,1fr)] items-center gap-x-2 gap-y-2">
        <span />
        <span className="label">Rola</span>
        <span className="label">Šport</span>
        {WEEKDAYS.map((day) => (
          <div key={day} className="contents">
            <span className="text-sm font-bold">{WEEKDAY_SHORT[day]}</span>
            <select aria-label={`Rola – ${WEEKDAY_SHORT[day]}`} className={inputClass} value={values[day].role} onChange={(e) => set(day, { role: e.target.value })}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </select>
            <select
              aria-label={`Šport – ${WEEKDAY_SHORT[day]}`}
              className={inputClass}
              value={values[day].role === "rest" ? "" : values[day].sport}
              disabled={values[day].role === "rest"}
              onChange={(e) => set(day, { sport: e.target.value })}
            >
              {COACH_SPORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={busy}>
          Uložiť dni
        </Button>
        <Button variant="secondary" disabled={busy} onClick={() => send({}, "Preferované dni vrátené na predvolené.")}>
          Predvolené dni
        </Button>
      </div>
    </form>
  );
}

export function PreferredDays({ athlete }: { athlete: Schemas["AthleteDTO"] | null | undefined }) {
  // re-initialise the form from what the server stored (after save / reset)
  const { flash, ...report } = useFlash();
  return (
    <Card title="Preferované dni v týždni" className="flex flex-col gap-3">
      <Editor key={JSON.stringify(athlete?.preferred_days ?? {})} current={athlete?.preferred_days} report={report} />
      <FlashNotice flash={flash} />
    </Card>
  );
}
