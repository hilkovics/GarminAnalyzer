// Relationships between health metrics (METRICS §12.3): findings with the sentence, ρ and its CI, n, the
// quartile contrast and a button that shows the pair in the charts.
import { LineChart as ChartIcon } from "lucide-react";

import type { Schemas } from "@/api/client";
import { Badge, Notice } from "@/components/ui";
import { fmtNum } from "@/lib/format";

import { fmtMetricDiff } from "./format";

type Rel = Schemas["HealthRelationshipDTO"];
type Metric = Schemas["HealthMetricDTO"];

const rho = (v: number) => fmtNum(v, 2);

function Row({ r, units, onShow }: { r: Rel; units: Record<string, string>; onShow: (keys: string[]) => void }) {
  return (
    <li className="flex flex-col gap-1.5 rounded-lg border border-line bg-card-2 p-3">
      <p className="text-sm">{r.text}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
        <Badge tone={r.finding ? "blue" : "gray"}>ρ {rho(r.rho)}</Badge>
        <span className="num">
          95 % interval {rho(r.ci_low)} až {rho(r.ci_high)} · n = {r.n} dní
        </span>
        {r.contrast !== null && r.contrast !== undefined && (
          <span className="num">rozdiel najvyššej a najnižšej štvrtiny dní: {fmtMetricDiff(r.contrast, units[r.y] ?? "")}</span>
        )}
        <button type="button" className="inline-flex items-center gap-1 font-medium text-accent hover:underline" onClick={() => onShow([r.x, r.y])}>
          <ChartIcon size={13} aria-hidden /> V grafe
        </button>
      </div>
    </li>
  );
}

export function Relationships({ data, metrics, onShow }: { data: Schemas["HealthRelationshipsDTO"]; metrics: Metric[]; onShow: (keys: string[]) => void }) {
  const units = Object.fromEntries(metrics.map((m) => [m.key, m.unit]));
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted">
        Porovnávajú sa odchýlky od tvojho normálu (nie surové hodnoty), v ten istý deň aj s odstupom jedného dňa. Otestovaných dvojíc: {data.tested}; ako
        súvislosť sa ukáže len to, čo prejde štatistickou kontrolou pre veľa porovnaní naraz (|ρ| ≥ 0,2).
      </p>
      {data.findings.length ? (
        <ul className="flex flex-col gap-2">
          {data.findings.map((r) => (
            <Row key={`${r.x}-${r.y}-${r.lag}`} r={r} units={units} onShow={onShow} />
          ))}
        </ul>
      ) : (
        <Notice>Zatiaľ žiadna spoľahlivá súvislosť – treba aspoň 30 dní s oboma hodnotami a výraznejší vzťah.</Notice>
      )}
      {data.others.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted hover:text-text">Najsilnejšie ostatné dvojice (neprešli kontrolou)</summary>
          <ul className="mt-2 flex flex-col gap-2">
            {data.others.map((r) => (
              <Row key={`${r.x}-${r.y}-${r.lag}`} r={r} units={units} onShow={onShow} />
            ))}
          </ul>
        </details>
      )}
      <p className="text-xs text-muted">Súvislosť neznamená príčinu: oboje môže ovplyvňovať niečo tretie (choroba, cestovanie, horúčava).</p>
    </div>
  );
}
