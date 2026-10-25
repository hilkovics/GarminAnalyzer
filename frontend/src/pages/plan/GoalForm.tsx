// "Cieľ": race date, distance preset or custom km, optional target time, sport; save (PUT) and clear (DELETE).
import { useState } from "react";

import { useApiMutation, type ApiError } from "@/api/client";
import { Button, Card, Segmented } from "@/components/ui";
import { fmtTimeHms } from "@/lib/format";

import { addDays, FlashNotice, inputClass, useClearGoal, useFlash, type Goal } from "./shared";
import { parseTimeHms } from "./time";

const DISTANCES = [
  { value: "5 km", label: "5 km", m: 5000 },
  { value: "10 km", label: "10 km", m: 10000 },
  { value: "Polmaratón", label: "Polmaratón", m: 21097.5 },
  { value: "Maratón", label: "Maratón", m: 42195 },
  { value: "Vlastná", label: "Vlastná", m: null },
];
const SPORTS = [
  { value: "run", label: "Beh" },
  { value: "bike", label: "Bicykel" },
];

type Body = { race_date: string; distance_m: number | null; target_time_s: number | null; sport: string };
type Report = { ok: (text: string) => void; fail: (error: Error | ApiError) => void; clear: () => void };

function Fields({ goal, today, report }: { goal: Goal | null; today: string; report: Report }) {
  const save = useApiMutation<Body, Goal>("PUT", () => "/plan/goal");
  const del = useClearGoal();

  const preset0 = DISTANCES.find((d) => goal && d.m === goal.distance_m)?.value ?? (goal ? "Vlastná" : "10 km");
  const [date, setDate] = useState(goal && goal.race_date >= today ? goal.race_date : addDays(today, 84));
  const [preset, setPreset] = useState(preset0);
  const [km, setKm] = useState(goal?.distance_m && preset0 === "Vlastná" ? String(goal.distance_m / 1000).replace(".", ",") : "");
  const [sport, setSport] = useState(goal?.sport ?? "run");
  const [time, setTime] = useState(goal?.target_time_s ? fmtTimeHms(goal.target_time_s) : "");

  const submit = () => {
    report.clear();
    try {
      if (!date) throw new Error("Zadaj dátum pretekov.");
      const fixed = DISTANCES.find((d) => d.value === preset)?.m ?? null;
      const custom = Number(km.replace(",", "."));
      if (fixed === null && km.trim() && !(custom > 0)) throw new Error("Vlastná vzdialenosť musí byť kladné číslo v km.");
      // mutateAsync: the form remounts when the saved goal arrives, which would drop per-call callbacks
      save
        .mutateAsync({ race_date: date, distance_m: fixed ?? (km.trim() ? custom * 1000 : null), target_time_s: parseTimeHms(time), sport })
        .then(() => report.ok("Cieľ uložený."), report.fail);
    } catch (error) {
      report.fail(error as Error);
    }
  };

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Dátum pretekov
          <input type="date" className={inputClass} value={date} min={today} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Šport
          <select className={inputClass} value={sport} onChange={(e) => setSport(e.target.value)}>
            {SPORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="flex flex-col gap-1 text-xs text-muted">
        Vzdialenosť
        <div className="overflow-x-auto">
          <Segmented label="Vzdialenosť" value={preset} onChange={setPreset} options={DISTANCES.map(({ value, label }) => ({ value, label }))} />
        </div>
      </div>
      {preset === "Vlastná" && (
        <label className="flex flex-col gap-1 text-xs text-muted">
          Vlastná vzdialenosť (km)
          <input inputMode="decimal" className={inputClass} value={km} onChange={(e) => setKm(e.target.value)} placeholder="napr. 15" />
        </label>
      )}
      <label className="flex flex-col gap-1 text-xs text-muted">
        Cieľový čas (h:mm:ss, nepovinné)
        <input className={inputClass} value={time} onChange={(e) => setTime(e.target.value)} placeholder="1:45:00" />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={save.isPending}>
          Uložiť cieľ
        </Button>
        <Button
          variant="secondary"
          disabled={!goal || del.isPending}
          onClick={() => {
            report.clear();
            del.mutateAsync().then(() => report.ok("Cieľ zmazaný."), report.fail);
          }}
        >
          Zmazať cieľ
        </Button>
      </div>
    </form>
  );
}

export function GoalForm({ goal, today }: { goal: Goal | null; today: string }) {
  const { flash, ...report } = useFlash();
  // keyed on the stored goal, so the fields reset to what the server saved (the message lives out here)
  const key = goal ? `${goal.id}-${goal.race_date}-${goal.distance_m}-${goal.target_time_s}-${goal.sport}` : "none";
  return (
    <Card title="Cieľ" className="flex flex-col gap-3">
      <Fields key={key} goal={goal} today={today} report={report} />
      <p className="mt-3 text-xs text-muted">Po zmene cieľa použi „Prepočítať“ pri dnešnom tréningu, aby sa zohľadnil nový plán.</p>
      <FlashNotice flash={flash} />
    </Card>
  );
}
