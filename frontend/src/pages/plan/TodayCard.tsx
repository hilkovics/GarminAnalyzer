// "Dnešný tréning": workout, profile and steps, the reason with its inputs, load tiles, Garmin state and the actions.
import { CloudCheck } from "lucide-react";

import { WorkoutProfile } from "@/components/charts";
import { Badge, Card, Meta, Notice, Stat } from "@/components/ui";
import { fmtDuration, fmtNum, fmtSigned, sportLabel } from "@/lib/format";
import { FITNESS_SLOT_LABELS, readinessBadge, ROLE_LABELS, statusBadge, stepLines } from "@/lib/labels";
import { SportIcon } from "@/pages/dashboard/TodayCards";

import { TodayActions } from "./TodayActions";
import type { Decision } from "./shared";

function Inputs({ decision }: { decision: Decision }) {
  if (decision.readiness === null || decision.readiness === undefined) {
    return <p className="text-xs text-muted">Pripravenosť: bez wellness dát.</p>;
  }
  const band = readinessBadge(decision.readiness_band);
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
      Pripravenosť: <strong className="num text-sm text-text">{Math.floor(decision.readiness)}</strong>
      <Badge tone={band.tone}>{band.text}</Badge>
      <span>
        · ACWR {fmtNum(decision.acwr, 2)} · TSB {fmtSigned(decision.tsb)}
      </span>
    </p>
  );
}

export function TodayCard({ decision }: { decision: Decision }) {
  const workout = decision.workout;
  const badge = statusBadge(workout);
  const rest = workout.sport === "rest";
  const pushed = workout.garmin_workout_id !== null && workout.garmin_workout_id !== undefined;
  return (
    <Card padded={false}>
      <div className="grid lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="flex min-w-0 flex-col gap-4 p-4 sm:p-5">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="label">Dnešný tréning</h2>
            {workout.provisional && <Badge tone="yellow">predbežný</Badge>}
            {workout.status === "pushed" ? (
              <span className="flex items-center gap-1 text-xs font-medium text-accent">
                <CloudCheck size={15} /> Odoslané do Garminu
              </span>
            ) : (
              <Badge tone={badge.tone}>{badge.text}</Badge>
            )}
            {workout.missed && workout.status === "pushed" && <Badge tone="red">zmeškané</Badge>}
          </div>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <h3 className="text-2xl font-bold leading-tight sm:text-3xl">{workout.name}</h3>
            {!rest && (
              <div className="flex gap-5">
                <Meta label="Šport">
                  <span className="flex items-center gap-1.5 font-sans text-base">
                    <SportIcon sport={workout.sport} /> {sportLabel(workout.sport)}
                  </span>
                </Meta>
                <Meta label="Trvanie">{fmtDuration(workout.duration_s)}</Meta>
              </div>
            )}
          </div>
          {rest ? (
            <p className="text-sm text-muted">Dnes voľno – oddych je súčasť tréningu.</p>
          ) : (
            <>
              <WorkoutProfile steps={workout.steps} height={96} />
              <ul className="flex flex-col gap-1 border-t border-line pt-3 text-sm sm:flex-row sm:flex-wrap sm:gap-x-6">
                {stepLines(workout.steps).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </>
          )}
          {decision.waiting_sleep && (
            <Notice tone="yellow">
              Čaká sa na dnešný spánok z hodiniek. Po synchronizácii sa tréning rozhodne znova, najneskôr o 12:00 – do Garminu
              sa zatiaľ neposiela.
            </Notice>
          )}
          {decision.reason && <p className="border-t border-line pt-3 text-sm italic text-muted">{decision.reason}</p>}
          <Inputs decision={decision} />
        </div>
        <aside className="flex flex-col gap-4 border-t border-line p-4 sm:p-5 lg:border-l lg:border-t-0">
          {!rest && (
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-line bg-card-2 p-3">
                <Stat label="Odhad záťaže" value={fmtNum(workout.estimated_load)} unit="TSS-ekv." />
              </div>
              <div className="rounded-lg border border-line bg-card-2 p-3">
                <Stat label="Skutočná záťaž" value={workout.actual_load ? fmtNum(workout.actual_load) : "–"} unit="TSS-ekv." />
              </div>
            </div>
          )}
          <TodayActions workout={workout} />
          <dl className="mt-auto flex flex-col gap-1 text-xs text-muted">
            <div className="flex justify-between gap-2">
              <dt>Garmin</dt>
              <dd className="num text-text">{pushed ? `v kalendári (#${workout.garmin_workout_id})` : "nie je odoslané"}</dd>
            </div>
            {workout.slot && (
              <div className="flex justify-between gap-2">
                <dt>{decision.mode === "fitness" ? "Položka menu" : "Rola dňa"}</dt>
                <dd className="text-text">
                  {(decision.mode === "fitness" ? FITNESS_SLOT_LABELS[workout.slot] : ROLE_LABELS[workout.slot]) ?? workout.slot}
                </dd>
              </div>
            )}
          </dl>
        </aside>
      </div>
    </Card>
  );
}
