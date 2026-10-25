// Prahy a zóny: threshold history, "Pridať prah" (PUT /settings/thresholds) and today's zone preview.
import { useState, type FormEvent } from "react";

import { useApiMutation, type Schemas } from "@/api/client";
import { Button, Badge, Card, ErrorBox, Notice, Table } from "@/components/ui";
import { fmtDate, fmtNum, fmtPace, fmtPaceS, isoDate, sportLabel } from "@/lib/format";
import { ZONE_COLORS } from "@/lib/labels";

import { Field, INPUT, SelectField, TextField } from "./fields";
import { buildThresholdIn, fmtZoneRange, sourceLabel, type ThresholdValues } from "./forms";

type Settings = Schemas["SettingsDTO"];
type Threshold = Schemas["ThresholdDTO"];

const SPORTS = [
  { value: "run", label: "Beh" },
  { value: "bike", label: "Bicykel" },
];

export function ThresholdHistory({ cfg }: { cfg: Settings }) {
  if (!cfg.thresholds.length) return <Notice>Zatiaľ nie je zadaný žiadny prah. Pridaj prvý nižšie.</Notice>;
  const today = new Set(Object.values(cfg.current).flatMap((t) => (t ? [t.id] : [])));
  return (
    <Table
      head={["Šport", "Platný od", "LTHR (bpm)", "Prahové tempo", "Zdroj", "Platí dnes"]}
      align={["left", "left", "right", "right", "left", "left"]}
      rows={cfg.thresholds.map((t) => [
        sportLabel(t.sport),
        fmtDate(t.valid_from),
        fmtNum(t.lthr, 0),
        fmtPace(t.threshold_speed),
        sourceLabel(t.source),
        today.has(t.id) ? <Badge tone="green">áno</Badge> : "",
      ])}
    />
  );
}

export function AddThreshold({ cfg, onSaved }: { cfg: Settings; onSaved: (message: string) => void }) {
  const speed = cfg.current.run?.threshold_speed;
  const [values, setValues] = useState<ThresholdValues>({
    sport: "run",
    lthr: "",
    pace: speed ? fmtPaceS(1000 / speed) : "",
    validFrom: isoDate(new Date()),
  });
  const [error, setError] = useState<string | null>(null);
  const save = useApiMutation<Schemas["ThresholdIn"], Threshold>("PUT", () => "/settings/thresholds");
  const set = <K extends keyof ThresholdValues>(key: K) => (value: ThresholdValues[K]) => setValues((v) => ({ ...v, [key]: value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    let body: Schemas["ThresholdIn"];
    try {
      body = buildThresholdIn(values);
    } catch (e) {
      setError((e as Error).message);
      return;
    }
    save.mutate(body, {
      onSuccess: () => onSaved(`Prah (${sportLabel(body.sport)}, od ${fmtDate(body.valid_from)}) uložený.`),
    });
  }

  const run = values.sport === "run";
  return (
    <Card title="Pridať prah">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <SelectField label="Šport" value={values.sport} options={SPORTS} onChange={set("sport")} />
          <TextField label="LTHR (bpm)" value={values.lthr} onChange={set("lthr")} unit="bpm" />
          {run ? (
            <TextField label="Prahové tempo (m:ss, iba beh)" value={values.pace} onChange={set("pace")} unit="/km" placeholder="4:10" decimal={false} />
          ) : (
            <div />
          )}
          <Field label="Platný od">
            {(id) => <input id={id} type="date" value={values.validFrom} onChange={(e) => set("validFrom")(e.target.value)} className={INPUT} />}
          </Field>
        </div>
        {run && !values.pace.trim() && (
          <Notice tone="yellow">Bez tempa sa od tohto dátumu nepočíta rTSS ani tempové zóny (len hrTSS).</Notice>
        )}
        {(error || save.error) && <ErrorBox>{error ?? save.error?.message}</ErrorBox>}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={save.isPending}>
            Pridať prah
          </Button>
          {save.isPending && (
            <span className="text-sm text-muted" role="status">
              Ukladám prah a prepočítavam metriky…
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}

function ZoneTable({ title, zones, kind }: { title: string; zones: Schemas["ZoneBoundDTO"][]; kind: "hr" | "pace" }) {
  return (
    <div className="min-w-0">
      <h3 className="mb-1 text-sm font-semibold">{title}</h3>
      <Table
        head={["Zóna", "Rozsah"]}
        rows={zones.map((z) => [
          <span key={z.zone} className="inline-flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: ZONE_COLORS[z.zone] ?? "var(--neutral)" }} />Z{z.zone}
          </span>,
          fmtZoneRange(z.lower, z.upper, kind),
        ])}
      />
    </div>
  );
}

export function ZonePreview({ cfg }: { cfg: Settings }) {
  const tables: { key: string; title: string; zones: Schemas["ZoneBoundDTO"][]; kind: "hr" | "pace" }[] = Object.entries(cfg.hr_zones).map(
    ([sport, zones]) => ({ key: `hr-${sport}`, title: `Tepové zóny – ${sportLabel(sport).toLowerCase()}`, zones, kind: "hr" }),
  );
  if (cfg.pace_zones) tables.push({ key: "pace", title: "Tempové zóny – beh", zones: cfg.pace_zones, kind: "pace" });
  return (
    <Card title="Zóny podľa dnešných prahov">
      {tables.length ? (
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
          {tables.map((t) => (
            <ZoneTable key={t.key} title={t.title} zones={t.zones} kind={t.kind} />
          ))}
        </div>
      ) : (
        <Notice>Bez platného prahu sa zóny nedajú zobraziť.</Notice>
      )}
    </Card>
  );
}
