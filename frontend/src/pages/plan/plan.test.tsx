import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Planned } from "./shared";
import { pushMessage, TodayActions } from "./TodayActions";
import { parseTimeHms } from "./time";

const workout = (patch: Partial<Planned> = {}): Planned =>
  ({ id: 7, date: "2026-10-23", sport: "run", name: "Tempo", status: "planned", missed: false, steps: [], garmin_workout_id: null, ...patch }) as Planned;

function setup(planned: Planned, reply: unknown = {}) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(reply), { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TodayActions workout={planned} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

const lastCall = (m: ReturnType<typeof vi.fn>) => {
  const [url, init] = m.mock.calls.at(-1) as unknown as [string, RequestInit];
  return { url, method: init.method, body: init.body };
};

afterEach(() => vi.unstubAllGlobals());

describe("TodayActions", () => {
  it("Hotovo and Vynechať post the status of the planned workout, without routing fields in the body", async () => {
    const fetchMock = setup(workout());
    fireEvent.click(screen.getByRole("button", { name: /Hotovo/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(lastCall(fetchMock)).toEqual({ url: "/api/plan/7/status", method: "POST", body: '{"status":"done"}' });
    await screen.findByText("Označené ako hotové.");
    fireEvent.click(screen.getByRole("button", { name: /Vynechať/ }));
    await waitFor(() => expect(lastCall(fetchMock).body).toBe('{"status":"skipped"}'));
  });

  it("a closed workout offers only the way back to planned", async () => {
    const fetchMock = setup(workout({ status: "done" }));
    expect(screen.queryByRole("button", { name: /Hotovo/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Späť na plánované/ }));
    await waitFor(() => expect(lastCall(fetchMock).body).toBe('{"status":"planned"}'));
  });

  it("pushes to Garmin and shows the outcome; a failure shows the service message", async () => {
    const fetchMock = setup(workout(), { planned_id: 7, action: "uploaded" });
    fireEvent.click(screen.getByRole("button", { name: /Poslať do Garmin/ }));
    await screen.findByText(/Garmin Connect kalendári/);
    expect(lastCall(fetchMock).url).toBe("/api/plan/7/push");
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Garmin nie je dostupný." }), { status: 502 }));
    fireEvent.click(screen.getByRole("button", { name: /Poslať do Garmin/ }));
    expect((await screen.findByRole("alert")).textContent).toBe("Garmin nie je dostupný.");
  });

  it("a rest day still in Garmin offers to remove it", () => {
    setup(workout({ sport: "rest", garmin_workout_id: 99 }));
    expect(screen.getByRole("button", { name: /Odstrániť z Garmin/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Hotovo/ })).toBeNull();
  });

  it("an updated workout in Garmin is labelled as an update", () => {
    setup(workout({ garmin_workout_id: 99 }));
    expect(screen.getByRole("button", { name: /Aktualizovať v Garmin/ })).toBeTruthy();
  });
});

describe("helpers", () => {
  it("pushMessage covers every action and appends notes", () => {
    expect(pushMessage({ planned_id: 1, action: "deleted" })).toBe("Odstránené z Garmin.");
    expect(pushMessage({ planned_id: 1, action: "updated", notes: ["Poznámka."] })).toMatch(/aktualizovaný\. Poznámka\.$/);
  });

  it("parseTimeHms parses h:mm:ss and m:ss, blank is null, bad input explains itself", () => {
    expect(parseTimeHms("1:45:00")).toBe(6300);
    expect(parseTimeHms("40:00")).toBe(2400);
    expect(parseTimeHms("  ")).toBeNull();
    expect(() => parseTimeHms("1:75:00")).toThrow(/0–59/);
    expect(() => parseTimeHms("abc")).toThrow(/h:mm:ss/);
    expect(() => parseTimeHms("0:00:00")).toThrow(/kladný/);
  });
});

describe("FitnessWeek", () => {
  it("shows the block week, the running time and the K – D – Ľ menu with done items", async () => {
    const { FitnessWeek } = await import("./FitnessWeek");
    render(
      <FitnessWeek
        fitness={{
          block_start: "2026-10-26",
          week_no: 4,
          block_weeks: 12,
          base_s: 6000,
          target_s: 4200,
          run_s: 2100,
          brake: "hold",
          recovery: true,
          test: false,
          menu: [
            { slot: "k", label: "Kvalita", minutes: 35, weekday_minutes: 35, done_date: "2026-11-17" },
            { slot: "d", label: "Dlhší beh", minutes: 45, weekday_minutes: 45, done_date: null },
            { slot: "e", label: "Ľahký beh", minutes: 25, weekday_minutes: 25, done_date: null },
          ],
        }}
      />,
    );
    expect(screen.getByText("Týždeň 4/12")).toBeTruthy();
    expect(screen.getByText(/odľahčený týždeň/)).toBeTruthy();
    expect(screen.getByText("hotovo Ut 17. 11.")).toBeTruthy();
    expect(screen.getByText("45 min")).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("50");
    expect(screen.getByText("bez rastu")).toBeTruthy();
  });
});

describe("BlockProgressCard", () => {
  const snap = (day: string, pace: number, ef: number | null, t5k: number) => ({ day, pace_at_ref_hr: pace, ef, vdot: 50, t5k_s: t5k, t10k_s: t5k * 2.08, reference_date: day, stale: false });
  it("shows the summary, the change from the baseline in the better/worse colour and the check runs", async () => {
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} }); // recharts' container
    const { BlockProgressCard } = await import("./BlockProgress");
    const week = {
      monday: "2026-10-26", week_no: 6, target_s: 6000, run_s: 4800, items_done: 2, brake: null, recovery: false, test: true,
      mean_readiness: 61, mean_sleep_s: 6.5 * 3600, value: { ...snap("2026-11-15", 1000 / 290, 1.6, 1500), stale: true },
      change: { pace_at_ref_hr: 1000 / 290 - 1000 / 300, ef: 0, vdot: 0, t5k_s: -30, t10k_s: -62.4 },
    };
    render(
      <BlockProgressCard
        block={{
          start: "2026-10-05", end: "2026-12-27", block_weeks: 12,
          baseline: snap("2026-10-04", 1000 / 300, 1.6, 1530),
          weeks: [week],
          check_runs: [{ date: "2026-11-11", activity_id: 3, distance_m: 6000, avg_hr: 172, vdot: 48, t5k_s: 1501, t10k_s: 3120 }],
          summary: { final: false, weeks: 6, items_done: 14, items_planned: 18, run_s: 30000, target_s: 36000, brake_weeks: 1, mean_readiness: 60, mean_sleep_s: 6.4 * 3600, green_share: 0.25, change: null },
        }}
      />,
    );
    expect(screen.getByText("Zatiaľ v bloku")).toBeTruthy();
    expect(screen.getByText("14/18")).toBeTruthy();
    expect(screen.getByText("týždeň 1/12")).toBeTruthy();
    const faster = screen.getByText(/−0:10\/km/);  // 5:00 → 4:50 per km
    expect(faster.className).toContain("text-good");
    expect(screen.getByText(/−0:30$/).className).toContain("text-good"); // 5 km 25:30 → 25:00
    expect(screen.getAllByText("bez zmeny").length).toBe(1); // EF unchanged
    expect(screen.getByText("6,00 km")).toBeTruthy();
    expect(screen.getByText(/\* Odhad vychádza z výkonu staršieho ako 60 dní/)).toBeTruthy(); // stale reference
  });
});

describe("Forecast", () => {
  const effect = (patch: object) => ({ status: "reliable", n: 54, min_n: 30, slope: 0.05, ci_low: 0.02, ci_high: 0.08, sleep_typ_s: 7 * 3600, pace_typ: 3.0, ...patch });
  it("explains the sleep effect for each status", async () => {
    const { EffectLine } = await import("./Forecast");
    const { rerender } = render(<EffectLine effect={effect({})} />);
    // 1000/3.0 − 1000/3.05 = 5.46 s/km per hour
    expect(screen.getByText(/každá hodina spánku navyše ≈ 5 s\/km rýchlejšie/)).toBeTruthy();
    rerender(<EffectLine effect={effect({ status: "uncertain" })} />);
    expect(screen.getByText(/zatiaľ nie je preukázateľný \(54 dní\)/)).toBeTruthy();
    rerender(<EffectLine effect={effect({ status: "insufficient", n: 12, slope: null })} />);
    expect(screen.getByText(/zatiaľ málo dát \(12\/30 dní/)).toBeTruthy();
  });
  it("shows the note in the colour of its direction", async () => {
    const { NoteLine } = await import("./Forecast");
    render(<NoteLine note={{ sleep_s: 18000, delta_s_per_km: 11, text: "Po 5:00 spánku … pomalšie" }} />);
    expect(screen.getByText(/Po 5:00 spánku/)).toBeTruthy();
  });
});
