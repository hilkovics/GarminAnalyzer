// Návrhy prahov z posledných 90 dní: the estimates, why some are missing and one "Použiť" button per proposed
// change (POST /progress/threshold-proposals/apply). A proposal is never applied automatically.
import { useApi, useApiMutation, type Schemas } from "@/api/client";
import { Badge, Button, Card, ErrorBox, Notice, QueryState, Table } from "@/components/ui";
import { sportLabel } from "@/lib/format";

import { FIELD_LABELS, proposalChange, proposalGarmin, proposalValue } from "./forms";

type Proposal = Schemas["ProposalDTO"];
type Apply = Schemas["ProposalApplyIn"];

function Gaps() {
  const gaps = useApi<Schemas["ProposalGapDTO"][]>("/progress/threshold-proposals/missing");
  if (!gaps.data?.length) return null;
  return (
    <ul className="mt-3 flex flex-col gap-1 text-sm text-muted">
      {gaps.data.map((g) => (
        <li key={`${g.sport}-${g.field}`}>
          Bez návrhu – {sportLabel(g.sport)}, {FIELD_LABELS[g.field] ?? g.field}: {g.reason}
        </li>
      ))}
    </ul>
  );
}

function ApplyButtons({ proposals, onSaved }: { proposals: Proposal[]; onSaved: (message: string) => void }) {
  const apply = useApiMutation<Apply, Schemas["ThresholdDTO"]>("POST", () => "/progress/threshold-proposals/apply");
  const proposed = proposals.filter((p) => p.propose);
  if (!proposed.length) return null;
  return (
    <div className="mt-4 flex flex-col items-start gap-2">
      <div className="flex flex-wrap gap-2">
        {proposed.map((p) => {
          const what = `${FIELD_LABELS[p.field] ?? p.field} ${proposalValue(p.field, p.estimate)}`;
          return (
            <Button
              key={`${p.sport}-${p.field}`}
              variant="secondary"
              disabled={apply.isPending}
              onClick={() =>
                apply.mutate(
                  { sport: p.sport as Apply["sport"], field: p.field as Apply["field"] },
                  { onSuccess: () => onSaved(`Návrh prahu (${sportLabel(p.sport)}, ${FIELD_LABELS[p.field] ?? p.field}) uložený od dnes.`) },
                )
              }
            >
              Použiť: {sportLabel(p.sport)} – {what} od dnes
            </Button>
          );
        })}
      </div>
      {apply.isPending && (
        <span className="text-sm text-muted" role="status">
          Ukladám prah a prepočítavam metriky…
        </span>
      )}
      {apply.error && <ErrorBox error={apply.error} />}
    </div>
  );
}

export function Proposals({ onSaved }: { onSaved: (message: string) => void }) {
  const query = useApi<Proposal[]>("/progress/threshold-proposals");
  return (
    <Card title="Návrhy prahov z posledných 90 dní">
      <p className="mb-3 text-sm text-muted">Návrhy sa nikdy nepoužijú automaticky. Použitie uloží nový prah platný od dnes.</p>
      <QueryState query={query}>
        {(proposals) =>
          proposals.length ? (
            <>
              <Table
                head={["Šport", "Prah", "Aktuálne", "Odhad", "Zmena", "Navrhnúť", "Garmin", "Základ"]}
                align={["left", "left", "right", "right", "right", "left", "left", "left"]}
                rows={proposals.map((p) => [
                  sportLabel(p.sport),
                  FIELD_LABELS[p.field] ?? p.field,
                  proposalValue(p.field, p.current),
                  proposalValue(p.field, p.estimate),
                  proposalChange(p),
                  p.propose ? <Badge tone="blue">áno</Badge> : <Badge>nie</Badge>,
                  proposalGarmin(p),
                  p.basis,
                ])}
              />
              <ApplyButtons proposals={proposals} onSaved={onSaved} />
            </>
          ) : (
            <Notice>Zatiaľ žiadne návrhy prahov – chýbajú najlepšie úseky z posledných 90 dní.</Notice>
          )
        }
      </QueryState>
      <Gaps />
    </Card>
  );
}
