// Zdravie (METRICS §12): trend tiles of every health metric, overlaid charts of the chosen metrics (small
// multiples + relative to the normal), relationships between the metrics, and the former Spánok page as a tab.
import { useState } from "react";

import { useApi, type Schemas } from "@/api/client";
import { Card, Notice, PageHeader, QueryState, Segmented } from "@/components/ui";
import { fmtDate } from "@/lib/format";
import { SleepContent } from "@/pages/spanok";

import { RelativeChart, SeriesTable, StackedCharts } from "./Charts";
import { Relationships } from "./Relationships";
import { Tiles } from "./Tiles";

type Tab = "trends" | "relations" | "sleep";
const TABS: { value: Tab; label: string }[] = [
  { value: "trends", label: "Trendy" },
  { value: "relations", label: "Súvislosti" },
  { value: "sleep", label: "Spánok a výkon" },
];
const RANGES = [
  { value: 90, label: "90 dní" },
  { value: 180, label: "180 dní" },
  { value: 365, label: "1 rok" },
  { value: 730, label: "2 roky" },
];
const DEFAULT_KEYS = ["sleep_s", "rhr", "stress_avg"];
const MAX_KEYS = 4;

export function initialTab(search: string): Tab {
  const tab = new URLSearchParams(search).get("tab");
  return TABS.some((t) => t.value === tab) ? (tab as Tab) : "trends";
}

/** Toggle `key` in the selection: at most 4, the oldest drops out, at least one stays. */
export function toggleKey(keys: string[], key: string): string[] {
  if (keys.includes(key)) return keys.length > 1 ? keys.filter((k) => k !== key) : keys;
  return [...keys, key].slice(-MAX_KEYS);
}

function Overlay({ keys, days }: { keys: string[]; days: number }) {
  const series = useApi<Schemas["HealthSeriesDTO"][]>("/wellness/health/series", { metrics: keys.join(","), days }, { keepPrevious: true });
  return (
    <QueryState query={series}>
      {(s) => (
        <div className="flex flex-col gap-4">
          <section className="min-w-0">
            <h3 className="label mb-1">Oproti tvojmu normálu (spoločná škála)</h3>
            <p className="mb-2 text-xs text-muted">7-dňový priemer každého ukazovateľa v % nad / pod jeho normálom (medián predošlých 28 dní) – tak sa dajú prekryť aj veličiny v rôznych jednotkách.</p>
            <RelativeChart series={s} />
          </section>
          <section className="min-w-0">
            <h3 className="label mb-2">Hodnoty pod sebou</h3>
            <StackedCharts series={s} />
          </section>
          <SeriesTable series={s} />
        </div>
      )}
    </QueryState>
  );
}

function Trends({ overview, keys, setKeys }: { overview: Schemas["HealthOverviewDTO"]; keys: string[]; setKeys: (k: string[]) => void }) {
  const [days, setDays] = useState(180);
  const withData = overview.metrics.filter((m) => m.latest !== null || m.monthly.length);
  const without = overview.metrics.filter((m) => m.latest === null && !m.monthly.length);
  return (
    <div className="flex flex-col gap-4">
      <Card title="Prehľad" right={<span className="text-xs text-muted">posledných 28 dní oproti predošlým 28</span>}>
        <p className="mb-3 text-xs text-muted">Kliknutím na dlaždicu ju pridáš do grafov nižšie (najviac 4). Zelená / červená = výrazná zmena k lepšiemu / horšiemu; čiarka dole = mesačné priemery.</p>
        <Tiles metrics={withData} selected={keys} onToggle={(k) => setKeys(toggleKey(keys, k))} />
        {without.length > 0 && <p className="mt-3 text-xs text-muted">Bez dát: {without.map((m) => m.label).join(", ")} – doplnia sa po <code>uv run training recompute</code> alebo ďalšom syncu.</p>}
      </Card>
      <Card title="Grafy" right={<Segmented label="Rozsah" value={days} onChange={setDays} options={RANGES} />}>
        <Overlay keys={keys} days={days} />
      </Card>
    </div>
  );
}

export default function HealthPage() {
  const [tab, setTab] = useState<Tab>(() => initialTab(window.location.search));
  const [keys, setKeys] = useState<string[]>(DEFAULT_KEYS);
  const overview = useApi<Schemas["HealthOverviewDTO"]>("/wellness/health");
  const relations = useApi<Schemas["HealthRelationshipsDTO"]>("/wellness/health/relationships", undefined, { enabled: tab === "relations" });
  const show = (pair: string[]) => {
    setKeys(pair);
    setTab("trends");
  };
  return (
    <>
      <PageHeader
        title="Zdravie"
        subtitle={overview.data?.first_date ? `údaje od ${fmtDate(overview.data.first_date)}` : undefined}
        right={<Segmented label="Časť" value={tab} onChange={setTab} options={TABS} />}
      />
      {tab === "sleep" ? (
        <SleepContent />
      ) : (
        <QueryState query={overview}>
          {(o) =>
            !o.first_date ? (
              <Notice>Zatiaľ žiadne wellness dáta. Spusti sync v Nastaveniach.</Notice>
            ) : tab === "trends" ? (
              <Trends overview={o} keys={keys} setKeys={setKeys} />
            ) : (
              <Card title="Súvislosti medzi ukazovateľmi">
                <QueryState query={relations}>{(r) => <Relationships data={r} metrics={o.metrics} onShow={show} />}</QueryState>
              </Card>
            )
          }
        </QueryState>
      )}
    </>
  );
}
