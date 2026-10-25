// Streams of one activity: HR, pace (bike: km/h) and altitude as stacked small charts on one time axis.
// The charts share a Recharts `syncId`, so the cursor and tooltip move together. Display conversions only:
// s → min on the x-axis, m/s → s/km (axis reversed, faster is higher) or km/h.
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useApi, type Schemas } from "@/api/client";
import { AXIS, Empty, GRID, tooltipStyle } from "@/components/charts";
import { Card, Loading, Notice } from "@/components/ui";
import { fmtDurationHms, fmtNum, fmtPaceS, valid } from "@/lib/format";

type Row = Record<string, number | null>;
type Panel = { key: string; title: string; unit: string };

const PACE_CAP_S = 900; // slower than 15:00/km (standing still) is drawn as a gap so it cannot flatten the axis
const SYNC = "activity-streams";
const MARGIN = { top: 6, right: 8, bottom: 0, left: 0 };

const has = (values?: (number | null)[]) => Boolean(values?.some(valid));
const pace = (v: number | null | undefined) => (valid(v) && v > 0 && 1000 / v <= PACE_CAP_S ? 1000 / v : null);
const kmh = (v: number | null | undefined) => (valid(v) ? v * 3.6 : null);

/** One row per point with the display units already applied. */
function toRows(streams: Schemas["StreamsDTO"], bike: boolean): Row[] {
  const { hr, speed, gap_speed: gap, alt } = streams.series;
  return streams.t.map((t, i) => ({
    min: t / 60,
    hr: hr?.[i] ?? null,
    speed: bike ? kmh(speed?.[i]) : pace(speed?.[i]),
    gap: bike ? null : pace(gap?.[i]),
    alt: alt?.[i] ?? null,
  }));
}

/** Pace axis ticks every 30 s/km (60 s/km on a wide range) so the labels are round m:ss values. */
function paceTicks(values: (number | null)[]): number[] | undefined {
  const v = values.filter(valid);
  if (!v.length) return undefined;
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const step = hi - lo > 300 ? 60 : 30;
  const out: number[] = [];
  for (let t = Math.floor(lo / step) * step; t <= Math.ceil(hi / step) * step; t += step) out.push(t);
  return out;
}

function Panel({ rows, panel, bike, last, height }: { rows: Row[]; panel: Panel; bike: boolean; last: boolean; height: number }) {
  const isPace = panel.key === "speed" && !bike;
  const tick = (v: number) => (isPace ? fmtPaceS(v) : fmtNum(v, 0));
  const color = panel.key === "hr" ? "var(--red)" : panel.key === "speed" ? (bike ? "var(--bike)" : "var(--run)") : "var(--dim)";
  const pad = panel.key === "alt" ? 5 : 0;
  const domain: [(v: number) => number, (v: number) => number] = isPace
    ? [(v) => Math.floor(v / 30) * 30, (v) => Math.ceil(v / 30) * 30]
    : [(v) => Math.floor(v / 10) * 10 - pad, (v) => Math.ceil(v / 10) * 10 + pad];
  const ticks = isPace ? paceTicks(rows.map((r) => r.speed)) : undefined;
  return (
    <div>
      <div className="mb-0.5 flex items-center gap-1.5 text-xs text-muted">
        <span className="inline-block h-0.5 w-3 rounded" style={{ background: color }} />
        {panel.title} <span className="text-dim">({panel.unit})</span>
        {isPace && has(rows.map((r) => r.gap)) && <span className="ml-2 text-dim">čiarkovane: GAP</span>}
      </div>
      <ResponsiveContainer width="100%" height={height + (last ? 22 : 0)}>
        <ComposedChart data={rows} syncId={SYNC} margin={MARGIN}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="min" type="number" domain={[0, "dataMax"]} hide={!last} tickFormatter={(v: number) => fmtNum(v, 0)} {...AXIS} height={last ? 22 : 0} />
          <YAxis
            {...AXIS}
            width={44}
            reversed={isPace}
            domain={domain}
            tickCount={4}
            ticks={ticks}
            tickFormatter={tick}
            allowDecimals={false}
          />
          <Tooltip
            {...tooltipStyle()}
            isAnimationActive={false}
            labelFormatter={(m: number) => `čas ${fmtDurationHms(m * 60)}`}
            formatter={(v: number, name: string) => [isPace ? `${fmtPaceS(v)}/km` : `${fmtNum(v, bike && panel.key === "speed" ? 1 : 0)} ${panel.unit}`, name]}
          />
          {panel.key === "alt" ? (
            <Area dataKey="alt" name="Výška" stroke="var(--dim)" fill="var(--neutral)" fillOpacity={0.35} strokeWidth={1} dot={false} isAnimationActive={false} connectNulls />
          ) : (
            <Line dataKey={panel.key} name={panel.title} stroke={color} strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls={false} />
          )}
          {isPace && <Line dataKey="gap" name="GAP" stroke="var(--dim)" strokeWidth={1.2} strokeDasharray="4 3" dot={false} isAnimationActive={false} />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function StreamsCard({ activityId, sport }: { activityId: number; sport: string }) {
  const bike = sport === "bike";
  const query = useApi<Schemas["StreamsDTO"]>(`/activities/${activityId}/streams`, {
    fields: bike ? "hr,speed,alt" : "hr,speed,gap_speed,alt",
    points: 1500,
  });
  return (
    <Card title="Priebeh" right={<span className="text-xs text-muted">čas v minútach</span>}>
      {query.isPending ? (
        <Loading />
      ) : query.error || !query.data ? (
        <Notice>Priebeh nie je k dispozícii: {query.error?.message}</Notice>
      ) : (
        <Streams streams={query.data} bike={bike} />
      )}
    </Card>
  );
}

function Streams({ streams, bike }: { streams: Schemas["StreamsDTO"]; bike: boolean }) {
  const s = streams.series;
  const panels: Panel[] = [
    has(s.hr) && { key: "hr", title: "Tep", unit: "bpm" },
    has(s.speed) && { key: "speed", title: bike ? "Rýchlosť" : "Tempo", unit: bike ? "km/h" : "min/km" },
    has(s.alt) && { key: "alt", title: "Výška", unit: "m n. m." },
  ].filter((p): p is Panel => Boolean(p));
  if (!streams.t.length || !panels.length) return <Empty text="Pre túto aktivitu nie sú k dispozícii dáta streamu." />;
  const rows = toRows(streams, bike);
  return (
    <div role="group" aria-label="Priebeh tepu, tempa a výšky v čase" className="flex flex-col gap-2">
      {panels.map((p, i) => (
        <Panel key={p.key} rows={rows} panel={p} bike={bike} last={i === panels.length - 1} height={p.key === "alt" ? 90 : 130} />
      ))}
      <p className="text-xs text-muted">
        {streams.points} bodov zo {streams.source_points} vzoriek.
      </p>
    </div>
  );
}
