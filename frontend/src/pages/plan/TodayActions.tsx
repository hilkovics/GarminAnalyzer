// Buttons of today's workout card: Hotovo / Vynechať / Späť na plánované, push to Garmin, remove from Garmin.
// Every button is one API call (docs/API.md); the mutations refresh all queries, the message shows the outcome.
import { CircleCheck, CircleMinus, CloudUpload, Trash2, Undo2 } from "lucide-react";

import { useApiMutation } from "@/api/client";
import { Button } from "@/components/ui";

import { FlashNotice, useFlash, type Planned, type PushResult } from "./shared";

export type WorkoutStatus = "done" | "skipped" | "planned";

const PUSH_MESSAGES: Record<string, string> = {
  uploaded: "Tréning je v Garmin Connect kalendári – hodinky ho dostanú pri ďalšej synchronizácii.",
  updated: "Tréning v Garmin Connect kalendári je aktualizovaný.",
  deleted: "Odstránené z Garmin.",
  skipped: "Bez zmeny – v Garmin Connect je už aktuálna verzia.",
};

export function pushMessage(result: PushResult): string {
  const base = PUSH_MESSAGES[result.action] ?? `Garmin: ${result.action}`;
  return result.notes?.length ? `${base} ${result.notes.join(" ")}` : base;
}

export function TodayActions({ workout }: { workout: Planned }) {
  const { flash, ok, fail, clear } = useFlash();
  const setStatus = useApiMutation<{ _id: number; status: WorkoutStatus }, Planned>("POST", (b) => `/plan/${b._id}/status`);
  const push = useApiMutation<{ _id: number }, PushResult>("POST", (b) => `/plan/${b._id}/push`);
  const busy = setStatus.isPending || push.isPending;

  const closed = workout.status === "done" || workout.status === "skipped";
  const inGarmin = workout.garmin_workout_id !== null && workout.garmin_workout_id !== undefined;
  const rest = workout.sport === "rest";

  const mark = (status: WorkoutStatus, text: string) => {
    clear();
    setStatus.mutate({ _id: workout.id, status }, { onSuccess: () => ok(text), onError: fail });
  };
  const send = () => {
    clear();
    push.mutate({ _id: workout.id }, { onSuccess: (result) => ok(pushMessage(result)), onError: fail });
  };

  return (
    <div className="flex flex-col gap-2">
      {rest && inGarmin && !closed && (
        <>
          <p className="text-xs text-muted">Pôvodný tréning je ešte v Garmin Connect kalendári.</p>
          <Button variant="secondary" disabled={busy} onClick={send}>
            <Trash2 size={16} /> Odstrániť z Garmin
          </Button>
        </>
      )}
      {!rest &&
        (closed ? (
          <Button variant="secondary" disabled={busy} onClick={() => mark("planned", "Vrátené na plánované.")}>
            <Undo2 size={16} /> Späť na plánované
          </Button>
        ) : (
          <>
            <Button disabled={busy} onClick={() => mark("done", "Označené ako hotové.")}>
              <CircleCheck size={17} /> Hotovo
            </Button>
            <div className="grid grid-cols-2 gap-2">
              <Button variant="secondary" disabled={busy} onClick={() => mark("skipped", "Označené ako vynechané.")}>
                <CircleMinus size={16} /> Vynechať
              </Button>
              <Button variant="secondary" disabled={busy} onClick={send}>
                <CloudUpload size={16} /> {inGarmin ? "Aktualizovať v Garmin" : "Poslať do Garmin"}
              </Button>
            </div>
            {inGarmin && workout.status === "planned" && (
              <p className="text-xs text-muted">Plán sa zmenil – v Garmin je ešte predchádzajúca verzia, aktualizuj ju.</p>
            )}
          </>
        ))}
      <FlashNotice flash={flash} />
    </div>
  );
}
