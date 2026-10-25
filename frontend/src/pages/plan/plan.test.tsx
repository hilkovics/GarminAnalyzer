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
