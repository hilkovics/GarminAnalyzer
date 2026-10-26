// Plán (coach): today's workout, this week planned vs done, the season, the goal and the preferred days.
import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { useApi, useApiMutation, type Schemas } from "@/api/client";
import { Button, Loading, PageHeader, QueryState, Segmented } from "@/components/ui";
import { fmtLongDate, isoWeekLabel } from "@/lib/format";

import { GoalForm } from "./GoalForm";
import { PreferredDays } from "./PreferredDays";
import { SeasonBlock } from "./SeasonBlock";
import { TodayCard } from "./TodayCard";
import { WeekBlock } from "./WeekBlock";
import { FlashNotice, useFlash, type Decision, type Goal, type Season, type WeekPlan } from "./shared";

const SPORTS = [
  { value: "", label: "Podľa pravidiel" },
  { value: "run", label: "Beh" },
  { value: "bike", label: "Bicykel" },
];

/** "Prepočítať pre šport": decide today again, optionally for run or bike (a done workout stays). */
function Regenerate({ decision }: { decision: Decision | undefined }) {
  const [sport, setSport] = useState("");
  const { flash, ok, fail } = useFlash();
  const regenerate = useApiMutation<{ _sport: string }, Decision>("POST", (b) => `/plan/today/regenerate${b._sport ? `?sport=${b._sport}` : ""}`);
  const closed = decision?.workout.status === "done" || decision?.workout.status === "skipped";
  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <span className="text-xs text-muted">Prepočítať pre šport</span>
        <Segmented label="Prepočítať pre šport" value={sport} onChange={setSport} options={SPORTS} />
        <Button variant="secondary" disabled={!decision || closed || regenerate.isPending} onClick={() => regenerate.mutate({ _sport: sport }, { onSuccess: () => ok("Plán prepočítaný."), onError: fail })}>
          <RefreshCw size={15} className={regenerate.isPending ? "animate-spin" : undefined} /> Prepočítať
        </Button>
      </div>
      <FlashNotice flash={flash} />
    </div>
  );
}

export default function PlanPage() {
  const [weekDate, setWeekDate] = useState<string | undefined>(undefined);
  const today = useApi<Decision>("/plan/today");
  const week = useApi<WeekPlan>("/plan/week", { date: weekDate }, { keepPrevious: true });
  const season = useApi<Season>("/plan/season");
  const goal = useApi<Goal | null>("/plan/goal");
  const settings = useApi<Schemas["SettingsDTO"]>("/settings");
  const todayIso = today.data?.date ?? season.data?.today;

  return (
    <>
      <PageHeader
        title="Plán"
        subtitle={todayIso ? `${fmtLongDate(todayIso)} · ${isoWeekLabel(todayIso)}` : undefined}
        right={<Regenerate decision={today.data} />}
      />
      <div className="flex flex-col gap-4">
        <QueryState query={today}>{(decision) => <TodayCard decision={decision} />}</QueryState>
        <QueryState query={week}>
          {(w) => <WeekBlock week={w} today={todayIso ?? ""} onNavigate={setWeekDate} pending={week.isPlaceholderData} />}
        </QueryState>
        {today.data?.mode === "fitness" ? (
          <p className="text-sm text-muted">
            Bez pretekového cieľa plánuje tréner <strong className="text-text">Kondícia</strong>: každý týždeň kvalita, dlhší a ľahký beh,
            čas rastie v 12-týždňových blokoch podľa spánku a pripravenosti. Zadaním cieľa nižšie sa prepne na prípravu na preteky.
          </p>
        ) : (
          <QueryState query={season}>{(s) => <SeasonBlock goal={s.goal} season={s} />}</QueryState>
        )}
        <div className="grid gap-4 lg:grid-cols-2">
          <QueryState query={goal}>{(g) => (todayIso ? <GoalForm goal={g} today={todayIso} /> : <Loading />)}</QueryState>
          <QueryState query={settings}>{(s) => <PreferredDays athlete={s.athlete} />}</QueryState>
        </div>
      </div>
    </>
  );
}
