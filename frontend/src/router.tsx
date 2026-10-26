// Routes (code-based TanStack Router). Each page lives in src/pages/<name>/ and owns its own data hooks.
import { createRootRoute, createRoute, createRouter, useParams } from "@tanstack/react-router";

import { Layout } from "@/app/Layout";
import { NotFound } from "@/app/NotFound";
import ActivitiesPage from "@/pages/aktivity";
import ActivityDetailPage from "@/pages/aktivity/detail";
import DashboardPage from "@/pages/dashboard";
import FitnessPage from "@/pages/fitness";
import SettingsPage from "@/pages/nastavenia";
import PlanPage from "@/pages/plan";
import ProgressPage from "@/pages/progres";
import SleepPage from "@/pages/spanok";
import HealthPage from "@/pages/zdravie";

const root = createRootRoute({ component: Layout, notFoundComponent: NotFound });

function ActivityDetailRoute() {
  const { activityId } = useParams({ from: "/aktivity/$activityId" });
  return <ActivityDetailPage activityId={Number(activityId)} />;
}

const routes = [
  createRoute({ getParentRoute: () => root, path: "/", component: DashboardPage }),
  createRoute({ getParentRoute: () => root, path: "/aktivity", component: ActivitiesPage }),
  createRoute({ getParentRoute: () => root, path: "/aktivity/$activityId", component: ActivityDetailRoute }),
  createRoute({ getParentRoute: () => root, path: "/fitness", component: FitnessPage }),
  createRoute({ getParentRoute: () => root, path: "/progres", component: ProgressPage }),
  createRoute({ getParentRoute: () => root, path: "/zdravie", component: HealthPage }),
  createRoute({ getParentRoute: () => root, path: "/spanok", component: SleepPage }), // old links keep working
  createRoute({ getParentRoute: () => root, path: "/plan", component: PlanPage }),
  createRoute({ getParentRoute: () => root, path: "/nastavenia", component: SettingsPage }),
];

export const router = createRouter({ routeTree: root.addChildren(routes), defaultPreload: "intent" });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
