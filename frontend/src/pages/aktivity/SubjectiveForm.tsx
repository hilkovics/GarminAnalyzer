// Subjective rating of one activity: RPE 1–10, feel 1–5, soreness 0–3, note. A selected value is cleared by
// clicking it again (null = unset); the whole form is saved with one POST.
import { useId, useState } from "react";

import { useApiMutation, type Schemas } from "@/api/client";
import { Button, Card, ErrorBox, Notice, cx } from "@/components/ui";

import { FEEL_LABELS, SORENESS_LABELS } from "./lib";

type Body = Schemas["SubjectiveIn"] & { _id: number };

function Choice({
  label,
  options,
  value,
  onChange,
  titles,
}: {
  label: string;
  options: number[];
  value: number | null;
  onChange: (v: number | null) => void;
  titles?: Record<number, string>;
}) {
  const labelId = useId();
  return (
    <div>
      <div className="mb-1 text-xs text-muted" id={labelId}>
        {label}
      </div>
      <div role="radiogroup" aria-labelledby={labelId} className="flex gap-1.5">
        {options.map((o) => (
          <button
            key={o}
            type="button"
            role="radio"
            aria-checked={o === value}
            title={titles?.[o]}
            onClick={() => onChange(o === value ? null : o)}
            className={cx(
              "num h-9 min-w-0 flex-1 rounded-lg border text-sm font-semibold transition-colors",
              o === value ? "border-accent bg-accent text-accent-text" : "border-line-strong bg-card-2 text-text hover:border-accent",
            )}
          >
            {o}
          </button>
        ))}
      </div>
    </div>
  );
}

const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => from + i);

export function SubjectiveForm({ activityId, current }: { activityId: number; current: Schemas["SubjectiveDTO"] | null }) {
  const [rpe, setRpe] = useState<number | null>(current?.rpe ?? null);
  const [feel, setFeel] = useState<number | null>(current?.feel ?? null);
  const [soreness, setSoreness] = useState<number | null>(current?.soreness ?? null);
  const [notes, setNotes] = useState(current?.notes ?? "");
  const save = useApiMutation<Body, Schemas["SubjectiveDTO"]>("POST", (b) => `/activities/${b._id}/subjective`);
  const edit = <T,>(setter: (v: T) => void) => (v: T) => {
    save.reset();
    setter(v);
  };
  return (
    <Card title="Subjektívne hodnotenie">
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({ _id: activityId, rpe, feel, soreness, notes: notes.trim() || null });
        }}
      >
        <Choice label="RPE (1–10)" options={range(1, 10)} value={rpe} onChange={edit(setRpe)} />
        <div className="grid gap-4 sm:grid-cols-[5fr_4fr]">
          <Choice label="Pocit (1 – veľmi zle … 5 – výborne)" options={range(1, 5)} value={feel} onChange={edit(setFeel)} titles={FEEL_LABELS} />
          <Choice label="Bolestivosť (0–3)" options={range(0, 3)} value={soreness} onChange={edit(setSoreness)} titles={SORENESS_LABELS} />
        </div>
        <div>
          <label htmlFor={`notes-${activityId}`} className="mb-1 block text-xs text-muted">
            Poznámka
          </label>
          <textarea
            id={`notes-${activityId}`}
            value={notes}
            maxLength={2000}
            rows={3}
            onChange={(e) => edit(setNotes)(e.target.value)}
            className="w-full rounded-lg border border-line-strong bg-card-2 px-3 py-2 text-sm text-text"
          />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={save.isPending}>
            Uložiť hodnotenie
          </Button>
          {save.isSuccess && <Notice tone="green">Hodnotenie uložené.</Notice>}
        </div>
        {save.error && <ErrorBox error={save.error} />}
      </form>
    </Card>
  );
}
