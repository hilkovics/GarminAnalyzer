// Progres: EF, decoupling, speed–HR curves, pace at reference HR, best efforts, predictions and threshold proposals.
import { useState, type ReactNode } from "react";

import { useApi, type Schemas } from "@/api/client";
import { Card, Notice, PageHeader, QueryState, Segmented } from "@/components/ui";
import { fmtNum, fmtPace } from "@/lib/format";

import { BlockSection } from "@/pages/plan/BlockProgress";

import { CurvesChart } from "./CurvesChart";
import { EffortsTable, HrEfforts, SpeedEfforts } from "./Efforts";
import { DECOUPLING_KIND, EF_KIND, latestTrend, PACE_REF_KIND, SeriesChart } from "./SeriesChart";
import { Predictions, Proposals } from "./Tables";

const SPORTS = [
  { value: "run", label: "Beh" },
  { value: "bike", label: "Bicykel" },
];
const RANGES = [
  { value: 90, label: "90 dní" },
  { value: 180, label: "180 dní" },
  { value: 365, label: "1 rok" },
  { value: 730, label: "2 roky" },
];

const Median = ({ children }: { children: string }) => (
  <div className="text-right">
    <span className="num text-xl font-semibold">{children}</span> <span className="text-xs text-muted">medián 28 d</span>
  </div>
);

function SeriesCard({
  title,
  caption,
  note,
  query,
  kind,
  summary,
}: {
  title: string;
  caption?: string;
  note?: (s: Schemas["SeriesDTO"]) => ReactNode;
  query: ReturnType<typeof useApi<Schemas["SeriesDTO"]>>;
  kind: Parameters<typeof SeriesChart>[0]["kind"];
  summary: (latest: number) => string;
}) {
  const latest = latestTrend(query.data);
  return (
    <Card title={title} right={latest !== null ? <Median>{summary(latest)}</Median> : undefined}>
      {caption && <p className="mb-3 text-xs text-muted">{caption}</p>}
      <QueryState query={query}>
        {(s) => (
          <>
            {note?.(s)}
            <SeriesChart series={s} kind={kind} />
            <p className="mt-2 text-xs text-muted">Os Y: {kind.axisLabel}{kind.pace ? ", rýchlejšie hore" : ""}</p>
          </>
        )}
      </QueryState>
    </Card>
  );
}

export default function ProgressPage() {
  const [sport, setSport] = useState("run");
  const [days, setDays] = useState(365);
  const run = sport === "run";
  const opts = { keepPrevious: true };
  const ef = useApi<Schemas["SeriesDTO"]>("/progress/ef", { sport, days, metric: "ef" }, opts);
  const decoupling = useApi<Schemas["SeriesDTO"]>("/progress/ef", { sport, days, metric: "decoupling_pct" }, opts);
  const paceRef = useApi<Schemas["SeriesDTO"]>("/progress/ef", { sport: "run", days, metric: "pace_at_ref_hr_day" }, { ...opts, enabled: run });
  const curves = useApi<Schemas["CurveDTO"][]>("/progress/speed-hr-curve", { months: 6 }, { ...opts, enabled: run });
  const recent = useApi<Schemas["BestEffortsDTO"]>("/progress/best-efforts", { sport, range: "90d" }, opts);
  const all = useApi<Schemas["BestEffortsDTO"]>("/progress/best-efforts", { sport, range: "all" }, opts);
  const predictions = useApi<Schemas["PredictionsDTO"]>("/progress/predictions", undefined, { ...opts, enabled: run });
  const proposals = useApi<Schemas["ProposalDTO"][]>("/progress/threshold-proposals");
  const gaps = useApi<Schemas["ProposalGapDTO"][]>("/progress/threshold-proposals/missing");

  return (
    <>
      <PageHeader
        title="Progres"
        right={
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            <Segmented label="Šport" value={sport} onChange={setSport} options={SPORTS} />
            <Segmented label="Rozsah" value={days} onChange={setDays} options={RANGES} />
          </div>
        }
      />
      <div className="flex flex-col gap-4">
        {run && <BlockSection withPicker />}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <SeriesCard
            title="Efektivita (EF) – trend"
            caption="EF = priemerná rýchlosť (m/min) / priemerný tep. Iba steady-state aktivity; čiara je 28-dňový medián. Rastúca čiara = lepšia aeróbna kondícia."
            note={(s) => s.caveat && <div className="mb-3"><Notice tone="yellow">Bicykel: EF závisí od terénu a vetra – sleduj iba trend, nie jednotlivé jazdy.</Notice></div>}
            query={ef}
            kind={EF_KIND}
            summary={(v) => fmtNum(v, 2)}
          />
          <SeriesCard
            title="Aeróbny decoupling"
            caption="Pokles EF medzi 1. a 2. polovicou aktivity. Pod 5 % dobré, 5–10 % priemerné, nad 10 % slabé."
            query={decoupling}
            kind={DECOUPLING_KIND}
            summary={(v) => fmtNum(v, 1, "%")}
          />
          {run ? (
            <>
              <Card title="Krivka rýchlosť–tep (posledných 6 mesiacov)">
                <p className="mb-3 text-xs text-muted">Každá čiara = 28 dní končiace koncom mesiaca. Krivka posunutá nahor (rýchlejšie tempo pri rovnakom tepe) znamená zlepšenie.</p>
                <QueryState query={curves}>{(c) => <CurvesChart curves={c} />}</QueryState>
                <p className="mt-2 text-xs text-muted">Os X: tepové pásmo (bpm, dolná hranica) · Os Y: GAP tempo (min/km), rýchlejšie hore</p>
              </Card>
              <SeriesCard title="Tempo pri referenčnom tepe (80 % LTHR)" query={paceRef} kind={PACE_REF_KIND} summary={(v) => fmtPace(v)} />
            </>
          ) : (
            <div className="xl:col-span-2">
              <Notice>Krivky rýchlosť–tep, tempo pri referenčnom tepe a predikcie pretekov sú len pre beh.</Notice>
            </div>
          )}
        </div>

        <div className={run ? "grid grid-cols-1 gap-4 xl:grid-cols-2" : ""}>
          <Card title="Najlepšie úseky: 90 dní vs celá história">
            <QueryState query={recent}>
              {(r) => (
                <QueryState query={all}>
                  {(a) => (
                    <div className="flex flex-col gap-4">
                      <SpeedEfforts sport={sport} recent={r} all={a} />
                      <div>
                        <h3 className="label mb-1">Tep najlepších úsekov</h3>
                        <HrEfforts recent={r} all={a} />
                      </div>
                      <EffortsTable sport={sport} recent={r} all={a} />
                    </div>
                  )}
                </QueryState>
              )}
            </QueryState>
          </Card>
          {run && (
            <Card title="Predikcie pretekov">
              <QueryState query={predictions}>{(p) => <Predictions dto={p} />}</QueryState>
            </Card>
          )}
        </div>

        <Card title="Návrhy prahov">
          <QueryState query={proposals}>
            {(p) => (
              <QueryState query={gaps}>{(g) => <Proposals proposals={p} gaps={g} />}</QueryState>
            )}
          </QueryState>
        </Card>
      </div>
    </>
  );
}
