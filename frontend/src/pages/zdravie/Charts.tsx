// Overlaid health charts (METRICS §12.2): small multiples on one shared time axis (synchronised hover), each
// with the daily value, the 7-day mean and the personal normal band; and one chart of every selected metric
// relative to its normal (%, a single axis – never two scales).
import { Area, CartesianGrid, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { Schemas } from "@/api/client";
import { AXIS, GRID, legendStyle, tooltipStyle } from "@/components/charts";
import { Table } from "@/components/ui";
import { fmtDate, fmtDayMonth, fmtNum, fmtPctSigned } from "@/lib/format";

import { axisTick, axisUnit, fmtMetric, SERIES_COLORS } from "./format";

type Series = Schemas["HealthSeriesDTO"];

const SYNC = "health";

function Panel({ s, color }: { s: Series; color: string }) {
  const data = s.points.map((p) => ({
    date: p.date,
    value: p.value,
    mean7: p.mean7,
    median: p.median28,
    band: p.median28 !== null && p.median28 !== undefined && p.mad28 !== null && p.mad28 !== undefined ? [p.median28 - p.mad28, p.median28 + p.mad28] : null,
  }));
  const tick = axisTick(s.unit);
  return (
    <div>
      <div className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} aria-hidden />
        {s.label} {axisUnit(s.unit) && <span className="text-xs font-normal text-muted">({axisUnit(s.unit)})</span>}
      </div>
      <div role="img" aria-label={`${s.label}: denné hodnoty, 7-dňový priemer a pásmo tvojho normálu`}>
        <ResponsiveContainer width="100%" height={150}>
          <ComposedChart data={data} syncId={SYNC} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="date" {...AXIS} tick={{ fontSize: 11 }} tickFormatter={fmtDayMonth} minTickGap={40} />
            <YAxis {...AXIS} width={48} tickFormatter={tick} domain={["auto", "auto"]} />
            <Tooltip
              {...tooltipStyle()}
              labelFormatter={(l) => fmtDate(String(l))}
              formatter={(v: number | number[], name: string) => [Array.isArray(v) ? `${fmtMetric(v[0], s.unit)} – ${fmtMetric(v[1], s.unit)}` : fmtMetric(v, s.unit), name]}
            />
            <Area dataKey="band" name="Normál (± MAD)" stroke="none" fill="var(--neutral)" fillOpacity={0.18} isAnimationActive={false} connectNulls={false} />
            <Line dataKey="median" name="Normál (medián 28 dní)" stroke="var(--neutral)" strokeDasharray="4 3" strokeWidth={1} dot={false} isAnimationActive={false} />
            <Line dataKey="value" name="Deň" stroke="none" dot={{ r: 2, fill: color, fillOpacity: 0.45, stroke: "none" }} activeDot={{ r: 4 }} isAnimationActive={false} />
            <Line dataKey="mean7" name="Priemer 7 dní" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function StackedCharts({ series }: { series: Series[] }) {
  return (
    <div className="flex flex-col gap-3">
      {series.map((s, i) => (
        <Panel key={s.key} s={s} color={SERIES_COLORS[i]} />
      ))}
      <p className="text-xs text-muted">Bodky = jednotlivé dni, čiara = 7-dňový priemer, sivé pásmo = tvoj normál (medián 28 dní ± MAD). Grafy majú spoločnú časovú os.</p>
    </div>
  );
}

export function RelativeChart({ series }: { series: Series[] }) {
  const byDate = new Map<string, Record<string, number | string | null>>();
  series.forEach((s) =>
    s.points.forEach((p) => {
      const row = byDate.get(p.date) ?? { date: p.date };
      row[s.key] = p.pct ?? null;
      byDate.set(p.date, row);
    }),
  );
  const data = [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));
  return (
    <div role="img" aria-label="Vybrané ukazovatele v percentách oproti tvojmu normálu (7-dňový priemer). Hodnoty sú v tabuľke nižšie.">
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="date" {...AXIS} tick={{ fontSize: 11 }} tickFormatter={fmtDayMonth} minTickGap={40} />
          <YAxis {...AXIS} width={48} tickFormatter={(v: number) => `${fmtNum(v)} %`} />
          <ReferenceLine y={0} stroke="var(--border-strong)" label={{ value: "tvoj normál", position: "insideTopLeft", fontSize: 11, fill: "var(--muted)" }} />
          <Tooltip {...tooltipStyle()} labelFormatter={(l) => fmtDate(String(l))} formatter={(v: number, name: string) => [fmtPctSigned(v / 100), name]} />
          <Legend {...legendStyle} />
          {series.map((s, i) => (
            <Line key={s.key} dataKey={s.key} name={s.label} stroke={SERIES_COLORS[i]} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SeriesTable({ series }: { series: Series[] }) {
  const dates = series[0]?.points.map((p) => p.date) ?? [];
  const last = dates.slice(-14).reverse();
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-muted hover:text-text">Tabuľka posledných 14 dní</summary>
      <div className="mt-2">
        <Table
          head={["Deň", ...series.map((s) => s.label)]}
          align={["left", ...series.map(() => "right" as const)]}
          rows={last.map((d) => [
            fmtDate(d),
            ...series.map((s) => {
              const p = s.points.find((x) => x.date === d);
              return `${fmtMetric(p?.value, s.unit)} (${fmtPctSigned(p?.pct === null || p?.pct === undefined ? null : p.pct / 100)})`;
            }),
          ])}
        />
      </div>
    </details>
  );
}
