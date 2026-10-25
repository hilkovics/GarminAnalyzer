// "Zistenia": sleep ↔ performance findings with the caveat, the mini ρ axis, folded extras and thin-data pairs.
import { useState } from "react";

import { useApi, type Schemas } from "@/api/client";
import { Badge, Card, cx, Notice, QueryState, Segmented } from "@/components/ui";
import { sportLabel } from "@/lib/format";

import { RhoAxis } from "./RhoAxis";
import { statsLine, type Finding } from "./rho";

const SPORTS = [
  { value: "run", label: "Beh" },
  { value: "bike", label: "Bicykel" },
];
const TOP_FINDINGS = 10;

function FindingRow({ finding }: { finding: Finding }) {
  return (
    <li className="grid grid-cols-1 items-center gap-2 rounded-lg border border-line bg-card-2 px-4 py-3 sm:grid-cols-[minmax(0,5fr)_minmax(0,2fr)] sm:gap-6" data-uncertain={finding.uncertain}>
      <div className="min-w-0">
        <p className={cx("text-sm font-semibold", finding.uncertain && "text-muted")}>{finding.sentence}</p>
        <p className="num mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
          {statsLine(finding)}
          {finding.uncertain && <Badge tone="gray">neisté</Badge>}
        </p>
      </div>
      <div className={cx("justify-self-start sm:w-full sm:justify-self-end", finding.uncertain && "opacity-80")}>
        <RhoAxis finding={finding} />
      </div>
    </li>
  );
}

function FindingsList({ items }: { items: Finding[] }) {
  return (
    <ul className="flex flex-col gap-2">
      {items.map((f) => (
        <FindingRow key={`${f.sport}-${f.predictor}-${f.outcome}`} finding={f} />
      ))}
    </ul>
  );
}

function Fold({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="group border-t border-line pt-3">
      <summary className="cursor-pointer select-none text-sm font-medium">{title}</summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}

function Body({ dto }: { dto: Schemas["CorrelationsDTO"] }) {
  const days = Object.entries(dto.n_days)
    .map(([sport, n]) => `${sportLabel(sport)}: ${n}`)
    .join(", ");
  const rest = dto.findings.slice(TOP_FINDINGS);
  return (
    <div className="flex flex-col gap-3">
      <Notice tone="yellow">{dto.caveat}</Notice>
      {days && <p className="text-xs text-muted">Dni s aktivitou (dataset): {days}</p>}
      {dto.findings.length === 0 ? (
        <Notice>Zatiaľ žiadne zistenia – každá dvojica potrebuje aspoň {dto.min_n} dní s údajmi.</Notice>
      ) : (
        <FindingsList items={dto.findings.slice(0, TOP_FINDINGS)} />
      )}
      {rest.length > 0 && (
        <Fold title={`Ďalšie zistenia (${rest.length})`}>
          <FindingsList items={rest} />
        </Fold>
      )}
      {dto.insufficient.length > 0 && (
        <Fold title={`Nedostatok dát (n < ${dto.min_n}): ${dto.insufficient.length} dvojíc`}>
          <ul className="flex flex-col gap-1 text-xs text-muted">
            {dto.insufficient.map((f) => (
              <li key={`${f.sport}-${f.predictor}-${f.outcome}`}>{f.sentence}</li>
            ))}
          </ul>
        </Fold>
      )}
    </div>
  );
}

export function Findings() {
  const [sport, setSport] = useState("run");
  const query = useApi<Schemas["CorrelationsDTO"]>("/wellness/correlations", { sport }, { keepPrevious: true });
  return (
    <Card title="Zistenia" right={<Segmented label="Šport zistení" value={sport} onChange={setSport} options={SPORTS} />}>
      <QueryState query={query} loading="Počítam korelácie…">
        {(dto) => <Body dto={dto} />}
      </QueryState>
    </Card>
  );
}
