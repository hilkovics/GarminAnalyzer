// Charts of the Kokpit design (Recharts / SVG). Colours are CSS variables, so both themes work.
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Schemas } from "@/api/client";
import { fmtDate, fmtDayMonth, fmtNum } from "@/lib/format";
import { expandSteps, repeatSpans, STEP_LABELS, ZONE_COLORS } from "@/lib/labels";

export const AXIS = { stroke: "var(--border-strong)", tickLine: false, axisLine: false } as const;
export const GRID = { stroke: "var(--grid)", strokeDasharray: "0", vertical: false } as const;

export function tooltipStyle() {
  return {
    contentStyle: { background: "var(--card)", border: "1px solid var(--border-strong)", borderRadius: 8, fontSize: 12 },
    labelStyle: { color: "var(--muted)", marginBottom: 4 },
    itemStyle: { padding: 0 },
    cursor: { fill: "var(--grid)", opacity: 0.5 },
  };
}

export const legendStyle = { wrapperStyle: { fontSize: 12, color: "var(--muted)" }, iconSize: 10 } as const;

export function Empty({ text, height = 200 }: { text: string; height?: number }) {
  return (
    <div className="flex items-center justify-center text-sm text-muted" style={{ height }}>
      {text}
    </div>
  );
}

/** CTL / ATL / TSB lines over daily-load bars (one axis, METRICS §4); grey band = warming-up period. */
export function PmcChart({ pmc, height = 320, compact = false }: { pmc: Schemas["PmcDTO"]; height?: number; compact?: boolean }) {
  if (!pmc.points.length) return <Empty text="Zatiaľ žiadne dáta." height={height} />;
  const data = pmc.points.map((p) => ({ ...p }));
  const warm = pmc.warming_up_until ? data.filter((p) => p.warming_up) : [];
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
        <CartesianGrid {...GRID} />
        {warm.length > 0 && <ReferenceArea x1={warm[0].date} x2={warm[warm.length - 1].date} fill="var(--grid)" fillOpacity={0.6} ifOverflow="visible" />}
        <XAxis dataKey="date" tickFormatter={fmtDayMonth} minTickGap={28} {...AXIS} />
        <YAxis {...AXIS} width={44} tickFormatter={(v: number) => fmtNum(v)} />
        <ReferenceLine y={0} stroke="var(--dim)" strokeDasharray="2 3" />
        <Tooltip {...tooltipStyle()} labelFormatter={(d: string) => fmtDate(d)} formatter={(v: number, name: string) => [fmtNum(v, name === "Denná záťaž" ? 0 : 1), name]} />
        {!compact && <Legend {...legendStyle} />}
        <Bar dataKey="load_total" name="Denná záťaž" fill="var(--neutral)" fillOpacity={0.55} isAnimationActive={false} />
        <Line dataKey="ctl" name="CTL" stroke="var(--run)" strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line dataKey="atl" name="ATL" stroke="var(--bike)" strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line dataKey="tsb" name="TSB" stroke="var(--green)" strokeWidth={2} dot={false} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

const BAND_COLORS: Record<string, string> = { green: "var(--green)", yellow: "var(--yellow)", red: "var(--red)" };

/** 0–100 half-circle with the three §8 bands (thin outer ring); the number is the score truncated to an integer. */
export function ReadinessGauge({ score, band, size = 220 }: { score: number | null | undefined; band?: string | null; size?: number }) {
  const arc = (r: number, from: number, to: number) => {
    const p = (v: number) => {
      const a = Math.PI * (1 - v / 100);
      return `${(100 + r * Math.cos(a)).toFixed(2)} ${(100 - r * Math.sin(a)).toFixed(2)}`;
    };
    return `M ${p(from)} A ${r} ${r} 0 0 1 ${p(to)}`;
  };
  const value = score === null || score === undefined ? null : Math.max(0, Math.min(100, score));
  return (
    <svg viewBox="0 0 200 112" width="100%" style={{ maxWidth: size }} role="img" aria-label={value === null ? "Pripravenosť neznáma" : `Pripravenosť ${Math.floor(value)}`}>
      <path d={arc(88, 0, 45)} stroke="var(--red)" strokeWidth={3} fill="none" />
      <path d={arc(88, 45, 70)} stroke="var(--yellow)" strokeWidth={3} fill="none" />
      <path d={arc(88, 70, 100)} stroke="var(--green)" strokeWidth={3} fill="none" />
      <path d={arc(74, 0, 100)} stroke="var(--border)" strokeWidth={16} fill="none" />
      {value !== null && value > 0.5 && <path d={arc(74, 0, value)} stroke={BAND_COLORS[band ?? ""] ?? "var(--muted)"} strokeWidth={16} fill="none" />}
      <text x="100" y="104" textAnchor="middle" className="num" fontSize="50" fontWeight="700" fill="var(--text)">
        {value === null ? "–" : Math.floor(value)}
      </text>
    </svg>
  );
}

/** Workout profile: bars along time (width = duration, height and colour = zone), "2×" brackets on repeats. */
export function WorkoutProfile({ steps, height = 96, axis = true }: { steps: Schemas["WorkoutStepDTO"][]; height?: number; axis?: boolean }) {
  const played = expandSteps(steps);
  const total = played.length ? played[played.length - 1].end : 0;
  if (!total) return null;
  const spans = repeatSpans(steps);
  const pct = (t: number) => `${(t / total) * 100}%`;
  const ends = played.map((p) => p.end);
  const ticks = [0, ...ends].filter((t, i, all) => i === 0 || t === total || (t - all[i - 1] >= total * 0.08 && total - t >= total * 0.08));
  return (
    <div className="w-full select-none" role="img" aria-label="Profil tréningu">
      {spans.length > 0 && (
        <div className="relative h-5">
          {spans.map((s, i) => (
            <div key={i} className="absolute top-2 h-2.5 border-x border-t border-muted" style={{ left: pct(s.start), width: pct(s.end - s.start) }}>
              <span className="num absolute -top-2.5 left-1/2 -translate-x-1/2 bg-card px-1 text-xs font-bold">{s.count}×</span>
            </div>
          ))}
        </div>
      )}
      <div className="relative" style={{ height }}>
        {played.map(({ step, start, end }, i) => {
          const zone = Math.min(Math.max(step.zone, 1), 5);
          return (
            <div
              key={i}
              title={`${STEP_LABELS[step.type] ?? step.type} · ${fmtNum((end - start) / 60, 0)} min · Z${step.zone}`}
              className="absolute bottom-0 rounded-[2px]"
              style={{ left: `calc(${pct(start)} + 1px)`, width: `calc(${pct(end - start)} - 2px)`, height: `${25 + 15 * zone}%`, background: ZONE_COLORS[zone] }}
            />
          );
        })}
      </div>
      {axis && (
        <div className="relative mt-1 h-4 text-[11px] text-muted">
          {ticks.map((t) => (
            <span key={t} className="num absolute whitespace-nowrap" style={{ left: pct(t), transform: t === 0 ? "none" : t === total ? "translateX(-100%)" : "translateX(-50%)" }}>
              {t === total ? `${fmtNum(t / 60)} min` : fmtNum(t / 60)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
