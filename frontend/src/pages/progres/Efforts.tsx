// Best efforts (METRICS §6.2): 90 days vs all time as curves (pace for runs, km/h for bikes), HR curve and a table.
import { CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { Schemas } from "@/api/client";
import { AXIS, Empty, GRID, legendStyle, tooltipStyle } from "@/components/charts";
import { Table } from "@/components/ui";
import { fmtDate, fmtNum, fmtSpeed, fmtWindow, valid } from "@/lib/format";

import { paceAxis, paceS } from "./axes";

type Efforts = Schemas["BestEffortsDTO"];
type Effort = Schemas["BestEffortDTO"];

const SERIES = [
  { key: "recent", name: "Posledných 90 dní", color: "var(--run)" },
  { key: "all", name: "Celá história", color: "var(--bike)" },
] as const;

function byWindow(dto: Efforts | undefined, kind: string): Map<number, Effort> {
  return new Map((dto?.efforts ?? []).filter((e) => e.kind === kind).map((e) => [e.window_s, e]));
}

export function windows(kind: string, recent?: Efforts, all?: Efforts): number[] {
  return [...new Set([...byWindow(recent, kind).keys(), ...byWindow(all, kind).keys()])].sort((a, b) => a - b);
}

export const speedKind = (sport: string) => (sport === "run" ? "gap_speed" : "speed");

type Row = Record<string, number | string | null>;

function rowsFor(kind: string, y: (v: number) => number | null, text: (v: number) => string, recent?: Efforts, all?: Efforts): Row[] {
  const maps = { recent: byWindow(recent, kind), all: byWindow(all, kind) };
  return windows(kind, recent, all).map((w) => {
    const row: Row = { label: fmtWindow(w) };
    for (const s of SERIES) {
      const e = maps[s.key].get(w);
      row[s.key] = e ? y(e.value) : null;
      row[`${s.key}_text`] = e ? `${text(e.value)} (${fmtDate(e.local_date)})` : "–";
    }
    return row;
  });
}

function EffortLines({ rows, axis, height, label }: { rows: Row[]; axis: object; height: number; label: string }) {
  return (
    <div role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="label" interval={0} tick={{ fontSize: 11 }} {...AXIS} />
          <YAxis width={48} {...AXIS} {...axis} />
          <Tooltip {...tooltipStyle()} formatter={(_: number, name: string, item) => [String(item.payload[`${String(item.dataKey)}_text`]), name]} />
          <Legend {...legendStyle} />
          {SERIES.map((s) => (
            <Line key={s.key} name={s.name} dataKey={s.key} stroke={s.color} strokeWidth={2.25} dot={{ r: 3, fill: s.color, strokeWidth: 0 }} connectNulls={false} isAnimationActive={false} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SpeedEfforts({ sport, recent, all }: { sport: string; recent?: Efforts; all?: Efforts }) {
  const kind = speedKind(sport);
  const run = sport === "run";
  const rows = rowsFor(kind, run ? paceS : (v) => v * 3.6, (v) => fmtSpeed(v, sport), recent, all);
  if (!rows.length) return <Empty text="Zatiaľ žiadne najlepšie úseky." height={240} />;
  const axis = run
    ? paceAxis(rows.flatMap((r) => [r.recent, r.all] as (number | null)[]))
    : { tickFormatter: (v: number) => fmtNum(v, 1), domain: [(lo: number) => Math.floor(lo) - 1, (hi: number) => Math.ceil(hi) + 1] };
  return <EffortLines rows={rows} axis={axis} height={300} label={`Najlepšie úseky ${run ? "(tempo GAP)" : "(rýchlosť)"}: 90 dní vs celá história`} />;
}

export function HrEfforts({ recent, all }: { recent?: Efforts; all?: Efforts }) {
  const rows = rowsFor("hr", (v) => v, (v) => fmtNum(v, 0, "bpm"), recent, all);
  if (!rows.length) return <Empty text="Zatiaľ žiadne tepové maximá úsekov." height={160} />;
  const axis = { tickFormatter: (v: number) => fmtNum(v, 0), allowDecimals: false, domain: [(lo: number) => Math.floor(lo) - 2, (hi: number) => Math.ceil(hi) + 2] };
  return <EffortLines rows={rows} axis={axis} height={220} label="Najvyšší priemerný tep úsekov: 90 dní vs celá história" />;
}

/** Window × (90 days, all time) for pace/speed and mean HR; the date of each effort under its value. */
export function EffortsTable({ sport, recent, all }: { sport: string; recent?: Efforts; all?: Efforts }) {
  const kind = speedKind(sport);
  const speedRecent = byWindow(recent, kind);
  const speedAll = byWindow(all, kind);
  const hrRecent = byWindow(recent, "hr");
  const hrAll = byWindow(all, "hr");
  const wins = [...new Set([...windows(kind, recent, all), ...windows("hr", recent, all)])].sort((a, b) => a - b);
  if (!wins.length) return null;
  const cell = (e: Effort | undefined, text: (v: number) => string) =>
    e && valid(e.value) ? (
      <span className="flex flex-col items-end whitespace-nowrap leading-tight">
        {text(e.value)}
        <span className="text-[11px] font-normal text-muted">{fmtDate(e.local_date)}</span>
      </span>
    ) : (
      "–"
    );
  const hr = (v: number) => fmtNum(v, 0, "bpm");
  const speed = (v: number) => fmtSpeed(v, sport);
  const head = ["Úsek", `${sport === "run" ? "Tempo (GAP)" : "Rýchlosť"} · 90 dní`, `${sport === "run" ? "Tempo (GAP)" : "Rýchlosť"} · história`, "Tep · 90 dní", "Tep · história"];
  const rows = wins.map((w) => [
    fmtWindow(w),
    cell(speedRecent.get(w), speed),
    cell(speedAll.get(w), speed),
    cell(hrRecent.get(w), hr),
    cell(hrAll.get(w), hr),
  ]);
  return <Table head={head} rows={rows} align={["left", "right", "right", "right", "right"]} />;
}
