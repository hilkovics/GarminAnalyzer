import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fmtMetric, fmtMetricDiff } from "./format";
import { initialTab, toggleKey } from "./index";
import { Relationships } from "./Relationships";
import { Tiles } from "./Tiles";

describe("health format", () => {
  it("formats values by unit", () => {
    expect(fmtMetric(7.5 * 3600, "s")).toBe("7:30 h");
    expect(fmtMetric(14.04, "dych/min")).toMatch(/^14,0/);
    expect(fmtMetricDiff(-1800, "s")).toBe("−0:30 h");
    expect(fmtMetricDiff(3, "bpm")).toMatch(/^\+3/);
    expect(fmtMetric(null, "bpm")).toBe("–");
  });
  it("keeps 1–4 selected metrics and reads the tab from the URL", () => {
    expect(toggleKey(["a"], "a")).toEqual(["a"]);
    expect(toggleKey(["a", "b", "c", "d"], "e")).toEqual(["b", "c", "d", "e"]);
    expect(toggleKey(["a", "b"], "a")).toEqual(["b"]);
    expect(initialTab("?tab=sleep")).toBe("sleep");
    expect(initialTab("?tab=x")).toBe("trends");
  });
});

const metric = (patch: object) => ({
  key: "rhr", label: "Pokojový tep", unit: "bpm", better: "down", latest: 52, latest_date: "2026-10-25", mean7: 52.3, mean28: 51, median28: 50, mad28: 1,
  change: { recent: 52, previous: 50, diff: 2, pct: 0.04, p: 0.01, notable: true, direction: "worse" }, monthly: [], ...patch,
});

describe("Tiles", () => {
  it("shows the 7-day mean, the normal and a notable change in the worse colour", () => {
    const onToggle = vi.fn();
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    render(<Tiles metrics={[metric({})] as never} selected={["rhr"]} onToggle={onToggle} />);
    const tile = screen.getByRole("button", { pressed: true });
    expect(tile.textContent).toContain("52 bpm");
    expect(tile.textContent).toContain("normál 50 bpm");
    expect(screen.getByText(/horšie/).parentElement?.className).toContain("text-bad");
    tile.click();
    expect(onToggle).toHaveBeenCalledWith("rhr");
  });
});

describe("Relationships", () => {
  it("lists findings with ρ, the interval and the contrast in the unit of y, and shows a pair in the charts", () => {
    const onShow = vi.fn();
    const r = { x: "stress_avg", y: "sleep_s", lag: 1, n: 120, rho: -0.42, ci_low: -0.56, ci_high: -0.26, p: 0.0001, finding: true, contrast: -1800, text: "Keď je „Denný stres“ nad tvojím normálom…" };
    render(<Relationships data={{ tested: 300, findings: [r], others: [] }} metrics={[metric({ key: "sleep_s", unit: "s" })] as never} onShow={onShow} />);
    expect(screen.getByText(/Keď je „Denný stres“/)).toBeTruthy();
    expect(screen.getByText(/rozdiel najvyššej a najnižšej štvrtiny dní: −0:30 h/)).toBeTruthy();
    screen.getByRole("button", { name: /V grafe/ }).click();
    expect(onShow).toHaveBeenCalledWith(["stress_avg", "sleep_s"]);
  });
});
