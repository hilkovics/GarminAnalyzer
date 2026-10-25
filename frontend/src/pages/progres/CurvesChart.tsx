// Speed–HR curves (METRICS §6.1): one line per month snapshot, x = HR bin, y = GAP pace (faster on top).
import { CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { Schemas } from "@/api/client";
import { AXIS, Empty, GRID, legendStyle, tooltipStyle } from "@/components/charts";
import { fmtNum, fmtPace } from "@/lib/format";

import { paceAxis, paceS } from "./axes";

type Curve = Schemas["CurveDTO"];

/** Oldest month palest, newest darkest and thickest (one hue, so both themes work). */
export function monthStyle(index: number, count: number): { opacity: number; width: number } {
  if (count <= 1) return { opacity: 1, width: 3 };
  const share = index / (count - 1);
  return { opacity: 0.3 + 0.7 * share, width: index === count - 1 ? 3.5 : 2 };
}

/** HR axis ticks every 10 bpm (5 bpm for a narrow range). */
export function hrTicks(lo: number, hi: number): number[] {
  const step = hi - lo > 40 ? 10 : 5;
  const out: number[] = [];
  for (let t = Math.floor(lo / step) * step; t <= hi + step - 1; t += step) out.push(t);
  return out;
}

export function CurvesChart({ curves, height = 340 }: { curves: Curve[]; height?: number }) {
  const drawn = curves.filter((c) => c.bins.length);
  if (!drawn.length) return <Empty text="Zatiaľ žiadna krivka rýchlosť–tep (potrebné ≥ 10 minút v tepovom pásme)." height={height} />;
  const rows = drawn.map((c) => c.bins.map((b) => ({ hr: b.hr_bin, y: paceS(b.gap_speed), speed: b.gap_speed, n: b.count })));
  const axis = paceAxis(rows.flat().map((r) => r.y));
  const hrs = rows.flat().map((r) => r.hr);
  const ref = drawn[drawn.length - 1].ref_hr;
  const lo = Math.min(...hrs, ...(ref != null ? [ref] : []));
  const hi = Math.max(...hrs, ...(ref != null ? [ref] : []));
  return (
    <div role="img" aria-label={`Krivky rýchlosť–tep za ${drawn.length} mesiacov (${drawn.map((c) => c.month).join(", ")})`}>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart margin={{ top: 22, right: 16, bottom: 0, left: -12 }}>
          <CartesianGrid {...GRID} />
          <XAxis type="number" dataKey="hr" domain={[Math.floor(lo / 5) * 5, Math.ceil(hi / 5) * 5]} ticks={hrTicks(lo, hi)} allowDecimals={false} {...AXIS} />
          <YAxis type="number" dataKey="y" width={48} {...AXIS} {...axis} />
          <Tooltip
            {...tooltipStyle()}
            cursor={{ stroke: "var(--border-strong)" }}
            labelFormatter={(hr: number) => `${fmtNum(hr)} bpm`}
            formatter={(_: number, name: string, item) => [`${fmtPace(item.payload.speed)} (n = ${item.payload.n})`, name]}
          />
          <Legend {...legendStyle} />
          {ref != null && <ReferenceLine x={ref} stroke="var(--muted)" strokeDasharray="2 3" label={{ value: `ref. tep ${fmtNum(ref)}`, position: "top", fill: "var(--muted)", fontSize: 11 }} />}
          {drawn.map((c, i) => {
            const style = monthStyle(i, drawn.length);
            return (
              <Line
                key={c.month}
                name={c.month}
                data={rows[i]}
                dataKey="y"
                stroke="var(--run)"
                strokeOpacity={style.opacity}
                strokeWidth={style.width}
                dot={{ r: i === drawn.length - 1 ? 3 : 2, fill: "var(--run)", fillOpacity: style.opacity, strokeWidth: 0 }}
                isAnimationActive={false}
              />
            );
          })}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
