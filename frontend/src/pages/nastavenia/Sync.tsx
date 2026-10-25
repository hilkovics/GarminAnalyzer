// Sync: "Spustiť sync teraz" runs POST /sync synchronously (it can take minutes) and shows the SyncResult.
import { RefreshCw } from "lucide-react";

import { useApiMutation, type Schemas } from "@/api/client";
import { Button, Card, ErrorBox, Notice, Stat } from "@/components/ui";

type Result = Schemas["SyncResultDTO"];

function SyncResult({ result }: { result: Result }) {
  const stats: [string, number][] = [
    ["Nové aktivity", result.activities_new],
    ["Aktualizované", result.activities_updated],
    ["Nezmenené", result.activities_unchanged],
    ["Wellness dni", result.wellness_days],
    ["Čakajúce", result.activities_pending],
    ["Zlyhané", result.activities_failed],
    ["Prepočítané metriky", result.metrics_computed],
    ["Dni PMC", result.pmc_days],
  ];
  return (
    <div className="mt-4 flex flex-col gap-3">
      <Notice tone={result.errors.length ? "yellow" : "green"}>
        {result.errors.length ? "Sync dokončený s chybami." : "Sync dokončený."}
      </Notice>
      <div className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-4">
        {stats.map(([label, value]) => (
          <Stat key={label} label={label} value={value} valueClass="text-2xl" />
        ))}
      </div>
      {result.errors.map((message, i) => (
        <Notice key={i} tone="yellow">
          {message}
        </Notice>
      ))}
    </div>
  );
}

export function SyncPanel() {
  const sync = useApiMutation<void, Result>("POST", () => "/sync");
  return (
    <Card title="Sync">
      <p className="mb-3 text-sm text-muted">
        Stiahne nové aktivity a wellness dáta z Garmin Connect a prepočíta metriky. Môže trvať minúty.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={sync.isPending} onClick={() => sync.mutate()}>
          <RefreshCw size={15} className={sync.isPending ? "animate-spin" : undefined} aria-hidden />
          Spustiť sync teraz
        </Button>
        {sync.isPending && (
          <span className="text-sm text-muted" role="status">
            Synchronizujem s Garmin Connect…
          </span>
        )}
      </div>
      {sync.error && (
        <div className="mt-3">
          <ErrorBox>Sync zlyhal: {sync.error.message}</ErrorBox>
        </div>
      )}
      {sync.data && <SyncResult result={sync.data} />}
    </Card>
  );
}
