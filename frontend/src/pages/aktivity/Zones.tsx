// Time in HR / pace zones: horizontal bars Z1 on top, labelled with the zone bounds, time and share.
import type { Schemas } from "@/api/client";
import { Card } from "@/components/ui";
import { fmtDate, fmtDurationHms, fmtNum, fmtPace, fmtPct } from "@/lib/format";
import { ZONE_COLORS } from "@/lib/labels";

import { zoneRange } from "./lib";

type Zone = Schemas["ZoneTimeDTO"];

function ZoneBars({ zones, kind, title }: { zones: Zone[]; kind: "hr" | "pace"; title: string }) {
  const rows = [...zones].sort((a, b) => a.zone - b.zone);
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">Žiadne dáta o zónach (chýba prah alebo tep).</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {rows.map((z) => (
            <li
              key={z.zone}
              className="grid grid-cols-[minmax(0,9.5rem)_1fr_auto] items-center gap-x-3 text-sm sm:grid-cols-[minmax(0,11rem)_1fr_auto]"
              aria-label={`Zóna ${z.zone}, ${zoneRange(z.lower, z.upper, kind)}: ${fmtDurationHms(z.seconds)}, ${fmtPct(z.share)}`}
            >
              <span className="truncate">
                <b className="mr-1.5">Z{z.zone}</b>
                <span className="text-muted">{zoneRange(z.lower, z.upper, kind)}</span>
              </span>
              <span className="h-3.5 overflow-hidden rounded-[3px] bg-card-2">
                <span className="block h-full rounded-[3px]" style={{ width: `${Math.max(0, Math.min(1, z.share)) * 100}%`, background: ZONE_COLORS[z.zone] ?? "var(--neutral)" }} />
              </span>
              <span className="num whitespace-nowrap text-right text-xs sm:text-sm">
                {fmtDurationHms(z.seconds)} · {fmtPct(z.share)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ZonesCard({ detail }: { detail: Schemas["ActivityDetailDTO"] }) {
  const th = detail.threshold;
  if (!th) {
    return (
      <Card title="Čas v zónach">
        <p className="text-sm text-muted">K dátumu aktivity nie je platný žiadny prah – zóny nie sú k dispozícii.</p>
      </Card>
    );
  }
  const pace = th.threshold_speed ? `, prahové tempo ${fmtPace(th.threshold_speed)}` : "";
  return (
    <Card
      title="Čas v zónach"
      right={
        <span className="text-xs text-muted">
          Prah platný od {fmtDate(th.valid_from)}: LTHR {fmtNum(th.lthr, 0, "bpm")}
          {pace}.
        </span>
      }
    >
      <div className={detail.pace_zones ? "grid gap-6 lg:grid-cols-2" : ""}>
        <ZoneBars zones={detail.hr_zones} kind="hr" title="Tepové zóny" />
        {detail.pace_zones && <ZoneBars zones={detail.pace_zones} kind="pace" title="Tempové zóny" />}
      </div>
    </Card>
  );
}
