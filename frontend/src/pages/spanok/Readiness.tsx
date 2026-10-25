// "Pripravenosť dnes": gauge, band badge, message and the component breakdown (score, weight, value vs baseline).
import { useApi, type Schemas } from "@/api/client";
import { ReadinessGauge } from "@/components/charts";
import { Badge, Card, Notice, QueryState, Table } from "@/components/ui";
import { DASH, fmtDuration, fmtNum, fmtPct, fmtSigned } from "@/lib/format";
import { readinessBadge } from "@/lib/labels";

type Component = Schemas["ReadinessComponentDTO"];

const COMPONENT_LABELS: Record<string, string> = {
  rhr: "Pokojový tep",
  sleep: "Spánok",
  body_battery: "Body Battery",
  form: "Forma (TSB)",
};

/** A component input or baseline in its own unit (seconds as h:mm, TSB signed). */
export function componentValue(c: Pick<Component, "unit">, x: number | null): string {
  if (x === null) return DASH;
  if (c.unit === "bpm") return fmtNum(x, 0, "bpm");
  if (c.unit === "s") return fmtDuration(x);
  if (c.unit === "TSB") return fmtSigned(x);
  return fmtNum(x, 0);
}

function Breakdown({ r }: { r: Schemas["ReadinessDTO"] }) {
  const rows = r.components.map((c) => [
    <span key="n" className="font-sans">{COMPONENT_LABELS[c.name] ?? c.name}</span>,
    fmtNum(c.score, 0),
    fmtPct(c.weight),
    componentValue(c, c.value),
    componentValue(c, c.baseline),
  ]);
  const fallback = r.components.some((c) => c.name === "sleep" && c.unit === "s" && c.value !== null);
  return (
    <>
      <Table head={["Zložka", "Skóre", "Váha", "Hodnota", "Baseline (medián 28 d)"]} rows={rows} align={["left", "right", "right", "right", "right"]} />
      <p className="mt-2 text-xs text-muted">Chýbajúca zložka sa zobrazí ako „–“ a váhy ostatných sa prepočítajú.</p>
      {fallback && <p className="mt-1 text-xs text-muted">Skóre spánku chýba – použitý prepočet z dĺžky spánku.</p>}
    </>
  );
}

export function Readiness() {
  const query = useApi<Schemas["ReadinessDTO"]>("/wellness/readiness/today");
  return (
    <Card title="Pripravenosť dnes">
      <QueryState query={query}>
        {(r) => {
          const badge = readinessBadge(r.band);
          return (
            <div className="grid items-center gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
              <div className="flex justify-center">
                <ReadinessGauge score={r.available ? r.score : null} band={r.band} size={260} />
              </div>
              <div className="flex min-w-0 flex-col gap-3">
                {r.available ? (
                  <p className="flex flex-wrap items-center gap-2">
                    <Badge tone={badge.tone}>{badge.text}</Badge>
                    <span className="font-semibold">{r.message}</span>
                  </p>
                ) : (
                  <Notice>{r.message}</Notice>
                )}
                <Breakdown r={r} />
              </div>
            </div>
          );
        }}
      </QueryState>
    </Card>
  );
}
