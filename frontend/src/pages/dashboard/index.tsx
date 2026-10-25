// Dashboard: health notices, readiness + today's workout, form tiles, week vs last 4, mini PMC, AI report.
import { ChevronDown, FileText, RefreshCw } from "lucide-react";
import { useState } from "react";

import { useApi, type Schemas } from "@/api/client";
import { PmcChart } from "@/components/charts";
import { Markdown } from "@/components/Markdown";
import { Badge, Card, Notice, PageHeader, QueryState, Stat } from "@/components/ui";
import { fmtDate, fmtDateTime, fmtLongDate, fmtNum, fmtSigned, isoWeekLabel } from "@/lib/format";
import { acwrBadge } from "@/lib/labels";

import { ReadinessCard, TodayCard } from "./TodayCards";
import { WeekCompare } from "./WeekCompare";

function Health({ dash }: { dash: Schemas["DashboardDTO"] }) {
  const notes = [];
  if (dash.last_sync === null) notes.push(<Notice key="s" tone="red">Posledný sync: žiadny. Spusti ho v Nastaveniach alebo príkazom <code>uv run training sync</code>.</Notice>);
  else if (dash.sync_stale)
    notes.push(
      <Notice key="s" tone="red">
        Posledný sync je starší ako 36 hodín (posledný: {fmtDate(dash.last_sync)}). Spusti ho v Nastaveniach.
      </Notice>,
    );
  if (dash.last_run_ok === false) notes.push(<Notice key="m" tone="red">Posledný ranný beh zlyhal – pozri Nastavenia → Sync a diagnostika.</Notice>);
  else if (dash.last_run_ok && dash.morning_run_stale)
    notes.push(
      <Notice key="m" tone="red">
        Posledný úspešný ranný beh je starší ako 36 hodín (posledný: {fmtDateTime(dash.last_successful_run, ", ")}).
      </Notice>,
    );
  return notes.length ? <div className="mb-4 flex flex-col gap-2">{notes}</div> : null;
}

function FormTiles({ latest }: { latest: Schemas["PmcPointDTO"] }) {
  const acwr = acwrBadge(latest.acwr_band);
  const tile = "rounded-none border-0 p-4 sm:p-5";
  return (
    <section className="grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-card sm:grid-cols-3 lg:grid-cols-5 [&>*]:border-line [&>*:not(:last-child)]:border-b lg:[&>*:not(:last-child)]:border-b-0 lg:[&>*:not(:last-child)]:border-r">
      <div className={tile}>
        <Stat label="CTL (kondícia)" color="var(--run)" value={fmtNum(latest.ctl, 1)} unit="TSS-ekv." hint="Chronická záťaž, 42-dňový priemer." />
      </div>
      <div className={tile}>
        <Stat label="ATL (únava)" color="var(--bike)" value={fmtNum(latest.atl, 1)} unit="TSS-ekv." hint="Akútna záťaž, 7-dňový priemer." />
      </div>
      <div className={tile}>
        <Stat label="TSB (sviežosť)" color="var(--green)" value={fmtSigned(latest.tsb)} unit="TSS-ekv." hint="CTL − ATL z predošlého dňa." />
      </div>
      <div className={tile}>
        <Stat
          label="ACWR"
          value={fmtNum(latest.acwr, 2)}
          valueClass={latest.acwr_band === "caution" ? "text-bike" : latest.acwr_band === "danger" ? "text-bad" : undefined}
          badge={latest.acwr_band ? <Badge tone={acwr.tone}>{acwr.text}</Badge> : undefined}
          hint="Pomer akútnej a chronickej záťaže."
        />
      </div>
      <div className={tile}>
        <Stat label="Nárast CTL / týždeň" value={fmtSigned(latest.ramp_rate)} badge={latest.ramp_warning ? <Badge tone="red">príliš rýchlo</Badge> : undefined} />
      </div>
    </section>
  );
}

function WeeklyReport() {
  const [open, setOpen] = useState(false);
  const report = useApi<Schemas["ReportDTO"]>("/reports/latest", undefined, { enabled: open });
  return (
    <Card padded={false}>
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-4 py-3 text-left sm:px-5" aria-expanded={open}>
        <FileText size={18} className="text-muted" />
        <span className="label">Týždenný report</span>
        {report.data && (
          <span className="text-xs text-muted">
            Týždeň {report.data.week}, vygenerované {fmtDateTime(report.data.generated_at)} ({report.data.model})
          </span>
        )}
        <ChevronDown size={18} className={`ml-auto text-muted transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="border-t border-line px-4 py-3 sm:px-5">
          {report.isPending ? (
            <p className="text-sm text-muted">Načítavam…</p>
          ) : report.error?.status === 404 ? (
            <p className="text-sm text-muted">
              Týždenný report zatiaľ nie je. Zapni ho nastavením <code>TRAINING_ANTHROPIC_API_KEY</code> a spusti <code>uv run training weekly-report</code>.
            </p>
          ) : report.data ? (
            <Markdown text={report.data.markdown} />
          ) : (
            <p className="text-sm text-bad">{report.error?.message}</p>
          )}
        </div>
      )}
    </Card>
  );
}

export default function DashboardPage() {
  const dash = useApi<Schemas["DashboardDTO"]>("/fitness/dashboard");
  const readiness = useApi<Schemas["ReadinessDTO"]>("/wellness/readiness/today");
  const today = useApi<Schemas["DailyDecisionDTO"]>("/plan/today");
  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={dash.data ? `${fmtLongDate(dash.data.today)} · ${isoWeekLabel(dash.data.today)}` : undefined}
        right={
          dash.data?.last_sync && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1 text-xs text-muted">
              <RefreshCw size={13} className={dash.data.sync_stale ? "text-bad" : "text-good"} />
              Posledný sync: {fmtDate(dash.data.last_sync)}
              {dash.data.last_successful_run && ` · ranný beh ${fmtDateTime(dash.data.last_successful_run, ", ")}`}
            </span>
          )
        }
      />
      <QueryState query={dash}>
        {(d) => (
          <div className="flex flex-col gap-4">
            <Health dash={d} />
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2.2fr)]">
              <ReadinessCard query={readiness} />
              <TodayCard query={today} />
            </div>
            {d.latest ? (
              <>
                <FormTiles latest={d.latest} />
                {d.latest.warming_up && <p className="text-xs text-muted">Séria je ešte v prvých 90 dňoch – CTL a ATL sa zahrievajú a nie sú spoľahlivé.</p>}
              </>
            ) : (
              <Notice>Zatiaľ žiadne metriky. Spusti sync v Nastaveniach.</Notice>
            )}
            <WeekCompare week={d.this_week} avg={d.last4_avg} weekStart={d.week_start} />
            <Card title="Kondícia a únava (posledných 42 dní)" right={<span className="text-xs text-muted">Os Y: TSS-ekvivalent</span>}>
              <PmcChart pmc={d.pmc} height={260} />
            </Card>
            <WeeklyReport />
          </div>
        )}
      </QueryState>
    </>
  );
}
