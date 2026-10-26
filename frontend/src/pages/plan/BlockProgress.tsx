// Coach "Kondícia" block progress (METRICS §11.4): baseline vs now, weekly running time, check runs, summary.
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useApi, type Schemas } from "@/api/client";
import { AXIS, GRID, legendStyle, tooltipStyle } from "@/components/charts";
import { Badge, Card, QueryState, Stat, Table, cx } from "@/components/ui";
import { DASH, fmtDate, fmtDayMonth, fmtDuration, fmtHours, fmtKm, fmtNum, fmtPace, fmtPaceS, fmtPct, fmtTimeHms, MINUS, valid } from "@/lib/format";

type Block = Schemas["BlockProgressDTO"];
type Snapshot = Schemas["FitnessSnapshotDTO"];
type Num = number | null | undefined;

/** A signed difference with the better direction in green and the worse one in red. */
function Delta({ value, text, betterWhen }: { value: Num; text: string; betterWhen: "up" | "down" }) {
  if (!valid(value) || Math.abs(value) < 1e-9) return <span className="text-muted">{valid(value) ? "bez zmeny" : DASH}</span>;
  const better = betterWhen === "up" ? value > 0 : value < 0;
  return (
    <span className={cx("num font-semibold", better ? "text-good" : "text-bad")}>
      {text} <span className="sr-only">{better ? "(lepšie)" : "(horšie)"}</span>
    </span>
  );
}

const signedSeconds = (s: number) => `${s < 0 ? MINUS : "+"}${fmtPaceS(Math.abs(s))}`;

/** Pace difference in s/km (negative = faster) from two speeds. */
function paceDelta(now: Num, base: Num): number | null {
  return valid(now) && valid(base) && now > 0 && base > 0 ? 1000 / now - 1000 / base : null;
}

type Change = Schemas["FitnessChangeDTO"];

/** Rows of "start vs now"; the change comes from the API (value − baseline, §11.4) and is only formatted
 * here: pace as s/km, EF as a percentage of the baseline EF. */
const ROWS: { label: string; short: string; hint: string; show: (s: Snapshot) => string; delta: (c: Change, now: Snapshot, base: Snapshot) => JSX.Element }[] = [
  {
    label: "Tempo pri referenčnom tepe",
    short: "Tempo pri ref. tepe",
    hint: "80 % LTHR, medián 28 dní",
    show: (s) => fmtPace(s.pace_at_ref_hr),
    delta: (c, n, b) => {
      const d = valid(c.pace_at_ref_hr) ? paceDelta(n.pace_at_ref_hr, b.pace_at_ref_hr) : null;
      return <Delta value={d} text={valid(d) ? `${signedSeconds(d)}/km` : ""} betterWhen="down" />;
    },
  },
  {
    label: "Efektivita (EF)",
    short: "EF",
    hint: "steady-state behy, medián 28 dní",
    show: (s) => fmtNum(s.ef, 2),
    delta: (c, _n, b) => {
      const d = valid(c.ef) && valid(b.ef) && b.ef > 0 ? c.ef / b.ef : null;
      return <Delta value={d} text={valid(d) ? `${d > 0 ? "+" : MINUS}${fmtPct(Math.abs(d), 1)}` : ""} betterWhen="up" />;
    },
  },
  {
    label: "Odhad 5 km",
    short: "5 km",
    hint: "Daniels z najlepšieho výkonu",
    show: (s) => fmtTimeHms(s.t5k_s),
    delta: (c) => <Delta value={c.t5k_s} text={valid(c.t5k_s) ? signedSeconds(c.t5k_s) : ""} betterWhen="down" />,
  },
  {
    label: "Odhad 10 km",
    short: "10 km",
    hint: "Daniels z najlepšieho výkonu",
    show: (s) => fmtTimeHms(s.t10k_s),
    delta: (c) => <Delta value={c.t10k_s} text={valid(c.t10k_s) ? signedSeconds(c.t10k_s) : ""} betterWhen="down" />,
  },
];

const NO_CHANGE: Change = { pace_at_ref_hr: null, ef: null, vdot: null, t5k_s: null, t10k_s: null };
const STALE_TITLE = "Odhad vychádza z výkonu staršieho ako 60 dní – zaraď tempový úsek alebo kontrolný beh.";

function Indicators({ block }: { block: Block }) {
  const last = block.weeks.at(-1);
  const now = last?.value ?? block.baseline;
  const change = last?.change ?? NO_CHANGE;
  const time = (s: Snapshot, row: (typeof ROWS)[number]) =>
    s.stale && row.label.startsWith("Odhad") ? (
      <span title={STALE_TITLE}>
        {row.show(s)} <span className="text-warn">*</span>
      </span>
    ) : (
      row.show(s)
    );
  return (
    <>
      <Table
        head={["Ukazovateľ", "Začiatok", "Teraz", "Zmena"]}
        align={["left", "right", "right", "right"]}
        rows={ROWS.map((r) => [
          <span className="font-sans">
            <span className="sm:hidden">{r.short}</span>
            <span className="hidden sm:inline">{r.label}</span>
            <span className="hidden text-xs text-muted sm:block">{r.hint}</span>
          </span>,
          time(block.baseline, r),
          time(now, r),
          r.delta(change, now, block.baseline),
        ])}
      />
      {(now.stale || block.baseline.stale) && <p className="mt-1 text-xs text-warn">* {STALE_TITLE}</p>}
    </>
  );
}

function WeeksChart({ block }: { block: Block }) {
  const data = block.weeks.map((w) => ({
    label: `${w.week_no}`,
    full: `Týždeň ${w.week_no} (od ${fmtDayMonth(w.monday)})`,
    target: Math.round(w.target_s / 60),
    done: Math.round(w.run_s / 60),
  }));
  return (
    <div role="img" aria-label="Čas behu po týždňoch bloku: cieľ a skutočnosť v minútach. Hodnoty sú v tabuľke nižšie.">
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: -16 }} barGap={2}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="label" interval={0} {...AXIS} tick={{ fontSize: 11 }} />
          <YAxis {...AXIS} width={44} tickFormatter={(v: number) => fmtNum(v)} />
          <Tooltip {...tooltipStyle()} labelFormatter={(_l, p) => p?.[0]?.payload?.full ?? _l} formatter={(v: number, name: string) => [`${fmtNum(v)} min`, name]} />
          <Legend {...legendStyle} />
          <Bar dataKey="target" name="Cieľ (min)" fill="var(--neutral)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="done" name="Odbehnuté (min)" fill="var(--accent)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function WeeksTable({ block }: { block: Block }) {
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-muted hover:text-text">Tabuľka týždňov</summary>
      <div className="mt-2">
        <Table
          head={["Týždeň", "Cieľ", "Odbehnuté", "Menu", "Pripravenosť", "Spánok", "Odhad 5 km"]}
          align={["left", "right", "right", "right", "right", "right", "right"]}
          rows={block.weeks.map((w) => [
            <span className="font-sans">
              {w.week_no} · {fmtDayMonth(w.monday)}
              {w.recovery && <span className="ml-1 text-xs text-muted">odľahčený</span>}
              {w.test && <span className="ml-1 text-xs text-muted">test</span>}
              {w.brake && <span className="ml-1 text-xs text-warn">brzda</span>}
            </span>,
            fmtDuration(w.target_s),
            fmtDuration(w.run_s),
            `${w.items_done}/3`,
            fmtNum(w.mean_readiness),
            fmtHours(w.mean_sleep_s),
            fmtTimeHms(w.value.t5k_s),
          ])}
        />
      </div>
    </details>
  );
}

function CheckRuns({ block }: { block: Block }) {
  if (!block.check_runs.length) {
    return <p className="text-sm text-muted">Kontrolný beh je v 6. a 12. týždni bloku (30 min naplno). Výsledok sa zobrazí, keď ho označíš ako hotový.</p>;
  }
  return (
    <Table
      head={["Dátum", "Za 30 min", "Tempo", "Priem. tep", "Odhad 5 km", "Odhad 10 km"]}
      align={["left", "right", "right", "right", "right", "right"]}
      rows={block.check_runs.map((c) => [fmtDate(c.date), fmtKm(c.distance_m, 2), fmtPace(c.distance_m / 1800), fmtNum(c.avg_hr), fmtTimeHms(c.t5k_s), fmtTimeHms(c.t10k_s)])}
    />
  );
}

function Summary({ block }: { block: Block }) {
  const s = block.summary;
  const tile = "rounded-lg border border-line bg-card-2 p-3";
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <div className={tile}>
        <Stat label="Tréningy z menu" value={`${s.items_done}/${s.items_planned}`} />
      </div>
      <div className={tile}>
        <Stat label="Čas behu" value={s.target_s > 0 ? fmtPct(s.run_s / s.target_s) : DASH} unit="cieľa" />
      </div>
      <div className={tile}>
        <Stat label="Týždne s brzdou" value={`${s.brake_weeks}`} />
      </div>
      <div className={tile}>
        <Stat label="Priemerný spánok" value={fmtHours(s.mean_sleep_s)} />
      </div>
      <div className={tile}>
        <Stat label="Priem. pripravenosť" value={fmtNum(s.mean_readiness)} />
      </div>
      <div className={tile}>
        <Stat label="Zelené dni" value={fmtPct(s.green_share)} />
      </div>
    </div>
  );
}

export function BlockProgressCard({ block, picker }: { block: Block; picker?: JSX.Element }) {
  const final = block.summary.final;
  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          Blok {fmtDayMonth(block.start)} – {fmtDate(block.end)}
          <Badge tone={final ? "green" : "blue"}>{final ? "ukončený" : `týždeň ${block.weeks.length}/${block.block_weeks}`}</Badge>
        </span>
      }
      right={picker}
    >
      <div className="flex min-w-0 flex-col gap-4 [&>section]:min-w-0">
        <section>
          <h3 className="label mb-2">{final ? "Súhrn bloku" : "Zatiaľ v bloku"}</h3>
          <Summary block={block} />
        </section>
        <section>
          <h3 className="label">Kondícia oproti začiatku bloku</h3>
          <p className="mb-1 text-xs text-muted">
            Začiatok = {fmtDate(block.baseline.day)}, teraz = {block.weeks.length ? `týždeň ${block.weeks.at(-1)?.week_no}` : "začiatok"}. Zelená = zlepšenie.
          </p>
          <Indicators block={block} />
        </section>
        <section className="flex flex-col gap-2">
          <h3 className="label">Čas behu po týždňoch</h3>
          <WeeksChart block={block} />
          <WeeksTable block={block} />
        </section>
        <section>
          <h3 className="label mb-1">Kontrolné behy</h3>
          <CheckRuns block={block} />
        </section>
      </div>
    </Card>
  );
}

/** The block card with its own data: the current block, or an older one picked in the select. */
export function BlockSection({ withPicker = false }: { withPicker?: boolean }) {
  const [start, setStart] = useState<string | undefined>(undefined);
  const block = useApi<Block | null>("/plan/block", { start }, { keepPrevious: true });
  const blocks = useApi<Schemas["BlockRefDTO"][]>("/plan/blocks", undefined, { enabled: withPicker });
  const picker =
    withPicker && (blocks.data?.length ?? 0) > 1 ? (
      <select
        aria-label="Blok"
        className="rounded-lg border border-line-strong bg-card-2 px-2 py-1 text-sm"
        value={start ?? ""}
        onChange={(e) => setStart(e.target.value || undefined)}
      >
        <option value="">Aktuálny blok</option>
        {blocks.data?.map((b) => (
          <option key={b.start} value={b.start}>
            {fmtDate(b.start)} – {fmtDate(b.end)}
          </option>
        ))}
      </select>
    ) : undefined;
  return <QueryState query={block}>{(b) => (b ? <BlockProgressCard block={b} picker={picker} /> : null)}</QueryState>;
}
