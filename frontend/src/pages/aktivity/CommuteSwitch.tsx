// METRICS §2.6: commute or training – automatic (ride < 25 min) or the user's choice.
import { useApiMutation, type Schemas } from "@/api/client";
import { Card, ErrorBox, Segmented } from "@/components/ui";

type Choice = "auto" | "commute" | "training";
const OPTIONS: { value: Choice; label: string }[] = [
  { value: "auto", label: "automaticky" },
  { value: "commute", label: "dochádzka" },
  { value: "training", label: "tréning" },
];
const TO_BODY: Record<Choice, boolean | null> = { auto: null, commute: true, training: false };
const fromOverride = (o: boolean | null | undefined): Choice => (o === true ? "commute" : o === false ? "training" : "auto");

type Body = { _id: number; commute: boolean | null };

export function CommuteSwitch({ summary }: { summary: Schemas["ActivitySummaryDTO"] }) {
  const save = useApiMutation<Body, Schemas["ActivitySummaryDTO"]>("PUT", (b) => `/activities/${b._id}/commute`);
  // While the request runs (and the refresh is on its way) show the choice just made.
  const value = save.isPending && save.variables ? fromOverride(save.variables.commute) : fromOverride(summary.commute_override);
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="label">
          Typ aktivity
        </span>
        <Segmented label="Typ aktivity" value={value} options={OPTIONS} onChange={(c) => save.mutate({ _id: summary.id, commute: TO_BODY[c] })} />
        {summary.commute_override === null || summary.commute_override === undefined ? (
          <span className="text-xs text-muted">Automaticky: {summary.is_commute ? "dochádzka" : "tréning"}.</span>
        ) : null}
      </div>
      <p className="mt-2 text-xs text-muted">
        Dochádzka sa ráta do únavy a formy, ale nie do tréningu (plán, týždenný cieľ, najlepšie úseky, návrhy prahov).
        Automaticky = jazda na bicykli kratšia ako 25 min.
      </p>
      {save.error && (
        <div className="mt-2">
          <ErrorBox error={save.error} />
        </div>
      )}
    </Card>
  );
}
