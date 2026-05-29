import { describe, expect, it } from "vitest";
import type { MetricRow, SessionRow } from "./api";
import {
  acwrSeries,
  baseline,
  dailySeries,
  daysBetween,
  loadSeries,
  recentMean,
  type SeriesPoint,
} from "./series";

const TODAY = "2026-01-28";

function metric(over: { kind: string; date: string; value: number }): MetricRow {
  return { id: "m", source: "test", unit: "", ...over };
}

function session(over: { date: string; duration_min: number; rpe: number }): SessionRow {
  return { id: "s", type: "run", notes: null, ...over };
}

describe("daysBetween", () => {
  it("returns whole-day difference (a - b)", () => {
    expect(daysBetween("2026-01-28", "2026-01-21")).toBe(7);
    expect(daysBetween("2026-01-21", "2026-01-28")).toBe(-7);
    expect(daysBetween("2026-01-28", "2026-01-28")).toBe(0);
  });
});

describe("dailySeries", () => {
  it("indexes by day-from-today, drops other kinds and out-of-window points", () => {
    const metrics = [
      metric({ kind: "hrv", date: "2026-01-27", value: 50 }),
      metric({ kind: "hrv", date: "2026-01-28", value: 55 }),
      metric({ kind: "hrv", date: "2025-12-01", value: 99 }), // >27d ago, excluded
      metric({ kind: "sleep", date: "2026-01-28", value: 7 }), // wrong kind
    ];
    expect(dailySeries(metrics, "hrv", TODAY)).toEqual([
      { day: -1, value: 50 },
      { day: 0, value: 55 },
    ]);
  });

  it("keeps the last sample when a day has duplicates", () => {
    const metrics = [
      metric({ kind: "hrv", date: "2026-01-28", value: 40 }),
      metric({ kind: "hrv", date: "2026-01-28", value: 55 }),
    ];
    expect(dailySeries(metrics, "hrv", TODAY)).toEqual([{ day: 0, value: 55 }]);
  });

  it("returns [] when no metric matches the kind", () => {
    expect(dailySeries([], "hrv", TODAY)).toEqual([]);
  });
});

describe("baseline", () => {
  it("computes mean and population SD", () => {
    const series: SeriesPoint[] = [10, 20, 30, 40].map((value, i) => ({ day: i, value }));
    const { mean, sd } = baseline(series);
    expect(mean).toBe(25);
    expect(sd).toBeCloseTo(11.1803, 3); // sqrt(125)
  });

  it("returns zeros for an empty series", () => {
    expect(baseline([])).toEqual({ mean: 0, sd: 0 });
  });
});

describe("loadSeries", () => {
  it("sums RPE x duration per day across a full 28-day window", () => {
    const sessions = [
      session({ date: "2026-01-28", duration_min: 60, rpe: 5 }), // 300
      session({ date: "2026-01-28", duration_min: 30, rpe: 4 }), // +120 same day
      session({ date: "2026-01-27", duration_min: 50, rpe: 6 }), // 300
    ];
    const out = loadSeries(sessions, TODAY);
    expect(out).toHaveLength(28);
    expect(out[out.length - 1]).toEqual({ day: 0, load: 420 });
    expect(out[out.length - 2]).toEqual({ day: -1, load: 300 });
  });
});

describe("acwrSeries", () => {
  it("returns a ratio of 1 when there is no load", () => {
    const out = acwrSeries([], TODAY);
    expect(out).toHaveLength(28);
    expect(out.every((p) => p.value === 1)).toBe(true);
  });

  it("reflects an acute spike against a sparse chronic load", () => {
    // Single 280-AU session today: acute mean = 280/7 = 40,
    // chronic mean = 280/28 = 10, ratio = 4.0.
    const out = acwrSeries([session({ date: TODAY, duration_min: 56, rpe: 5 })], TODAY);
    expect(out[out.length - 1].value).toBe(4);
  });
});

describe("recentMean", () => {
  it("averages the most recent n values", () => {
    const series: SeriesPoint[] = [1, 2, 3, 4, 5, 6, 7, 8].map((value, i) => ({ day: i, value }));
    expect(recentMean(series, 3)).toBe(7); // (6+7+8)/3
  });

  it("returns null for an empty series", () => {
    expect(recentMean([])).toBeNull();
  });
});
