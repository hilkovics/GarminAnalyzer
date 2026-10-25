// Daily wellness charts over WellnessDayDTO: sleep stages, score / RHR with the 28-day baseline band, debt, Body Battery.
import { Area, Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { Schemas } from "@/api/client";
import { AXIS, Empty, GRID, legendStyle, tooltipStyle } from "@/components/charts";
import { fmtDate, fmtDayMonth, fmtDuration, fmtNum, valid } from "@/lib/format";

type Day = Schemas["WellnessDayDTO"];
type BaselineField = "sleep_score" | "rhr";

const NO_DATA = "Zatiaľ žiadne wellness dáta v tomto rozsahu.";
const STAGES = [
  { key: "deep_s", label: "Hlboký", color: "var(--z4)" },
  { key: "light_s", label: "Ľahký", color: "var(--z2)" },
  { key: "rem_s", label: "REM", color: "var(--green)" },
  { key: "awake_s", label: "Bdelý", color: "var(--bike)" },
] as const;

const legendText = (value: string) => <span style={{ color: "var(--muted)" }}>{value}</span>;
const hours = (s: number | null) => (s === null ? null : s / 3600);
const xAxis = <XAxis dataKey="date" tickFormatter={fmtDayMonth} minTickGap={32} {...AXIS} />;
const dateLabel = (d: string) => fmtDate(d);
const margin = { top: 8, right: 8, bottom: 0, left: -12 };

export function SleepStagesChart({ days }: { days: Day[] }) {
  const rows = days.filter((d) => STAGES.some((s) => d[s.key] !== null));
  if (!rows.length) return <Empty text={NO_DATA} height={300} />;
  const data = rows.map((d) => ({ date: d.date, ...Object.fromEntries(STAGES.map((s) => [s.key, hours(d[s.key])])) }));
  return (
    <ResponsiveContainer width="100%" height={320}>
      <ComposedChart data={data} margin={margin}>
        <CartesianGrid {...GRID} />
        {xAxis}
        <YAxis {...AXIS} width={44} tickFormatter={(v: number) => fmtNum(v)} />
        <Tooltip {...tooltipStyle()} labelFormatter={dateLabel} formatter={(v: number, name: string) => [fmtDuration(v * 3600), name]} />
        <Legend {...legendStyle} formatter={legendText} />
        {STAGES.map((s) => (
          <Bar key={s.key} dataKey={s.key} name={s.label} stackId="sleep" fill={s.color} isAnimationActive={false} />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** Line of one field, its 28-day median (dashed) and a median ± MAD band. */
export function BaselineChart({ days, field, name, unit, color, domain }: { days: Day[]; field: BaselineField; name: string; unit: string; color: string; domain?: [number | string, number | string] }) {
  if (!days.some((d) => d[field] !== null)) return <Empty text={NO_DATA} height={260} />;
  const data = days.map((d) => {
    const { median, mad } = d.baselines[field];
    return { date: d.date, value: d[field], median, band: valid(median) ? [median - (mad ?? 0), median + (mad ?? 0)] : null };
  });
  const text = (v: number) => fmtNum(v, 0, unit === "bpm" ? "bpm" : "");
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} margin={margin}>
        <CartesianGrid {...GRID} />
        {xAxis}
        <YAxis {...AXIS} width={44} domain={domain ?? ["auto", "auto"]} tickFormatter={(v: number) => fmtNum(v)} />
        <Tooltip {...tooltipStyle()} labelFormatter={dateLabel} formatter={(v: number, n: string) => [text(v), n]} />
        <Legend {...legendStyle} formatter={legendText} />
        <Area dataKey="band" name="± MAD" stroke="none" fill="var(--neutral)" fillOpacity={0.3} tooltipType="none" isAnimationActive={false} legendType="rect" />
        <Line dataKey="median" name="Medián 28 dní" stroke="var(--muted)" strokeDasharray="5 4" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        <Line dataKey="value" name={name} stroke={color} strokeWidth={2} dot={{ r: 2 }} connectNulls={false} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

const signedDuration = (s: number) => (s < 0 ? "−" : "") + fmtDuration(Math.abs(s));

/** 7-night sleep debt in hours (positive = debt, negative = surplus). */
export function SleepDebtChart({ days }: { days: Day[] }) {
  const rows = days.filter((d) => d.sleep_debt_7_s !== null);
  if (!rows.length) return <Empty text="Spánkový dlh sa počíta z aspoň 5 nocí za posledných 7." height={240} />;
  const data = rows.map((d) => ({ date: d.date, debt: hours(d.sleep_debt_7_s) }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <ComposedChart data={data} margin={margin}>
        <CartesianGrid {...GRID} />
        {xAxis}
        <YAxis {...AXIS} width={44} tickFormatter={(v: number) => fmtNum(v)} unit=" h" />
        <ReferenceLine y={0} stroke="var(--dim)" strokeDasharray="2 3" />
        <Tooltip {...tooltipStyle()} labelFormatter={dateLabel} formatter={(v: number, n: string) => [signedDuration(v * 3600), n]} />
        <Line dataKey="debt" name="Spánkový dlh (7 nocí)" stroke="var(--red)" strokeWidth={2.5} dot={false} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** Body Battery at wake and the day's average stress, both on Garmin's 0–100 scale. */
export function RecoveryChart({ days }: { days: Day[] }) {
  if (!days.some((d) => d.body_battery_wake !== null || d.stress_avg !== null)) return <Empty text={NO_DATA} height={240} />;
  const data = days.map((d) => ({ date: d.date, bb: d.body_battery_wake, stress: d.stress_avg }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <ComposedChart data={data} margin={margin}>
        <CartesianGrid {...GRID} />
        {xAxis}
        <YAxis {...AXIS} width={44} domain={[0, 100]} tickFormatter={(v: number) => fmtNum(v)} />
        <Tooltip {...tooltipStyle()} labelFormatter={dateLabel} formatter={(v: number, n: string) => [fmtNum(v, 0), n]} />
        <Legend {...legendStyle} formatter={legendText} />
        <Line dataKey="bb" name="Body Battery po prebudení" stroke="var(--green)" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
        <Line dataKey="stress" name="Stres (priemer)" stroke="var(--yellow)" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
