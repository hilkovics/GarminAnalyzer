import { useState } from "react";
import { Bar, BarChart, CartesianGrid, LabelList, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { Schemas } from "@/api/client";
import { AXIS, GRID, legendStyle, tooltipStyle } from "@/components/charts";
import { Card, Segmented, Table } from "@/components/ui";
import { fmtDate, fmtDuration, fmtKm, fmtLoad, fmtNum, sportLabel } from "@/lib/format";

type Week = Schemas["WeeklyDTO"];
type Metric = "load" | "duration_s" | "distance_m";

const METRICS: { value: Metric; label: string; unit: string; scale: number }[] = [
  { value: "load", label: "Záťaž", unit: "TSS-ekv.", scale: 1 },
  { value: "duration_s", label: "Čas", unit: "h", scale: 1 / 3600 },
  { value: "distance_m", label: "Vzdialenosť", unit: "km", scale: 1 / 1000 },
];

export function WeekCompare({ week, avg, weekStart }: { week: Week[]; avg: Week[]; weekStart: string }) {
  const [metric, setMetric] = useState<Metric>("load");
  const averages = new Map(avg.map((w) => [w.sport, w]));
  const spec = METRICS.find((m) => m.value === metric)!;
  const sports = week.filter((w) => w.sport !== "all");
  const total = week.find((w) => w.sport === "all");
  const data = sports.map((w) => ({
    sport: sportLabel(w.sport),
    now: w[metric] * spec.scale,
    avg: (averages.get(w.sport)?.[metric] ?? 0) * spec.scale,
  }));
  const rows = [...sports, ...(total ? [total] : [])].map((w) => {
    const a = averages.get(w.sport);
    return [
      <span className={w.sport === "all" ? "font-semibold" : ""}>{sportLabel(w.sport)}</span>,
      fmtLoad(w.load),
      a ? fmtLoad(a.load) : "–",
      fmtDuration(w.duration_s),
      a ? fmtDuration(a.duration_s) : "–",
      fmtKm(w.distance_m),
      a ? fmtKm(a.distance_m) : "–",
      w.n_activities,
    ];
  });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Tento týždeň vs. priemer 4 predchádzajúcich" right={<span className="text-xs text-muted">od {fmtDate(weekStart)}</span>}>
        <Table head={["Šport", "Záťaž", "Ø 4 t", "Čas", "Ø 4 t", "km", "Ø 4 t", "Akt."]} align={["left", "right", "right", "right", "right", "right", "right", "right"]} rows={rows} />
      </Card>
      <Card
        title={`${spec.label} (${spec.unit})`}
        right={<Segmented label="Metrika" value={metric} onChange={setMetric} options={METRICS.map(({ value, label }) => ({ value, label }))} />}
      >
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data} margin={{ top: 18, right: 4, bottom: 0, left: -16 }} barGap={4}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="sport" {...AXIS} />
            <YAxis {...AXIS} width={44} tickFormatter={(v: number) => fmtNum(v)} />
            <Tooltip {...tooltipStyle()} formatter={(v: number, name: string) => [fmtNum(v, metric === "load" ? 0 : 1), name]} />
            <Legend {...legendStyle} />
            <Bar dataKey="now" name="Tento týždeň" fill="var(--accent)" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              <LabelList dataKey="now" position="top" formatter={(v: number) => fmtNum(v, metric === "load" ? 0 : 1)} fontSize={11} fill="var(--text)" />
            </Bar>
            <Bar dataKey="avg" name="Ø 4 predch. týždne" fill="var(--neutral)" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              <LabelList dataKey="avg" position="top" formatter={(v: number) => fmtNum(v, metric === "load" ? 0 : 1)} fontSize={11} fill="var(--muted)" />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
}
