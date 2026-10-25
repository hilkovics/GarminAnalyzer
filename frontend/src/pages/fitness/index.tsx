// Fitness: PMC with the warming-up band, the load flags of the latest day and weekly bars per sport.
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useApi, type Schemas } from "@/api/client";
import { AXIS, Empty, GRID, legendStyle, PmcChart, tooltipStyle } from "@/components/charts";
import { Badge, Card, Notice, PageHeader, QueryState, Segmented, Stat } from "@/components/ui";
import { fmtDate, fmtDayMonth, fmtNum, fmtSigned, isoDate, sportLabel } from "@/lib/format";
import { acwrBadge, SPORT_COLORS } from "@/lib/labels";

const RANGES = [
  { value: 90, label: "90 dní" },
  { value: 180, label: "180 dní" },
  { value: 365, label: "1 rok" },
  { value: 0, label: "Všetko" },
];
const WEEKS = [
  { value: 12, label: "12 t" },
  { value: 24, label: "24 t" },
  { value: 52, label: "52 t" },
];
type Metric = "load" | "duration_s" | "distance_m";
const METRICS: { value: Metric; label: string; unit: string; scale: number }[] = [
  { value: "load", label: "Záťaž", unit: "TSS-ekv.", scale: 1 },
  { value: "duration_s", label: "Čas", unit: "h", scale: 1 / 3600 },
  { value: "distance_m", label: "Vzdialenosť", unit: "km", scale: 1 / 1000 },
];
const SPORT_ORDER = ["run", "bike", "other"];

function Flags({ latest }: { latest: Schemas["PmcPointDTO"] }) {
  const acwr = acwrBadge(latest.acwr_band);
  return (
    <Card title={`Posledný bod série: ${fmtDate(latest.date)}`}>
      <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
        <Stat label="ACWR" value={fmtNum(latest.acwr, 2)} badge={latest.acwr_band ? <Badge tone={acwr.tone}>{acwr.text}</Badge> : undefined} hint="Pomer akútnej (7 d) a chronickej (28 d) záťaže." />
        <Stat label="Monotónnosť" value={fmtNum(latest.monotony, 2)} hint="Priemer / smerodajná odchýlka záťaže za 7 dní." />
        <Stat label="Strain" value={fmtNum(latest.strain, 0)} hint="Súčet záťaže za 7 dní krát monotónnosť." />
        <Stat label="Nárast CTL / týždeň" value={fmtSigned(latest.ramp_rate)} />
      </div>
      {latest.ramp_warning && <div className="mt-3"><Notice tone="yellow">CTL rastie rýchlejšie ako 6 bodov za týždeň – pozor na preťaženie.</Notice></div>}
      {latest.warming_up && <p className="mt-3 text-xs text-muted">Séria je ešte v prvých 90 dňoch – hodnoty sa zahrievajú a nie sú spoľahlivé.</p>}
    </Card>
  );
}

function WeeklyBars({ weeks, metric }: { weeks: Schemas["WeeklyDTO"][]; metric: Metric }) {
  const spec = METRICS.find((m) => m.value === metric)!;
  const rows = weeks.filter((w) => w.sport !== "all");
  if (!rows.length) return <Empty text="Zatiaľ žiadne týždenné dáta." height={320} />;
  const sports = [...SPORT_ORDER.filter((s) => rows.some((w) => w.sport === s)), ...[...new Set(rows.map((w) => w.sport))].filter((s) => !SPORT_ORDER.includes(s))];
  const byWeek = new Map<string, Record<string, number | string>>();
  for (const w of rows) {
    const entry = byWeek.get(w.week_start) ?? { week: w.week_start, iso: `T${w.iso_week}/${w.iso_year}` };
    entry[w.sport] = w[metric] * spec.scale;
    byWeek.set(w.week_start, entry);
  }
  const data = [...byWeek.values()].sort((a, b) => String(a.week).localeCompare(String(b.week)));
  return (
    <ResponsiveContainer width="100%" height={320}>
      <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: -12 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="week" tickFormatter={fmtDayMonth} minTickGap={20} {...AXIS} />
        <YAxis {...AXIS} width={44} tickFormatter={(v: number) => fmtNum(v)} />
        <Tooltip {...tooltipStyle()} labelFormatter={(_: string, p) => String(p?.[0]?.payload?.iso ?? "")} formatter={(v: number, name: string) => [`${fmtNum(v, 1)} ${spec.unit}`, name]} />
        <Legend {...legendStyle} />
        {sports.map((s) => (
          <Bar key={s} dataKey={s} name={sportLabel(s)} stackId="w" fill={SPORT_COLORS[s] ?? "var(--neutral)"} isAnimationActive={false} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export default function FitnessPage() {
  const [days, setDays] = useState(365);
  const [weeks, setWeeks] = useState(12);
  const [metric, setMetric] = useState<Metric>("load");
  const today = new Date();
  const from = days ? new Date(today.getFullYear(), today.getMonth(), today.getDate() - days + 1) : null;
  const pmc = useApi<Schemas["PmcDTO"]>("/fitness/pmc", { from: from ? isoDate(from) : null }, { keepPrevious: true });
  const weekly = useApi<Schemas["WeeklyDTO"][]>("/fitness/weekly", { weeks }, { keepPrevious: true });
  const spec = METRICS.find((m) => m.value === metric)!;
  return (
    <>
      <PageHeader title="Fitness" right={<Segmented label="Rozsah PMC" value={days} onChange={setDays} options={RANGES} />} />
      <div className="flex flex-col gap-4">
        <QueryState query={pmc}>
          {(p) => (
            <>
              {p.latest ? <Flags latest={p.latest} /> : <Notice>Zatiaľ žiadne metriky. Spusti sync v Nastaveniach.</Notice>}
              <Card title="Výkonnostný manažment (PMC)" right={<span className="text-xs text-muted">Os Y: TSS-ekvivalent</span>}>
                <PmcChart pmc={p} height={360} />
                {p.warming_up_until && <p className="mt-2 text-xs text-muted">Sivé pásmo = zahrievanie do {fmtDate(p.warming_up_until)} (prvých 90 dní série).</p>}
              </Card>
            </>
          )}
        </QueryState>
        <Card
          title={`${spec.label} po týždňoch (${spec.unit})`}
          right={
            <div className="flex flex-wrap gap-2">
              <Segmented label="Metrika" value={metric} onChange={setMetric} options={METRICS.map(({ value, label }) => ({ value, label }))} />
              <Segmented label="Týždne" value={weeks} onChange={setWeeks} options={WEEKS} />
            </div>
          }
        >
          <QueryState query={weekly}>{(w) => <WeeklyBars weeks={w} metric={metric} />}</QueryState>
        </Card>
      </div>
    </>
  );
}

