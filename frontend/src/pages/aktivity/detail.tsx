import { PageHeader } from "@/components/ui";

export default function ActivityDetailPage({ activityId }: { activityId: number }) {
  return <PageHeader title={`Aktivita ${activityId}`} subtitle="pripravuje sa" />;
}
