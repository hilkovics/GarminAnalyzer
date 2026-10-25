// Readiness gauge and the "Dnešný tréning" card (the compact version of the Plán page's today card).
import { Link } from "@tanstack/react-router";
import { ArrowRight, Bike, CloudCheck, Footprints } from "lucide-react";

import type { ApiError, Schemas } from "@/api/client";
import { ReadinessGauge, WorkoutProfile } from "@/components/charts";
import { Badge, Card, ErrorBox, Loading, Meta } from "@/components/ui";
import { fmtDuration, fmtNum, sportLabel } from "@/lib/format";
import { readinessBadge, statusBadge, stepLines } from "@/lib/labels";

type Q<T> = { data?: T; error: ApiError | null; isPending: boolean };

export function ReadinessCard({ query }: { query: Q<Schemas["ReadinessDTO"]> }) {
  const r = query.data;
  return (
    <Card title="Pripravenosť" right={<span className="label">0–100</span>} className="flex flex-col">
      {query.isPending ? (
        <Loading />
      ) : query.error || !r ? (
        <ErrorBox error={query.error}>Pripravenosť dnes nie je k dispozícii.</ErrorBox>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
          <ReadinessGauge score={r.available ? r.score : null} band={r.band} />
          {r.available && <Badge tone={readinessBadge(r.band).tone}>{readinessBadge(r.band).text}</Badge>}
          <p className={r.available ? "text-sm font-semibold" : "text-sm text-muted"}>{r.message}</p>
        </div>
      )}
    </Card>
  );
}

export const SportIcon = ({ sport, size = 18 }: { sport: string; size?: number }) =>
  sport === "bike" ? <Bike size={size} className="text-bike" /> : <Footprints size={size} className={sport === "run" ? "text-run" : "text-other"} />;

export function TodayCard({ query }: { query: Q<Schemas["DailyDecisionDTO"]> }) {
  const decision = query.data;
  const workout = decision?.workout;
  const badge = workout ? statusBadge(workout) : null;
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          Dnešný tréning {workout?.provisional && <Badge tone="yellow">predbežný</Badge>}
        </span>
      }
      right={
        badge &&
        (workout?.status === "pushed" ? (
          <span className="flex items-center gap-1 text-xs font-medium text-accent">
            <CloudCheck size={15} /> Odoslané do Garminu
          </span>
        ) : (
          <Badge tone={badge.tone}>{badge.text}</Badge>
        ))
      }
      className="flex flex-col"
    >
      {query.isPending ? (
        <Loading />
      ) : query.error || !workout ? (
        <ErrorBox error={query.error}>Dnešný tréning nie je k dispozícii.</ErrorBox>
      ) : (
        <div className="flex flex-1 flex-col gap-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <h3 className="text-2xl font-bold leading-tight sm:text-3xl">{workout.name}</h3>
            {workout.sport !== "rest" && (
              <div className="flex gap-5">
                <Meta label="Šport">
                  <span className="flex items-center gap-1.5 font-sans text-base">
                    <SportIcon sport={workout.sport} /> {sportLabel(workout.sport)}
                  </span>
                </Meta>
                <Meta label="Trvanie">{fmtDuration(workout.duration_s)}</Meta>
                <Meta label="Odhad záťaže">
                  {fmtNum(workout.estimated_load)} <span className="text-xs font-normal text-muted">TSS-ekv.</span>
                </Meta>
              </div>
            )}
          </div>
          {workout.sport === "rest" ? (
            <p className="text-sm text-muted">Dnes voľno – oddych je súčasť tréningu.</p>
          ) : (
            <>
              <WorkoutProfile steps={workout.steps} height={72} />
              <ul className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted">
                {stepLines(workout.steps).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </>
          )}
          <div className="mt-auto flex flex-wrap items-end justify-between gap-3">
            {decision?.reason ? <p className="max-w-xl text-sm italic text-muted">{decision.reason}</p> : <span />}
            <Link to="/plan" className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-sm font-semibold text-accent-text hover:brightness-110">
              Otvoriť plán <ArrowRight size={16} />
            </Link>
          </div>
        </div>
      )}
    </Card>
  );
}
