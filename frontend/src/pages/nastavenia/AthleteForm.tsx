// Atlét: TRIMP inputs and the run:bike split (PUT /settings/athlete). Empty fields are left unchanged.
import { useState, type FormEvent } from "react";

import { useApiMutation, type Schemas } from "@/api/client";
import { Button, Card, ErrorBox, Segmented } from "@/components/ui";
import { fmtNum } from "@/lib/format";

import { Checkbox, TextField } from "./fields";
import { athleteValues, buildAthleteIn, SEX_LABELS, type AthleteValues } from "./forms";

type Athlete = Schemas["AthleteDTO"];

export function AthleteForm({ athlete, onSaved }: { athlete: Athlete | null; onSaved: (message: string) => void }) {
  const [values, setValues] = useState<AthleteValues>(() => athleteValues(athlete));
  const [error, setError] = useState<string | null>(null);
  const save = useApiMutation<Schemas["AthleteIn"], Athlete>("PUT", () => "/settings/athlete");
  const set = <K extends keyof AthleteValues>(key: K) => (value: AthleteValues[K]) => setValues((v) => ({ ...v, [key]: value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    let body: Schemas["AthleteIn"];
    try {
      body = buildAthleteIn(values, new Date().getFullYear());
    } catch (e) {
      setError((e as Error).message);
      return;
    }
    save.mutate(body, {
      onSuccess: (saved) => {
        setValues(athleteValues(saved));
        onSaved("Údaje atléta uložené.");
      },
    });
  }

  const sexOptions = Object.entries(SEX_LABELS).map(([value, label]) => ({ value, label }));
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Card title="Atlét">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <span className="mb-1 block text-xs text-muted">Pohlavie</span>
              <Segmented label="Pohlavie" value={values.sex} options={sexOptions} onChange={set("sex")} />
            </div>
            <TextField label="Rok narodenia" value={values.birthYear} onChange={set("birthYear")} decimal={false} placeholder="1991" />
            <TextField label="Hmotnosť (kg)" value={values.weight} onChange={set("weight")} unit="kg" placeholder="72,5" />
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <TextField label="Maximálny tep (bpm)" value={values.maxHr} onChange={set("maxHr")} unit="bpm" />
            <TextField
              label="Pokojový tep – ručná hodnota (bpm)"
              value={values.restHr}
              onChange={set("restHr")}
              unit="bpm"
              placeholder="–"
            />
            <TextField label="Podiel behu na týždennej záťaži (%)" value={values.split} onChange={set("split")} unit="%" placeholder="55" />
          </div>
          <Checkbox
            label="Zmazať ručný pokojový tep (použiť 28-dňový medián z Garminu)"
            checked={values.clearRest}
            onChange={set("clearRest")}
            disabled={athlete?.rest_hr_override == null}
          />
          {(error || save.error) && <ErrorBox>{error ?? save.error?.message}</ErrorBox>}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={save.isPending}>
              Uložiť atléta
            </Button>
            {save.isPending && (
              <span className="text-sm text-muted" role="status">
                Ukladám a prepočítavam metriky…
              </span>
            )}
          </div>
        </form>
      </Card>
      <Card>
        <p className="text-sm font-semibold">Pokojový tep použitý dnes: {fmtNum(athlete?.rest_hr_current, 0, "bpm")}</p>
        <p className="mt-1 text-sm text-muted">
          Prázdne polia sa nemenia. Pokojový tep bez ručnej hodnoty je 28-dňový medián z Garminu. Zmena vstupov TRIMP prepočíta všetky
          metriky.
        </p>
      </Card>
    </div>
  );
}
