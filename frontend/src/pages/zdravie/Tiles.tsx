// Trend tiles (METRICS §12.2): 7-day mean vs the personal normal, the 28-day change and the monthly means.
import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";

import type { Schemas } from "@/api/client";
import { cx } from "@/components/ui";
import { fmtPctSigned } from "@/lib/format";

import { fmtMetric, fmtMetricDiff } from "./format";

type Metric = Schemas["HealthMetricDTO"];

const DIRECTION: Record<string, { cls: string; word: string }> = {
  better: { cls: "text-good", word: "lepšie" },
  worse: { cls: "text-bad", word: "horšie" },
};

function ChangeLine({ m }: { m: Metric }) {
  const c = m.change;
  if (c.diff === null || c.diff === undefined) return <span className="text-xs text-muted">zmena: málo dát</span>;
  const Icon = c.diff > 0 ? ArrowUpRight : c.diff < 0 ? ArrowDownRight : ArrowRight;
  const tone = c.notable ? DIRECTION[c.direction ?? ""] : undefined;
  return (
    <span className={cx("num flex flex-wrap items-center gap-x-1 text-xs", tone?.cls ?? "text-muted")}>
      <Icon size={13} aria-hidden />
      <span className="whitespace-nowrap">{fmtMetricDiff(c.diff, m.unit)}</span>
      <span className="whitespace-nowrap">({fmtPctSigned(c.pct)})</span>
      <span className={cx("font-sans", !c.notable && "hidden sm:inline")}>
        {c.notable ? (tone ? `· ${tone.word}` : "· výrazná zmena") : "· v rámci bežného"}
      </span>
    </span>
  );
}

function Spark({ m }: { m: Metric }) {
  if (m.monthly.length < 2) return <div className="h-8" />;
  return (
    <div className="h-8" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={m.monthly} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
          <YAxis hide domain={["dataMin", "dataMax"]} />
          <Line dataKey="value" stroke="var(--neutral)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Tiles({ metrics, selected, onToggle }: { metrics: Metric[]; selected: string[]; onToggle: (key: string) => void }) {
  return (
    <ul className="grid grid-cols-2 gap-2 lg:grid-cols-3 xl:grid-cols-4" aria-label="Ukazovatele zdravia">
      {metrics.map((m) => {
        const on = selected.includes(m.key);
        return (
          <li key={m.key}>
            <button
              type="button"
              aria-pressed={on}
              onClick={() => onToggle(m.key)}
              className={cx(
                "flex h-full w-full flex-col gap-1 rounded-lg border p-2.5 text-left transition-colors sm:p-3",
                on ? "border-accent bg-accent/10 ring-1 ring-accent" : "border-line bg-card-2 hover:border-line-strong",
              )}
            >
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted sm:text-xs">{m.label}</span>
              <span className="num text-lg font-semibold sm:text-xl">{fmtMetric(m.mean7 ?? m.latest, m.unit)}</span>
              <span className="num text-xs text-muted">
                7 dní · normál {fmtMetric(m.median28, m.unit)}
              </span>
              <ChangeLine m={m} />
              <Spark m={m} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
