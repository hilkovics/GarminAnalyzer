import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Schemas } from "@/api/client";

import { CommuteSwitch } from "./CommuteSwitch";
import ActivitiesPage from "./index";
import { SubjectiveForm } from "./SubjectiveForm";
import { speedParts, zoneRange } from "./lib";

type Summary = Schemas["ActivitySummaryDTO"];

const summary = (over: Partial<Summary> = {}): Summary => ({
  id: 7,
  garmin_id: 1,
  sport: "bike",
  sub_sport: null,
  name: "Ranná jazda",
  local_date: "2026-10-20",
  start_utc: "2026-10-20T05:00:00Z",
  tz: null,
  duration_s: 1200,
  moving_s: 1200,
  distance_m: 8000,
  elev_gain_m: 20,
  avg_hr: 110,
  max_hr: 130,
  avg_speed: 6.67,
  is_race: false,
  is_indoor: false,
  load_primary: null,
  load_method: null,
  hrtss: null,
  rtss: null,
  trimp_norm: null,
  if_hr: null,
  if_pace: null,
  hr_coverage: 1,
  low_confidence: false,
  garmin_training_load: null,
  is_commute: true,
  commute_override: null,
  ...over,
});

const calls: { url: string; init?: RequestInit }[] = [];

function mockFetch(handler: (url: string, init?: RequestInit) => unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify(handler(url, init)), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
}

const wrap = (node: React.ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{node}</QueryClientProvider>
);

beforeEach(() => {
  calls.length = 0;
});
afterEach(() => vi.unstubAllGlobals());

describe("CommuteSwitch", () => {
  it("shows the automatic rule and sends commute=true as the body of PUT /commute", async () => {
    mockFetch(() => summary({ commute_override: true }));
    render(wrap(<CommuteSwitch summary={summary()} />));
    expect(screen.getByText("Automaticky: dochádzka.")).toBeTruthy();
    expect(screen.getByRole("radio", { name: "automaticky" }).getAttribute("aria-checked")).toBe("true");

    fireEvent.click(screen.getByRole("radio", { name: "dochádzka" }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.init?.method === "PUT")!;
    expect(put.url).toBe("/api/activities/7/commute");
    expect(JSON.parse(String(put.init?.body))).toEqual({ commute: true });
  });

  it("sends null to go back to the rule and false for training", async () => {
    mockFetch(() => summary());
    render(wrap(<CommuteSwitch summary={summary({ commute_override: true })} />));
    fireEvent.click(screen.getByRole("radio", { name: "tréning" }));
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ commute: false });
    fireEvent.click(screen.getByRole("radio", { name: "automaticky" }));
    await waitFor(() => expect(calls.some((c) => c.init?.body === '{"commute":null}')).toBe(true));
  });
});

describe("SubjectiveForm", () => {
  it("posts the selection, clears a value by clicking it again and confirms the save", async () => {
    mockFetch(() => ({ id: 1, date: "2026-10-20", activity_id: 7 }));
    render(wrap(<SubjectiveForm activityId={7} current={{ id: 1, date: "2026-10-20", activity_id: 7, rpe: 5, feel: null, soreness: null, notes: null }} />));
    fireEvent.click(screen.getByRole("radio", { name: "5", checked: true })); // clears RPE
    fireEvent.click(screen.getAllByRole("radio", { name: "3" })[0]); // the first group with a "3" is RPE
    fireEvent.change(screen.getByLabelText("Poznámka"), { target: { value: "  ťažké nohy " } });
    fireEvent.click(screen.getByRole("button", { name: "Uložiť hodnotenie" }));
    await waitFor(() => expect(screen.getByText("Hodnotenie uložené.")).toBeTruthy());
    const post = calls.find((c) => c.init?.method === "POST")!;
    expect(post.url).toBe("/api/activities/7/subjective");
    expect(JSON.parse(String(post.init?.body))).toEqual({ rpe: 3, feel: null, soreness: null, notes: "ťažké nohy" });
  });
});

describe("ActivitiesPage", () => {
  it("renders rows with the commute tag and the unknown-load warning and links to the detail", async () => {
    const items = [summary(), summary({ id: 8, sport: "run", name: "Tempo", is_commute: false, avg_speed: 3.5, load_primary: 80, load_method: "hrtss" })];
    mockFetch(() => ({ items, total: 2, page: 1, page_size: 25 }));
    const root = createRootRoute();
    const router = createRouter({
      routeTree: root.addChildren([
        createRoute({ getParentRoute: () => root, path: "/aktivity", component: ActivitiesPage }),
        createRoute({ getParentRoute: () => root, path: "/aktivity/$activityId", component: () => <p>detail stránka</p> }),
      ]),
      history: createMemoryHistory({ initialEntries: ["/aktivity?sport=run"] }),
    });
    render(wrap(<RouterProvider router={router} />));
    await waitFor(() => expect(screen.getAllByText("Ranná jazda").length).toBeGreaterThan(0));
    expect(calls[0].url).toBe("/api/activities?sport=run&page=1&page_size=25");
    expect(screen.getAllByText("Bicykel · dochádzka").length).toBeGreaterThan(0);
    expect(screen.getAllByText("⚠ neznáma").length).toBeGreaterThan(0);
    expect(screen.getAllByText("80 (hrTSS)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("4:46/km").length).toBeGreaterThan(0);
    expect(screen.getAllByText("24,0 km/h").length).toBeGreaterThan(0);

    fireEvent.click(screen.getAllByText("Tempo")[0]);
    await waitFor(() => expect(screen.getByText("detail stránka")).toBeTruthy());
    expect(router.state.location.pathname).toBe("/aktivity/8");
  });
});

describe("lib", () => {
  it("formats speed parts and zone ranges", () => {
    expect(speedParts(1000 / 283, "run")).toEqual(["4:43", "/km"]);
    expect(speedParts(8.5, "bike")).toEqual(["30,6", "km/h"]);
    expect(speedParts(null, "run")).toEqual(["–", ""]);
    expect(zoneRange(116, 143, "hr")).toBe("116–143 bpm");
    expect(zoneRange(null, 116, "hr")).toBe("< 116 bpm");
    expect(zoneRange(179, null, "hr")).toBe("> 179 bpm");
    expect(zoneRange(1000 / 330, 1000 / 290, "pace")).toBe("5:30–4:50/km");
    expect(zoneRange(null, 1000 / 321, "pace")).toBe("pomalšie ako 5:21/km");
    expect(zoneRange(1000 / 238, null, "pace")).toBe("rýchlejšie ako 3:58/km");
  });
});
