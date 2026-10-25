import { describe, expect, it } from "vitest";

import { fmtRho, headline, rhoColor, rhoX, statsLine, type Finding } from "./rho";

const base = {
  sport: "run", predictor: "sleep_s_lag0", predictor_base: "sleep_s", variant: "lag0", outcome: "ef", n: 51, status: "ok",
  rho: 0.5, p: 0.01, ci_low: 0.2, ci_high: 0.7, partial_n: null, partial_rho: null, partial_p: null, partial_ci_low: null, partial_ci_high: null,
  q_contrast: null, q_ci_low: null, q_ci_high: null, q_n_bottom: null, q_n_top: null, uncertain: false, headline_rho: 0.5, sentence: "x",
} as Finding;

describe("rho axis", () => {
  it("maps −1 / 0 / +1 across the padded axis and clamps", () => {
    expect(rhoX(-1)).toBe(14);
    expect(rhoX(0)).toBe(150);
    expect(rhoX(1)).toBe(286);
    expect(rhoX(-3)).toBe(14);
    expect(rhoX(2)).toBe(286);
  });

  it("uses the partial ρ as the headline when present, else the raw one", () => {
    expect(headline(base)).toEqual({ rho: 0.5, low: 0.2, high: 0.7 });
    expect(headline({ ...base, partial_rho: 0.46, partial_ci_low: 0.21, partial_ci_high: 0.65 })).toEqual({ rho: 0.46, low: 0.21, high: 0.65 });
  });

  it("formats ρ with sign, decimal comma, real minus and the interval", () => {
    expect(fmtRho(0.346, -0.1, 0.55)).toBe("+0,35 [95 % CI −0,10; +0,55]");
    expect(fmtRho(-0.29)).toBe("−0,29");
    expect(fmtRho(null)).toBe("–");
  });

  it("describes raw-only and partial findings", () => {
    expect(statsLine(base)).toBe("n = 51 · ρ = +0,50 [95 % CI +0,20; +0,70]");
    expect(statsLine({ ...base, partial_rho: -0.29, partial_ci_low: -0.53, partial_ci_high: -0.01 })).toBe(
      "n = 51 · parciálne ρ = −0,29 [95 % CI −0,53; −0,01] · surové ρ = +0,50 [95 % CI +0,20; +0,70]",
    );
  });

  it("mutes uncertain findings and colours the sign otherwise", () => {
    expect(rhoColor(0.4, true)).toBe("var(--neutral)");
    expect(rhoColor(0.4, false)).toBe("var(--accent)");
    expect(rhoColor(-0.4, false)).toBe("var(--bike)");
  });
});
