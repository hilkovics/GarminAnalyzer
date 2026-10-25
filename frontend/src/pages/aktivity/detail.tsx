// Activity detail: summary, commute switch, streams, laps, zones, load breakdown, subjective form.
import { Link, useSearch } from "@tanstack/react-router";

import { useApi, type Schemas } from "@/api/client";
import { ErrorBox, Loading } from "@/components/ui";

import { CommuteSwitch } from "./CommuteSwitch";
import { StreamsCard } from "./StreamsChart";
import { SubjectiveForm } from "./SubjectiveForm";
import { Header, LapsCard, LoadCard, LoadNotices, Tiles } from "./Summary";
import { ZonesCard } from "./Zones";

function Body({ detail }: { detail: Schemas["ActivityDetailDTO"] }) {
  const s = detail.summary;
  return (
    <div className="flex flex-col gap-4">
      <Header s={s} />
      <Tiles s={s} />
      <LoadNotices s={s} />
      <CommuteSwitch summary={s} />
      <StreamsCard activityId={s.id} sport={s.sport} />
      <LapsCard detail={detail} />
      <ZonesCard detail={detail} />
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <LoadCard s={s} />
        <SubjectiveForm key={s.id} activityId={s.id} current={detail.subjective} />
      </div>
    </div>
  );
}

export default function ActivityDetailPage({ activityId }: { activityId: number }) {
  const query = useApi<Schemas["ActivityDetailDTO"]>(`/activities/${activityId}`);
  // The list filters travel in the URL, so "back" returns to the same view.
  const listSearch = useSearch({ strict: false }) as Record<string, unknown>;
  return (
    <>
      <Link to="/aktivity" search={listSearch as never} className="mb-3 inline-block text-sm text-accent hover:underline">
        ← Späť na zoznam
      </Link>
      {query.isPending ? (
        <Loading />
      ) : query.error?.status === 404 ? (
        <ErrorBox>Aktivita {activityId} neexistuje.</ErrorBox>
      ) : query.error || !query.data ? (
        <ErrorBox error={query.error} />
      ) : (
        <Body detail={query.data} />
      )}
    </>
  );
}
