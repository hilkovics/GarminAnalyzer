// "Tento týždeň": target / done / remaining with progress, planned-vs-actual chart, seven day cards, week table.
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { AXIS, GRID, legendStyle, tooltipStyle } from "@/components/charts";
import { Badge, Card, Table, cx } from "@/components/ui";
import { DASH, fmtDate, fmtDayMonth, fmtNum, isoWeekLabel, WEEKDAY_SHORT } from "@/lib/format";
import { FITNESS_SLOT_LABELS, FITNESS_SLOT_SHORT, phaseText, PHASE_COLORS, ROLE_LABELS, ROLE_SHORT, statusBadge } from "@/lib/labels";
import { SportIcon } from "@/pages/dashboard/TodayCards";

import { FitnessWeek } from "./FitnessWeek";
import { addDays, type WeekPlan } from "./shared";

type Day = WeekPlan["days"][number];

const estimate = (d: Day) => (d.planned && d.planned.sport !== "rest" ? fmtNum(d.planned.estimated_load) : DASH);
const actual = (d: Day) => (d.activities ? fmtNum(d.actual_load) : DASH);
const dayLabel = (d: Day) => `${WEEKDAY_SHORT[d.weekday] ?? d.weekday} ${fmtDayMonth(d.date)}`;

/** The day's chip: the template role (§10), or in fitness mode the menu item of its plan (§11.1). */
function roleOf(day: Day, fitness: boolean): { short: string; label: string } {
  if (fitness) {
    const slot = day.planned?.slot ?? "";
    return FITNESS_SLOT_SHORT[slot]
      ? { short: FITNESS_SLOT_SHORT[slot], label: FITNESS_SLOT_LABELS[slot] }
      : { short: "–", label: day.planned?.sport === "bike" ? "Bicykel navyše" : "Bez položky menu" };
  }
  return { short: ROLE_SHORT[day.role] ?? day.role, label: ROLE_LABELS[day.role] ?? day.role };
}

function DayCard({ day, today, fitness }: { day: Day; today: boolean; fitness: boolean }) {
  const badge = statusBadge(day.planned, fitness ? null : day.role);
  const role = roleOf(day, fitness);
  const sport = day.planned?.sport;
  return (
    <li
      aria-current={today ? "date" : undefined}
      className={cx(
        "flex min-w-0 items-center gap-3 rounded-lg border p-3 xl:flex-col xl:items-stretch xl:gap-2",
        today ? "border-accent bg-accent/10 ring-1 ring-accent" : "border-line bg-card-2",
      )}
    >
      <div className="flex w-14 shrink-0 items-center justify-between gap-1 xl:w-auto">
        <div className="leading-tight">
          <div className="text-sm font-bold">{WEEKDAY_SHORT[day.weekday] ?? day.weekday}</div>
          <div className="num text-xs text-muted">{fmtDayMonth(day.date)}</div>
        </div>
        <span title={role.label} className="num hidden rounded border border-line-strong px-1.5 text-[11px] font-bold xl:inline">
          {role.short}
        </span>
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5 xl:flex-none">
        <div className="flex min-w-0 items-start gap-1.5 text-sm font-medium leading-snug">
          {sport && sport !== "rest" && <SportIcon sport={sport} size={15} />}
          <span className="min-w-0 break-words">{day.planned?.name ?? DASH}</span>
        </div>
        <div className="num flex flex-wrap gap-x-2 text-xs text-muted xl:flex-col xl:gap-x-0">
          <span className="xl:hidden">{role.short}</span>
          <span>Odhad {estimate(day)}</span>
          <span>Skut. {actual(day)}</span>
          {day.commute_load ? <span>Doch. {fmtNum(day.commute_load)}</span> : null}
        </div>
      </div>
      <div className="shrink-0 xl:mt-auto">
        <Badge tone={badge.tone}>{badge.text}</Badge>
      </div>
    </li>
  );
}

function WeekChart({ week }: { week: WeekPlan }) {
  const hasCommute = week.days.some((d) => d.commute_load);
  const data = week.days.map((d) => ({
    label: WEEKDAY_SHORT[d.weekday] ?? d.weekday,
    full: dayLabel(d),
    plan: d.planned?.estimated_load ?? 0,
    done: d.actual_load,
    commute: d.commute_load ?? 0,
  }));
  return (
    <div role="img" aria-label="Záťaž podľa dní: plán (odhad) a skutočnosť. Hodnoty sú v tabuľke nižšie.">
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: -16 }} barGap={2}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="label" interval={0} {...AXIS} tick={{ fontSize: 11 }} />
          <YAxis {...AXIS} width={44} tickFormatter={(v: number) => fmtNum(v)} />
          <Tooltip {...tooltipStyle()} labelFormatter={(_l, p) => p?.[0]?.payload?.full ?? _l} formatter={(v: number, name: string) => [fmtNum(v), name]} />
          <Legend {...legendStyle} />
          <Bar dataKey="plan" name="Plán (odhad)" fill="var(--neutral)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="done" name="Skutočnosť" fill="var(--accent)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
          {hasCommute && <Bar dataKey="commute" name="Dochádzka" fill="var(--neutral)" fillOpacity={0.45} radius={[3, 3, 0, 0]} isAnimationActive={false} />}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function WeekTable({ week }: { week: WeekPlan }) {
  const fitness = week.mode === "fitness";
  const rows = week.days.map((d) => {
    const badge = statusBadge(d.planned, fitness ? null : d.role);
    return [
      <span className="font-sans">
        {WEEKDAY_SHORT[d.weekday]} {fmtDate(d.date)}
      </span>,
      <span className="font-sans">{roleOf(d, fitness).label}</span>,
      <span className="font-sans">{d.planned?.name ?? DASH}</span>,
      estimate(d),
      actual(d),
      <Badge tone={badge.tone}>{badge.text}</Badge>,
    ];
  });
  return (
    <details className="mt-4 text-sm">
      <summary className="cursor-pointer text-muted hover:text-text">Tabuľka týždňa</summary>
      <div className="mt-2">
        <Table head={["Deň", "Rola", "Plán", "Odhad záťaže", "Skutočná záťaž", "Stav"]} align={["left", "left", "left", "right", "right", "left"]} rows={rows} />
      </div>
    </details>
  );
}

export function WeekBlock({ week, today, onNavigate, pending }: { week: WeekPlan; today: string; onNavigate: (date: string) => void; pending: boolean }) {
  const progress = week.target_load > 0 ? Math.min(1, week.done_load / week.target_load) : 0;
  const fitness = week.mode === "fitness";
  const nav = "rounded-lg border border-line-strong p-1.5 text-muted hover:bg-card-2 hover:text-text";
  const current = week.days.some((d) => d.date === today);
  return (
    <Card
      title="Tento týždeň"
      right={
        <div className="flex items-center gap-1.5 text-xs text-muted">
          <button type="button" className={nav} aria-label="Predchádzajúci týždeň" onClick={() => onNavigate(addDays(week.monday, -7))}>
            <ChevronLeft size={16} />
          </button>
          <span className="num min-w-24 text-center">
            {isoWeekLabel(week.monday)} · od {fmtDayMonth(week.monday)}
          </span>
          <button type="button" className={nav} aria-label="Nasledujúci týždeň" onClick={() => onNavigate(addDays(week.monday, 7))}>
            <ChevronRight size={16} />
          </button>
          {!current && (
            <button type="button" className="ml-1 font-medium text-accent hover:underline" onClick={() => onNavigate(today)}>
              Tento týždeň
            </button>
          )}
        </div>
      }
      className={pending ? "opacity-70" : undefined}
    >
      {fitness ? (
        week.fitness ? (
          <FitnessWeek fitness={week.fitness} />
        ) : (
          <p className="text-sm text-muted">Tento týždeň nie je v bloku trénera Kondícia (pred prvým blokom alebo v budúcnosti).</p>
        )
      ) : (
        <LoadSummary week={week} progress={progress} />
      )}
      <div className="mt-3">
        <WeekChart week={week} />
      </div>
      <ul className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        {week.days.map((d) => (
          <DayCard key={d.date} day={d} today={d.date === today} fitness={fitness} />
        ))}
      </ul>
      <WeekTable week={week} />
    </Card>
  );
}

/** §10 weekly load: target / done / remaining and the progress bar. */
function LoadSummary({ week, progress }: { week: WeekPlan; progress: number }) {
  return (
    <>
      <p className="text-sm text-muted">
        Fáza: <strong style={{ color: PHASE_COLORS[week.phase] }}>{phaseText(week.phase, week.recovery)}</strong> · cieľ{" "}
        <span className="num text-text">{fmtNum(week.target_load)}</span> (beh {fmtNum(week.run_target)}, bicykel {fmtNum(week.bike_target)}) · hotovo{" "}
        <span className="num text-text">{fmtNum(week.done_load)}</span> · zostáva <span className="num text-text">{fmtNum(week.remaining_load)}</span>
        {week.commute_load ? <> · dochádzka {fmtNum(week.commute_load)}</> : null}
      </p>
      <div className="mt-3 flex items-center gap-3">
        <div
          className="h-2 flex-1 overflow-hidden rounded-full bg-line"
          role="progressbar"
          aria-label="Splnenie týždenného cieľa"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress * 100)}
        >
          <div className="h-full rounded-full bg-accent" style={{ width: `${progress * 100}%` }} />
        </div>
        <span className="num text-sm font-semibold">{fmtNum(progress * 100)} %</span>
      </div>
    </>
  );
}
