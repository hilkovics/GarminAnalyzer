// Header of the detail (title, date, tags), metric tiles, load notices; laps table and load breakdown.
import type { Schemas } from "@/api/client";
import { Badge, Card, Notice, Stat, Table } from "@/components/ui";
import { fmtDate, fmtDurationHms, fmtLoad, fmtNum, fmtPct, sportLabel } from "@/lib/format";

import { speedParts } from "./lib";

type Summary = Schemas["ActivitySummaryDTO"];

export function Header({ s }: { s: Summary }) {
  const tags = [sportLabel(s.sport), s.sub_sport, s.is_race && "preteky", s.is_indoor && "indoor", s.is_commute && "dochádzka"].filter(Boolean) as string[];
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
      <h1 className="text-2xl font-bold sm:text-3xl">
        {s.name || "Aktivita"} · {fmtDate(s.local_date)}
      </h1>
      <ul className="flex flex-wrap gap-1.5" aria-label="Štítky aktivity">
        {tags.map((t, i) => (
          <li key={t}>
            <Badge tone={i === 0 ? "blue" : "gray"}>{t}</Badge>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Tiles({ s }: { s: Summary }) {
  const [speed, speedUnit] = speedParts(s.avg_speed, s.sport);
  const tile = "p-4 sm:p-5";
  return (
    <section className="grid grid-cols-2 overflow-hidden gap-px rounded-xl border border-line bg-line sm:grid-cols-3 lg:grid-cols-6 [&>*]:bg-card">
      <div className={tile}>
        <Stat label="Trvanie" value={fmtDurationHms(s.duration_s)} />
      </div>
      <div className={tile}>
        <Stat label="Vzdialenosť" value={fmtNum(s.distance_m === null ? null : s.distance_m / 1000, 2)} unit={s.distance_m === null ? undefined : "km"} />
      </div>
      <div className={tile}>
        <Stat label={s.sport === "bike" ? "Rýchlosť" : "Tempo"} value={speed} unit={speedUnit} />
      </div>
      <div className={tile}>
        <Stat label="Priem. tep" value={fmtNum(s.avg_hr, 0)} unit={s.avg_hr === null ? undefined : "bpm"} />
      </div>
      <div className={tile}>
        <Stat label="Max. tep" value={fmtNum(s.max_hr, 0)} unit={s.max_hr === null ? undefined : "bpm"} />
      </div>
      <div className={tile}>
        <Stat label="Prevýšenie" value={fmtNum(s.elev_gain_m, 0)} unit={s.elev_gain_m === null ? undefined : "m"} />
      </div>
    </section>
  );
}

export function LoadNotices({ s }: { s: Summary }) {
  if (!s.low_confidence && s.load_primary !== null) return null;
  return (
    <div className="flex flex-col gap-2">
      {s.low_confidence && <Notice tone="yellow">Nízka spoľahlivosť záťaže (pokrytie tepu {fmtPct(s.hr_coverage)}). Hodnoty ber s rezervou.</Notice>}
      {s.load_primary === null && <Notice tone="yellow">Záťaž tejto aktivity je neznáma (chýba tep alebo prah).</Notice>}
    </div>
  );
}

export function LapsCard({ detail }: { detail: Schemas["ActivityDetailDTO"] }) {
  const sport = detail.summary.sport;
  const bike = sport === "bike";
  return (
    <Card title="Kolá" padded={detail.laps.length === 0}>
      {detail.laps.length === 0 ? (
        <p className="text-sm text-muted">Aktivita nemá žiadne kolá.</p>
      ) : (
        <div className="px-4 pb-3 pt-1 sm:px-5">
          <Table
            head={["Kolo", "Trvanie", "Vzdialenosť", bike ? "Rýchlosť" : "Tempo", "Priem. tep", "Max. tep", "Prevýšenie (m)"]}
            align={["left", "right", "right", "right", "right", "right", "right"]}
            rows={detail.laps.map((l) => {
              const [speed, unit] = speedParts(l.avg_speed, sport);
              return [
                l.index,
                fmtDurationHms(l.duration_s),
                l.distance_m === null ? "–" : `${fmtNum(l.distance_m / 1000, 2)} km`,
                unit ? `${speed}${unit === "/km" ? "/km" : ` ${unit}`}` : speed,
                fmtNum(l.avg_hr, 0),
                fmtNum(l.max_hr, 0),
                fmtNum(l.elev_gain_m, 0),
              ];
            })}
          />
        </div>
      )}
    </Card>
  );
}

export function LoadCard({ s }: { s: Summary }) {
  const tiles: [string, string, boolean][] = [
    ["hrTSS", fmtNum(s.hrtss, 0), s.load_method === "hrtss"],
    ["rTSS", fmtNum(s.rtss, 0), s.load_method === "rtss"],
    ["TRIMP (norm.)", fmtNum(s.trimp_norm, 0), s.load_method === "trimp"],
    ["IF (tep)", fmtNum(s.if_hr, 2), false],
    ["IF (tempo)", fmtNum(s.if_pace, 2), false],
  ];
  return (
    <Card title="Záťaž">
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
        {tiles.map(([label, value, primary]) => (
          <div key={label} className={`rounded-lg border p-2.5 ${primary ? "border-accent" : "border-line"} bg-card-2`}>
            <Stat label={label} value={value} />
          </div>
        ))}
      </div>
      <p className="mt-3 text-sm text-muted">
        Primárna záťaž: <b className="num text-text">{fmtLoad(s.load_primary, s.load_method, s.low_confidence)}</b> · Garmin training load:{" "}
        <span className="num text-text">{fmtNum(s.garmin_training_load, 0)}</span>
      </p>
    </Card>
  );
}
