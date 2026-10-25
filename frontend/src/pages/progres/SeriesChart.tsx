// Per-activity metric points with the 28-day median line (EF, decoupling, pace at reference HR).
// DTO in, SVG out: the only transformations are unit conversions for display (m/s → s/km).
import type { AxisDomain } from "recharts/types/util/types";
import { CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";

import type { Schemas } from "@/api/client";
import { AXIS, Empty, GRID, legendStyle, tooltipStyle } from "@/components/charts";
import { fmtDate, fmtNum, fmtPace, valid } from "@/lib/format";

import { dateTicks, dateX, niceTicks, paceAxis, paceS } from "./axes";

type Series = Schemas["SeriesDTO"];
type Row = { t: number; y: number | null; text: string };

export type SeriesKind = {
  /** m/s or metric value → y on the axis */
  y: (value: number) => number | null;
  /** value → hover text */
  text: (value: number) => string;
  /** y-axis tick label (not used by the pace axis) */
  tick?: (value: number) => string;
  pace?: boolean;
  bands?: { level: number; label: string; color: string }[];
  empty: string;
  name: string;
  axisLabel: string;
};

export const EF_KIND: SeriesKind = {
  y: (v) => v,
  text: (v) => fmtNum(v, 3),
  tick: (v) => fmtNum(v, 2),
  empty: "Zatiaľ žiadne steady-state aktivity s EF.",
  name: "EF (steady-state)",
  axisLabel: "EF (m/min na úder)",
};
export const DECOUPLING_KIND: SeriesKind = {
  y: (v) => v,
  text: (v) => fmtNum(v, 1, "%"),
  tick: (v) => fmtNum(v, 0, "%"),
  bands: [
    { level: 5, label: "5 % – dobré", color: "var(--yellow)" }, // METRICS §5.3
    { level: 10, label: "10 % – slabé", color: "var(--red)" },
  ],
  empty: "Zatiaľ žiadne steady-state aktivity s decouplingom.",
  name: "Decoupling",
  axisLabel: "Decoupling (%)",
};
export const PACE_REF_KIND: SeriesKind = {
  y: paceS,
  text: fmtPace,
  pace: true,
  empty: "Zatiaľ žiadne behy s dostatkom dát okolo referenčného tepu (≥ 20 min).",
  name: "Tempo pri referenčnom tepe",
  axisLabel: "Tempo (min/km)",
};

export function shortDate(t: number): string {
  const d = new Date(t);
  return `${d.getDate()}. ${d.getMonth() + 1}. ${String(d.getFullYear()).slice(2)}`;
}

/** A local-midnight timestamp → "YYYY-MM-DD" without a UTC shift. */
function dayText(t: number): string {
  const d = new Date(t);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function SeriesTip({ active, payload }: { active?: boolean; payload?: { name?: string; payload?: Row }[] }) {
  const item = payload?.find((p) => p.payload && valid(p.payload.t));
  if (!active || !item?.payload) return null;
  return (
    <div style={tooltipStyle().contentStyle} className="px-2.5 py-1.5">
      <div className="text-muted">{fmtDate(dayText(item.payload.t))}</div>
      <div className="num">
        {item.name}: {item.payload.text}
      </div>
    </div>
  );
}

export function SeriesChart({ series, kind, height = 300 }: { series: Series; kind: SeriesKind; height?: number }) {
  const points: Row[] = series.points
    .filter((p) => valid(p.value))
    .map((p) => ({ t: dateX(p.local_date), y: kind.y(p.value as number), text: kind.text(p.value as number) }))
    .filter((p) => p.y !== null);
  if (!points.length) return <Empty text={kind.empty} height={height} />;
  const trend: Row[] = series.trend.map((t) => ({
    t: dateX(t.date),
    y: valid(t.value) ? kind.y(t.value) : null,
    text: valid(t.value) ? kind.text(t.value) : "–",
  }));
  const hasTrend = trend.some((t) => t.y !== null);
  const times = [...points, ...trend.filter((r) => r.y !== null)].map((r) => r.t);
  const min = Math.min(...times);
  const max = Math.max(...times);
  const ys = [...points, ...trend].map((r) => r.y);
  const yValues = ys.filter(valid);
  const lo = Math.min(...yValues, ...(kind.bands ? [0] : []));
  const hi = Math.max(...yValues, ...(kind.bands ? [kind.bands[kind.bands.length - 1].level + 1] : []));
  const yAxis = kind.pace
    ? paceAxis(ys)
    : kind.bands
      ? { ticks: niceTicks(lo, hi, 5), domain: [(l: number) => Math.min(l, 0), (h: number) => Math.max(h, hi)] as AxisDomain, tickFormatter: kind.tick }
      : { domain: ["auto", "auto"] as AxisDomain, tickFormatter: kind.tick };
  return (
    <div role="img" aria-label={`${kind.name}: ${points.length} aktivít, od ${fmtDate(dayText(min))} do ${fmtDate(dayText(max))}`}>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
          <CartesianGrid {...GRID} />
          <XAxis type="number" dataKey="t" domain={[min, max]} ticks={dateTicks(min, max, 4)} tickFormatter={shortDate} allowDuplicatedCategory={false} {...AXIS} />
          <YAxis type="number" dataKey="y" width={52} allowDecimals {...AXIS} {...yAxis} />
          <Tooltip content={<SeriesTip />} cursor={false} />
          <Legend {...legendStyle} />
          {kind.bands?.map((b) => (
            <ReferenceLine key={b.level} y={b.level} stroke={b.color} strokeDasharray="5 4" ifOverflow="extendDomain" label={{ value: b.label, position: "insideTopLeft", fill: b.color, fontSize: 11 }} />
          ))}
          <Scatter name={kind.name} data={points} dataKey="y" fill="var(--run)" fillOpacity={0.65} isAnimationActive={false} />
          {hasTrend && <Line name="Medián 28 dní" data={trend} dataKey="y" stroke="var(--text)" strokeWidth={2.25} dot={false} connectNulls={false} isAnimationActive={false} activeDot={{ r: 3 }} />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** The latest non-empty trend value (a display pick, not a computation). */
export function latestTrend(series: Series | undefined): number | null {
  const last = [...(series?.trend ?? [])].reverse().find((t) => valid(t.value));
  return last ? (last.value as number) : null;
}
