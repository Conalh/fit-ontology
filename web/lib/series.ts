/**
 * Series transforms. The API returns raw daily metrics + session rows;
 * the design's trend charts want { day: number, value: number } arrays
 * indexed by days-from-today, plus a 28d baseline { mean, sd }.
 *
 * Doing this on the client keeps the API thin and matches the design's
 * data shape exactly. The reasoning module computes the same baselines
 * server-side for the verdict, but those aren't exposed in the
 * response — we recompute here from the metric series the dashboard
 * already loads.
 */

import type { MetricRow, SessionRow } from "./api";

export interface SeriesPoint {
  day: number;
  value: number;
}

export interface Baseline {
  mean: number;
  sd: number;
}

/** Days between two ISO dates (a - b), rounding to whole days. */
export function daysBetween(a: string, b: string): number {
  const d1 = Date.parse(a);
  const d2 = Date.parse(b);
  return Math.round((d1 - d2) / 86_400_000);
}

/** Build a 28-day series of one metric kind, indexed by day-from-today. */
export function dailySeries(metrics: MetricRow[], kind: string, today: string): SeriesPoint[] {
  const filtered = metrics.filter((m) => m.kind === kind);
  if (filtered.length === 0) return [];
  // Pick the most recent value per day (in case multiple samples leaked through).
  const byDay = new Map<number, number>();
  for (const m of filtered) {
    const day = daysBetween(m.date, today);
    if (day < -27 || day > 0) continue;
    byDay.set(day, m.value);
  }
  const out: SeriesPoint[] = [];
  for (let d = -27; d <= 0; d++) {
    const v = byDay.get(d);
    if (v !== undefined) out.push({ day: d, value: v });
  }
  return out;
}

/** Mean + SD over a series. Population SD (divide by n, not n-1). */
export function baseline(series: SeriesPoint[]): Baseline {
  if (series.length === 0) return { mean: 0, sd: 0 };
  const values = series.map((p) => p.value);
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance = values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length;
  return { mean, sd: Math.sqrt(variance) };
}

/** Daily training load (RPE × duration) keyed by day-from-today. */
export function loadSeries(sessions: SessionRow[], today: string): { day: number; load: number }[] {
  const byDay = new Map<number, number>();
  for (const s of sessions) {
    const day = daysBetween(s.date, today);
    if (day < -27 || day > 0) continue;
    byDay.set(day, (byDay.get(day) ?? 0) + s.duration_min * s.rpe);
  }
  const out: { day: number; load: number }[] = [];
  for (let d = -27; d <= 0; d++) {
    out.push({ day: d, load: byDay.get(d) ?? 0 });
  }
  return out;
}

/** ACWR (acute 7d / chronic 28d daily-mean) per Gabbett. */
export function acwrSeries(sessions: SessionRow[], today: string): SeriesPoint[] {
  const loads = loadSeries(sessions, today);
  const out: SeriesPoint[] = [];
  for (let i = 0; i < loads.length; i++) {
    const acuteWindow = loads.slice(Math.max(0, i - 6), i + 1);
    const chronicWindow = loads.slice(Math.max(0, i - 27), i + 1);
    const acute = acuteWindow.reduce((a, b) => a + b.load, 0) / Math.max(1, acuteWindow.length);
    const chronic = chronicWindow.reduce((a, b) => a + b.load, 0) / Math.max(1, chronicWindow.length);
    const ratio = chronic > 0 ? acute / chronic : 1;
    out.push({ day: loads[i].day, value: Math.round(ratio * 100) / 100 });
  }
  return out;
}

/** Mean of the most recent N values. */
export function recentMean(series: SeriesPoint[], n = 7): number | null {
  if (series.length === 0) return null;
  const slice = series.slice(-n);
  return slice.reduce((a, b) => a + b.value, 0) / slice.length;
}
