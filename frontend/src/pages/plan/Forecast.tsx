// Predictions (METRICS §11.5): the 7-day readiness outlook with the best days for quality, the personal
// sleep → pace effect and today's morning note. Orientation only – the real decision is made every morning.
import { Moon, Star } from "lucide-react";

import { useApi, type Schemas } from "@/api/client";
import { Card, Notice, QueryState, cx } from "@/components/ui";
import { fmtDayMonth, fmtHours, fmtNum, WEEKDAY_SHORT } from "@/lib/format";
import { readinessBadge } from "@/lib/labels";

import { parseDateWeekday } from "./shared";

type Forecast = Schemas["ForecastDTO"];
type Effect = Schemas["SleepEffectDTO"];

const BAND_CLASSES: Record<string, string> = {
  green: "border-good/50 bg-good/10",
  yellow: "border-warn/50 bg-warn/10",
  red: "border-bad/50 bg-bad/10",
};

/** Seconds per km gained per extra hour of sleep at the typical pace (negative slope → slower). */
function secondsPerHour(effect: Effect): number | null {
  const { slope, pace_typ: v } = effect;
  if (slope === null || slope === undefined || !v || v + slope <= 0) return null;
  return 1000 / v - 1000 / (v + slope);
}

export function EffectLine({ effect }: { effect: Effect }) {
  if (effect.status === "insufficient") {
    return (
      <p className="text-xs text-muted">
        Vplyv spánku na tempo: zatiaľ málo dát ({effect.n}/{effect.min_n} dní s behom pri referenčnom tepe a spánkom).
      </p>
    );
  }
  const perHour = secondsPerHour(effect);
  if (effect.status === "uncertain" || perHour === null) {
    return <p className="text-xs text-muted">Vplyv spánku na tempo zatiaľ nie je preukázateľný ({effect.n} dní) – rozhoduje deň, nie priemer.</p>;
  }
  return (
    <p className="text-xs text-muted">
      Vplyv spánku na tempo ({effect.n} dní): každá hodina spánku navyše ≈ {fmtNum(Math.abs(perHour))} s/km {perHour > 0 ? "rýchlejšie" : "pomalšie"} pri
      rovnakom tepe a únave. Zvyčajne spíš {fmtHours(effect.sleep_typ_s)}.
    </p>
  );
}

export function NoteLine({ note }: { note: Forecast["note"] }) {
  return note ? (
    <Notice tone={note.delta_s_per_km > 0 ? "yellow" : "green"}>
      <span className="inline-flex items-start gap-2">
        <Moon size={15} className="mt-0.5 shrink-0" aria-hidden /> {note.text}
      </span>
    </Notice>
  ) : null;
}

function OutlookStrip({ forecast }: { forecast: Forecast }) {
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7" aria-label="Výhľad pripravenosti na 7 dní">
      {forecast.days.map((d) => {
        const badge = readinessBadge(d.band);
        return (
          <li
            key={d.date}
            className={cx(
              "flex flex-col gap-1 rounded-lg border p-3",
              d.available ? BAND_CLASSES[d.band ?? ""] ?? "border-line bg-card-2" : "border-line bg-card-2 opacity-60",
              d.best && "ring-2 ring-good",
            )}
          >
            <div className="flex items-center justify-between gap-1">
              <span className="text-sm font-bold">
                {WEEKDAY_SHORT[parseDateWeekday(d.date)]} <span className="num text-xs font-normal text-muted">{fmtDayMonth(d.date)}</span>
              </span>
              {d.best && <Star size={15} className="text-good" aria-label="vhodný na kvalitný tréning" />}
            </div>
            <span className="num text-2xl font-semibold">{d.readiness === null || d.readiness === undefined ? "–" : Math.floor(d.readiness)}</span>
            <span className="text-xs text-muted">{d.available ? (d.readiness === null || d.readiness === undefined ? "bez dát" : badge.text) : "voľný deň"}</span>
            <span className="num text-xs text-muted">spánok ~{fmtHours(d.sleep_s)}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function ForecastCard() {
  const forecast = useApi<Forecast>("/plan/forecast");
  return (
    <Card title="Výhľad na 7 dní" right={<span className="text-xs text-muted">orientačne</span>}>
      <QueryState query={forecast}>
        {(f) => {
          const best = f.days.filter((d) => d.best);
          return (
            <div className="flex flex-col gap-3">
              <NoteLine note={f.note} />
              <p className="text-sm text-muted">
                {best.length
                  ? `Najlepšie dni na kvalitný tréning: ${best.map((d) => `${WEEKDAY_SHORT[parseDateWeekday(d.date)]} ${fmtDayMonth(d.date)}`).join(", ")}`
                  : "V najbližších 7 dňoch sa zelený deň nečaká – kvalita príde, keď sa ráno ukáže zelený deň."}{" "}
                Odhad z tvojho typického spánku, pokojového tepu a Body Battery v daný deň týždňa a z bežnej záťaže; skutočné rozhodnutie padá
                každé ráno.
              </p>
              <OutlookStrip forecast={f} />
              <EffectLine effect={f.sleep_effect} />
            </div>
          );
        }}
      </QueryState>
    </Card>
  );
}
