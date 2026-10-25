// Race predictions and threshold proposals (read-only; a proposal is applied on Nastavenia).
import { Link } from "@tanstack/react-router";

import type { Schemas } from "@/api/client";
import { Badge, Notice, Table } from "@/components/ui";
import { DASH, fmtDate, fmtKm, fmtNum, fmtPace, fmtPctSigned, fmtSigned, fmtTimeHms, sportLabel } from "@/lib/format";

type Proposal = Schemas["ProposalDTO"];
type Gap = Schemas["ProposalGapDTO"];

const PREDICTION_NAMES: Record<string, string> = { "5k": "5 km", "10k": "10 km", half: "Polmaratón", marathon: "Maratón" };
const FIELD_LABELS: Record<string, string> = { threshold_speed: "Prahové tempo", lthr: "LTHR" };
const fieldLabel = (field: string) => FIELD_LABELS[field] ?? field;

export function Predictions({ dto }: { dto: Schemas["PredictionsDTO"] }) {
  const ref = dto.reference;
  if (!ref) return <Notice>Zatiaľ žiadny referenčný výkon (pretek alebo najlepší úsek ≥ 10 min so známou vzdialenosťou).</Notice>;
  const source = ref.source === "race" ? "pretek" : "najlepší úsek";
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm">
        Referencia: <span className="num">{fmtKm(ref.distance_m, 2)}</span> za <span className="num">{fmtTimeHms(ref.time_s)}</span> ({fmtPace(ref.distance_m / ref.time_s)}),{" "}
        {fmtDate(ref.local_date)}, {source} · VDOT <span className="num">{fmtNum(ref.vdot, 1)}</span>
      </p>
      {dto.stale && <Notice tone="yellow">⚠ Referenčný výkon je starší ako 60 dní – predikcie môžu byť zastarané.</Notice>}
      <Table
        head={["Vzdialenosť", "Riegel", "Daniels (VDOT)", "Tempo (Daniels)", "Poznámka"]}
        align={["left", "right", "right", "right", "left"]}
        rows={dto.predictions.map((p) => [
          PREDICTION_NAMES[p.name] ?? p.name,
          fmtTimeHms(p.riegel_s),
          <strong key="d">{fmtTimeHms(p.daniels_s)}</strong>,
          fmtPace(p.distance_m / p.daniels_s),
          p.extrapolated ? <span key="x" className="font-sans text-warn">⚠ extrapolované</span> : "",
        ])}
      />
      {dto.predictions.some((p) => p.extrapolated) && <p className="text-xs text-muted">Extrapolované = referenčná vzdialenosť je menšia ako ¼ cieľa.</p>}
    </div>
  );
}

const isSpeed = (p: Proposal) => p.field === "threshold_speed";
const value = (p: Proposal, x: number | null | undefined) => (x === null || x === undefined ? DASH : isSpeed(p) ? fmtPace(x) : fmtNum(x, 0, "bpm"));
const change = (p: Proposal) => (p.change === null || p.change === undefined ? DASH : isSpeed(p) ? fmtPctSigned(p.change) : `${fmtSigned(p.change, 0)} bpm`);

function garmin(p: Proposal): string {
  const parts: string[] = [];
  if (p.field === "lthr" && p.garmin_lthr != null) parts.push(`LT tep ${fmtNum(p.garmin_lthr, 0)} bpm`);
  if (isSpeed(p) && p.garmin_lt_speed != null) parts.push(`LT tempo ${fmtPace(p.garmin_lt_speed)}`);
  if (p.garmin_vo2max != null) parts.push(`VO2max ${fmtNum(p.garmin_vo2max, 0)}`);
  return parts.join(" · ") || DASH;
}

export function Proposals({ proposals, gaps }: { proposals: Proposal[]; gaps: Gap[] }) {
  return (
    <div className="flex flex-col gap-3">
      {proposals.length ? (
        <Table
          head={["Šport", "Prah", "Aktuálne", "Odhad", "Zmena", "Navrhnúť", "Garmin", "Základ"]}
          align={["left", "left", "right", "right", "right", "left", "right", "left"]}
          rows={proposals.map((p) => [
            sportLabel(p.sport),
            <span key="f" className="font-sans">{fieldLabel(p.field)}</span>,
            value(p, p.current),
            <strong key="e">{value(p, p.estimate)}</strong>,
            change(p),
            <Badge key="b" tone={p.propose ? "green" : "gray"}>{p.propose ? "áno" : "nie"}</Badge>,
            garmin(p),
            <span key="basis" className="font-sans text-muted">{p.basis}</span>,
          ])}
        />
      ) : (
        <Notice>Zatiaľ žiadne návrhy prahov – chýbajú najlepšie úseky z posledných 90 dní.</Notice>
      )}
      {gaps.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs text-muted">
          {gaps.map((g) => (
            <li key={`${g.sport}-${g.field}`}>
              Bez návrhu – {sportLabel(g.sport)}, {fieldLabel(g.field)}: {g.reason}
            </li>
          ))}
        </ul>
      )}
      {proposals.some((p) => p.propose) && (
        <div>
          <Link to="/nastavenia" className="inline-flex items-center justify-center rounded-lg bg-accent px-3.5 py-2 text-sm font-semibold text-accent-text transition hover:brightness-110">
            Použiť návrh v Nastaveniach
          </Link>
        </div>
      )}
    </div>
  );
}
