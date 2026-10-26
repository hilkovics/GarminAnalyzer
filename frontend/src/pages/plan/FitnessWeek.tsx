// Coach "Kondícia" week (METRICS §11): block week n/12, weekly running time, the K – D – Ľ menu.
import { Check } from "lucide-react";

import { Badge, cx } from "@/components/ui";
import { fmtDayMonth, fmtDuration, WEEKDAY_SHORT } from "@/lib/format";

import { parseDateWeekday, type WeekPlan } from "./shared";

type Fitness = NonNullable<WeekPlan["fitness"]>;

const BRAKES: Record<string, string> = {
  hold: "brzda: čas sa nezvyšuje (slabá pripravenosť, spánkový dlh alebo vysoké ACWR minulý týždeň)",
  cut: "brzda: čas znížený o 15 % (veľmi slabá pripravenosť minulý týždeň)",
};

function weekKind(f: Fitness): string {
  if (f.test) return f.recovery ? "testovací a odľahčený týždeň" : "testovací týždeň (kontrolný beh)";
  return f.recovery ? "odľahčený týždeň" : "rastový týždeň";
}

function minutesText(slot: Fitness["menu"][number]): string {
  return slot.slot === "d" && slot.minutes !== slot.weekday_minutes
    ? `${slot.minutes} min cez víkend · ${slot.weekday_minutes} min v týždni`
    : `${slot.weekday_minutes} min`;
}

export function FitnessWeek({ fitness }: { fitness: Fitness }) {
  const progress = fitness.target_s > 0 ? Math.min(1, fitness.run_s / fitness.target_s) : 0;
  return (
    <div className="flex flex-col gap-3">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
        <strong className="text-text">
          Týždeň {fitness.week_no}/{fitness.block_weeks}
        </strong>
        <span>bloku od {fmtDayMonth(fitness.block_start)}</span>· <span>{weekKind(fitness)}</span>· cieľ behu{" "}
        <span className="num text-text">{fmtDuration(fitness.target_s)}</span>· hotovo <span className="num text-text">{fmtDuration(fitness.run_s)}</span>
        {fitness.brake && <Badge tone="yellow">{fitness.brake === "cut" ? "znížené" : "bez rastu"}</Badge>}
      </p>
      {fitness.brake && <p className="text-xs text-muted">{BRAKES[fitness.brake]}</p>}
      <div className="flex items-center gap-3">
        <div
          className="h-2 flex-1 overflow-hidden rounded-full bg-line"
          role="progressbar"
          aria-label="Splnenie týždenného času behu"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress * 100)}
        >
          <div className="h-full rounded-full bg-accent" style={{ width: `${progress * 100}%` }} />
        </div>
        <span className="num text-sm font-semibold">{Math.round(progress * 100)} %</span>
      </div>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-3" aria-label="Menu týždňa">
        {fitness.menu.map((slot) => (
          <li
            key={slot.slot}
            className={cx("flex items-center gap-3 rounded-lg border p-3", slot.done_date ? "border-good/50 bg-good/10" : "border-line bg-card-2")}
          >
            <span className="num flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-line-strong text-sm font-bold">
              {slot.done_date ? <Check size={16} className="text-good" aria-hidden /> : slot.slot === "e" ? "Ľ" : slot.slot.toUpperCase()}
            </span>
            <div className="min-w-0 leading-tight">
              <div className="text-sm font-semibold">{slot.label}</div>
              <div className="num text-xs text-muted">
                {slot.done_date ? `hotovo ${WEEKDAY_SHORT[parseDateWeekday(slot.done_date)] ?? ""} ${fmtDayMonth(slot.done_date)}` : minutesText(slot)}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
