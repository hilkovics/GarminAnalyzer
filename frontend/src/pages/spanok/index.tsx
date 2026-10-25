// Spánok: readiness today, sleep stages, sleep score and RHR with baselines, sleep debt, Body Battery, findings.
import { useState } from "react";

import { useApi, type Schemas } from "@/api/client";
import { Card, Notice, PageHeader, QueryState, Segmented } from "@/components/ui";
import { fmtDate, fmtDuration, fmtNum, isoDate } from "@/lib/format";

import { Findings } from "./Findings";
import { Readiness } from "./Readiness";
import { BaselineChart, RecoveryChart, SleepDebtChart, SleepStagesChart } from "./SleepCharts";

const RANGES = [
  { value: 30, label: "30 dní" },
  { value: 90, label: "90 dní" },
  { value: 180, label: "180 dní" },
];

type Day = Schemas["WellnessDayDTO"];

/** The latest night with a value: last point of the series, no computation. */
function latest(days: Day[], field: "sleep_s" | "sleep_score" | "rhr"): Day | undefined {
  return [...days].reverse().find((d) => d[field] !== null);
}

function Charts({ days }: { days: Day[] }) {
  const night = latest(days, "sleep_s");
  const score = latest(days, "sleep_score");
  const rhr = latest(days, "rhr");
  const debt = [...days].reverse().find((d) => d.sleep_debt_7_s !== null);
  if (!days.length) return <Notice>Zatiaľ žiadne wellness dáta v tomto rozsahu. Spusti sync v Nastaveniach.</Notice>;
  return (
    <>
      <Card title="Dĺžka a fázy spánku" right={<span className="text-xs text-muted">Os Y: spánok (h){night ? ` · posledná noc ${fmtDuration(night.sleep_s)} h` : ""}</span>}>
        <SleepStagesChart days={days} />
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Skóre spánku"
          right={score && <span className="num text-xs text-muted"><b className="text-base text-text">{fmtNum(score.sleep_score, 0)}</b> · medián {fmtNum(score.baselines.sleep_score.median, 0)}</span>}
        >
          <BaselineChart days={days} field="sleep_score" name="Skóre spánku" unit="skóre" color="var(--run)" />
          <p className="mt-2 text-xs text-muted">Prerušovaná čiara = 28-dňový medián, pás = ± MAD (medián absolútnych odchýlok).</p>
        </Card>
        <Card
          title="Pokojový tep"
          right={rhr && <span className="num text-xs text-muted"><b className="text-base text-text">{fmtNum(rhr.rhr, 0)}</b> bpm · medián {fmtNum(rhr.baselines.rhr.median, 0)}</span>}
        >
          <BaselineChart days={days} field="rhr" name="Pokojový tep" unit="bpm" color="var(--bike)" />
          <p className="mt-2 text-xs text-muted">Prerušovaná čiara = 28-dňový medián, pás = ± MAD.</p>
        </Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Spánkový dlh (7 nocí)" right={debt && <span className="num text-xs text-muted">posledná noc {fmtDuration(Math.abs(debt.sleep_debt_7_s ?? 0))} h {(debt.sleep_debt_7_s ?? 0) < 0 ? "prebytok" : "dlh"}</span>}>
          <SleepDebtChart days={days} />
          <p className="mt-2 text-xs text-muted">Súčet rozdielov oproti max(8 h, medián 28 dní) za 7 nocí; záporná hodnota = prebytok spánku.</p>
        </Card>
        <Card title="Body Battery a stres">
          <RecoveryChart days={days} />
          <p className="mt-2 text-xs text-muted">Body Battery po prebudení a priemerný stres dňa (Garmin, 0–100).</p>
        </Card>
      </div>
    </>
  );
}

export default function Page() {
  const [days, setDays] = useState(90);
  const to = new Date();
  const from = new Date(to.getFullYear(), to.getMonth(), to.getDate() - (days - 1));
  const wellness = useApi<Schemas["WellnessDTO"]>("/wellness/daily", { from: isoDate(from), to: isoDate(to) }, { keepPrevious: true });
  return (
    <>
      <PageHeader
        title="Spánok"
        subtitle={wellness.data?.days.length ? `${fmtDate(wellness.data.date_from)} – ${fmtDate(wellness.data.date_to)}` : undefined}
        right={<Segmented label="Rozsah" value={days} onChange={setDays} options={RANGES} />}
      />
      <div className="flex flex-col gap-4">
        <Readiness />
        <QueryState query={wellness}>{(w) => <Charts days={w.days} />}</QueryState>
        <Findings />
      </div>
    </>
  );
}
