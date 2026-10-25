// Diagnostika (GET /diagnostics): sync state and queues, data quality, METRICS §2.5 load sanity check,
// hrTSS vs rTSS divergences, the "Ranné behy" table and the last errors.
import { useApi, type Schemas } from "@/api/client";
import { Badge, Card, Notice, QueryState, Stat, Table } from "@/components/ui";
import { fmtDate, fmtDateTime, fmtDurationHms, fmtNum, fmtPct, sportLabel } from "@/lib/format";
import { sanityBadge } from "@/lib/labels";

type Diagnostics = Schemas["DiagnosticsDTO"];
type Run = Schemas["MorningRunDTO"];

const STEPS = [
  ["sync", "Sync"],
  ["plan", "Plán"],
  ["push", "Garmin"],
  ["telegram", "Telegram"],
] as const;
const MARKS: Record<string, { mark: string; text: string; cls: string }> = {
  ok: { mark: "✓", text: "v poriadku", cls: "text-good" },
  failed: { mark: "✗", text: "zlyhalo", cls: "text-bad" },
  skipped: { mark: "–", text: "preskočené", cls: "text-muted" },
};

function StepMark({ run, name }: { run: Run; name: string }) {
  const status = run.steps?.find((s) => s.name === name)?.status;
  const m = (status && MARKS[status]) || MARKS.skipped;
  return (
    <span className={m.cls} role="img" aria-label={m.text} title={m.text}>
      {m.mark}
    </span>
  );
}

function MorningRuns({ runs, errors }: { runs: Run[]; errors: string[] }) {
  return (
    <>
      <Card title="Ranné behy">
        {runs.length ? (
          <Table
            head={["Začiatok", "Trvanie", "Výsledok", ...STEPS.map(([, label]) => label)]}
            align={["left", "right", "left", "left", "left", "left", "left"]}
            rows={runs.map((run) => [
              fmtDateTime(run.started_at),
              fmtDurationHms(run.duration_s),
              run.ok ? <Badge tone="green">OK</Badge> : <Badge tone="red">Chyba</Badge>,
              ...STEPS.map(([name]) => <StepMark key={name} run={run} name={name} />),
            ])}
          />
        ) : (
          <p className="text-sm text-muted">Automatický ranný beh zatiaľ nebežal – návod v docs/OPERATIONS.md.</p>
        )}
      </Card>
      <Card title="Posledné chyby">
        {errors.length ? (
          <div className="flex flex-col gap-2">
            {errors.map((message, i) => (
              <Notice key={i} tone="yellow">
                {message}
              </Notice>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted">Žiadne chyby.</p>
        )}
      </Card>
    </>
  );
}

function Body({ d }: { d: Diagnostics }) {
  const sanity = sanityBadge(d.load_sanity.status);
  return (
    <div className="flex flex-col gap-4">
      <Card title="Stav synchronizácie">
        <div className="grid grid-cols-2 gap-x-4 gap-y-5 lg:grid-cols-4">
          <Stat label="Posledný sync aktivít" value={fmtDate(d.last_activity_sync)} valueClass="text-2xl" />
          <Stat label="Posledné wellness" value={fmtDate(d.last_wellness_date)} valueClass="text-2xl" />
          <Stat label="Backfill (kurzor)" value={fmtDate(d.backfill_cursor)} valueClass="text-2xl" />
          <Stat label="Čakajúce" value={`${d.pending_activities} akt. / ${d.pending_wellness_days} dní`} valueClass="text-2xl" />
        </div>
        {(d.failed_activities.length > 0 || d.failed_wellness_days.length > 0) && (
          <div className="mt-4 flex flex-col gap-2">
            {d.failed_activities.length > 0 && <Notice tone="yellow">Zlyhané aktivity (Garmin id): {d.failed_activities.join(", ")}</Notice>}
            {d.failed_wellness_days.length > 0 && (
              <Notice tone="yellow">Zlyhané wellness dni: {d.failed_wellness_days.map((x) => fmtDate(x)).join(", ")}</Notice>
            )}
          </div>
        )}
      </Card>

      <Card title="Kvalita dát">
        <div className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 lg:grid-cols-5">
          <Stat label="Aktivity" value={fmtNum(d.activities)} valueClass="text-2xl" />
          <Stat label="S metrikami" value={fmtNum(d.activities_with_metrics)} valueClass="text-2xl" />
          <Stat label="Bez prahu" value={fmtNum(d.activities_without_threshold)} valueClass="text-2xl" />
          <Stat label="Bez záťaže" value={fmtNum(d.activities_without_load)} valueClass="text-2xl" />
          <Stat label="Nízka spoľahlivosť" value={fmtPct(d.low_confidence_share)} valueClass="text-2xl" />
        </div>
      </Card>

      <MorningRuns runs={d.recent_runs ?? []} errors={d.last_errors ?? []} />

      <Card title="Kontrola záťaže vs. Garmin training load">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
          <Stat label="Pearson r" value={fmtNum(d.load_sanity.r, 2)} hint="Korelácia load_primary s Garmin training load (METRICS §2.5)." />
          <div className="flex flex-col gap-1 text-sm">
            <span>
              <Badge tone={sanity.tone}>{sanity.text}</Badge> <span className="text-muted">· n = {d.load_sanity.n} aktivít</span>
            </span>
            <span className="text-muted">r &gt; 0,8 je dobré; pod 0,7 najprv skontroluj LTHR.</span>
          </div>
        </div>
      </Card>

      <Card title="Behy, kde sa hrTSS a rTSS líšia o viac ako 40 %">
        {d.hrtss_rtss_divergent.length ? (
          <Table
            head={["Garmin id", "Dátum", "Šport", "hrTSS", "rTSS", "Rozdiel (%)"]}
            align={["left", "left", "left", "right", "right", "right"]}
            rows={d.hrtss_rtss_divergent.map((x) => [
              x.garmin_id,
              fmtDate(x.local_date),
              sportLabel(x.sport),
              fmtNum(x.hrtss, 0),
              fmtNum(x.rtss, 0),
              fmtNum(x.diff_pct, 0),
            ])}
          />
        ) : (
          <p className="text-sm text-muted">Žiadne.</p>
        )}
      </Card>
    </div>
  );
}

export function DiagnosticsPanel() {
  const query = useApi<Diagnostics>("/diagnostics");
  return <QueryState query={query}>{(d) => <Body d={d} />}</QueryState>;
}
