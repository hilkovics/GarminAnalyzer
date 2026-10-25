// "Sezóna": goal summary line and the weekly target bars coloured by phase (recovery weeks lighter, hatched).
import { Bar, BarChart, CartesianGrid, Cell, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { AXIS, Empty, GRID, tooltipStyle } from "@/components/charts";
import { Card, Notice } from "@/components/ui";
import { fmtDate, fmtDayMonth, fmtKm, fmtNum, fmtTimeHms, isoWeekLabel, sportLabel } from "@/lib/format";
import { phaseText, PHASE_COLORS, PHASE_LABELS } from "@/lib/labels";

import type { Goal, Season } from "./shared";

type Week = Season["weeks"][number];

const weekTick = (monday: string) => isoWeekLabel(monday).split("/")[0];

export function GoalSummary({ goal, season }: { goal: Goal | null; season: Season }) {
  if (!goal) {
    return <Notice>Cieľ nie je nastavený – plán beží v nekonečnom cykle 3 týždne záťaž + 1 regenerácia.</Notice>;
  }
  const parts = [
    <strong key="d">{fmtDate(goal.race_date)}</strong>,
    sportLabel(goal.sport),
    goal.distance_m ? fmtKm(goal.distance_m) : null,
    goal.target_time_s ? fmtTimeHms(goal.target_time_s) : null,
  ].filter(Boolean);
  return (
    <p className="text-sm text-muted">
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && " · "}
          {p}
        </span>
      ))}
      {" · "}aktuálna fáza: <strong style={{ color: PHASE_COLORS[season.current_phase] }}>{phaseText(season.current_phase)}</strong>
    </p>
  );
}

/** SVG hatch fills, one per phase colour (recovery weeks). */
const patterns = (
  <defs>
      {Object.entries(PHASE_COLORS).map(([phase, color]) => (
        <pattern key={phase} id={`hatch-${phase}`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="6" height="6" fill={color} fillOpacity={0.18} />
          <rect width="2" height="6" fill={color} fillOpacity={0.75} />
        </pattern>
      ))}
    </defs>
);

const Triangle = ({ cx, cy }: { cx?: number; cy?: number }) =>
  cx === undefined || cy === undefined ? null : <polygon points={`${cx - 6},${cy - 8} ${cx + 6},${cy - 8} ${cx},${cy + 2}`} fill="var(--yellow)" stroke="var(--bg)" strokeWidth={1} />;

const Flag = ({ cx, cy }: { cx?: number; cy?: number }) =>
  cx === undefined || cy === undefined ? null : (
    <g stroke="var(--bg)" strokeWidth={0.5}>
      <line x1={cx - 4} x2={cx - 4} y1={cy - 14} y2={cy + 2} stroke="var(--text)" strokeWidth={1.5} />
      <polygon points={`${cx - 4},${cy - 14} ${cx + 8},${cy - 10} ${cx - 4},${cy - 6}`} fill="var(--red)" />
    </g>
  );

function Tip({ active, payload }: { active?: boolean; payload?: { payload: Week }[] }) {
  const w = active ? payload?.[0]?.payload : undefined;
  if (!w) return null;
  return (
    <div style={tooltipStyle().contentStyle} className="px-3 py-2">
      <div className="mb-1 text-muted">
        Týždeň od {fmtDayMonth(w.monday)} ({weekTick(w.monday)})
      </div>
      <div>
        {phaseText(w.phase, w.recovery)}: <strong className="num">{fmtNum(w.target_load)}</strong>
      </div>
      <div className="num text-muted">
        beh {fmtNum(w.run_target)}, bicykel {fmtNum(w.bike_target)}
      </div>
      <div className="num text-muted">CTL na začiatku {fmtNum(w.ctl_start)}</div>
      {w.is_current && <div>Tento týždeň</div>}
      {w.is_race_week && <div>Týždeň pretekov</div>}
    </div>
  );
}

export function SeasonChart({ season }: { season: Season }) {
  const weeks = season.weeks;
  if (!weeks.length) return <Empty text="Sezóna nie je k dispozícii." />;
  const top = Math.max(...weeks.map((w) => w.target_load), 1);
  const current = weeks.find((w) => w.is_current);
  const race = weeks.find((w) => w.is_race_week);
  return (
    <div role="img" aria-label={`Cieľová záťaž po týždňoch, ${weeks.length} týždňov, farba podľa fázy.`}>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={weeks} margin={{ top: 24, right: 8, bottom: 0, left: -12 }} barCategoryGap={2}>
          {patterns}
          <CartesianGrid {...GRID} />
          <XAxis dataKey="monday" tickFormatter={weekTick} minTickGap={24} {...AXIS} />
          <YAxis {...AXIS} width={44} domain={[0, Math.ceil(top * 1.12)]} tickFormatter={(v: number) => fmtNum(v)} />
          <Tooltip content={<Tip />} cursor={tooltipStyle().cursor} />
          <Bar dataKey="target_load" name="Cieľová záťaž" isAnimationActive={false} radius={[2, 2, 0, 0]}>
            {weeks.map((w) => (
              <Cell
                key={w.monday}
                fill={w.recovery ? `url(#hatch-${w.phase})` : PHASE_COLORS[w.phase]}
                stroke={w.recovery ? PHASE_COLORS[w.phase] : "none"}
                strokeWidth={w.recovery ? 1 : 0}
              />
            ))}
          </Bar>
          {current && <ReferenceDot x={current.monday} y={current.target_load + top * 0.05} r={0} ifOverflow="visible" shape={<Triangle />} />}
          {race && <ReferenceDot x={race.monday} y={race.target_load + top * 0.05} r={0} ifOverflow="visible" shape={<Flag />} />}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Legend({ season }: { season: Season }) {
  const phases = Object.entries(PHASE_LABELS).filter(([p]) => season.weeks.some((w) => w.phase === p));
  const hasRecovery = season.weeks.some((w) => w.recovery);
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      {phases.map(([phase, label]) => (
        <li key={phase} className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: PHASE_COLORS[phase] }} /> {label}
        </li>
      ))}
      {hasRecovery && (
        <li className="flex items-center gap-1.5">
          <svg width="12" height="12" aria-hidden>
            <rect width="12" height="12" fill="var(--muted)" fillOpacity={0.2} stroke="var(--muted)" />
          </svg>
          Regenerácia
        </li>
      )}
      {season.weeks.some((w) => w.is_current) && (
        <li className="flex items-center gap-1.5">
          <svg width="12" height="12" aria-hidden>
            <polygon points="0,1 12,1 6,11" fill="var(--yellow)" />
          </svg>
          Tento týždeň
        </li>
      )}
      {season.weeks.some((w) => w.is_race_week) && (
        <li className="flex items-center gap-1.5">
          <svg width="12" height="12" aria-hidden>
            <polygon points="1,1 11,4 1,7" fill="var(--red)" />
            <line x1="1" y1="1" x2="1" y2="12" stroke="var(--text)" />
          </svg>
          Preteky
        </li>
      )}
    </ul>
  );
}

export function SeasonBlock({ goal, season }: { goal: Goal | null; season: Season }) {
  return (
    <Card title="Sezóna" right={<span className="text-xs text-muted">cieľová záťaž týždňa, TSS-ekv.</span>}>
      <div className="flex flex-col gap-3">
        <GoalSummary goal={goal} season={season} />
        <SeasonChart season={season} />
        <Legend season={season} />
      </div>
    </Card>
  );
}
