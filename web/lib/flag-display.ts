/**
 * Trainer-facing labels for the engine's internal flag kinds.
 *
 * Reasoning emits flags like ``hrv_below_baseline`` and ``rhr_trend_up`` —
 * fine as machine-readable kinds, but the trainer reading their roster
 * shouldn't see snake_case metadata. This module is the single source of
 * truth for the readable phrasing, so when a new signal type is added in
 * reasoning.py it gets one row added here and the whole UI updates.
 */

const FLAG_LABELS: Record<string, string> = {
  hrv_below_baseline:      "HRV below baseline",
  hrv_trend_down:          "HRV trending down",
  rhr_above_baseline:      "RHR elevated",
  rhr_trend_up:            "RHR trending up",
  sleep_deficit:           "Sleep deficit",
  sleep_trend_down:        "Sleep eroding",
  rpe_rising:              "RPE rising",
  acwr_high:               "Training load spike",
  acwr_low:                "Under-load",
  training_readiness_low:  "Readiness low",
};

/** Map an engine flag kind to its trainer-facing phrase. Falls back to
 * the raw kind with underscores replaced by spaces and title-cased, so
 * a newly-added engine flag still renders sanely until this map is
 * updated. */
export function flagDisplay(kind: string): string {
  const known = FLAG_LABELS[kind];
  if (known) return known;
  // Defensive fallback: "some_new_kind" -> "Some new kind"
  return kind
    .split("_")
    .map((p, i) => (i === 0 ? p.charAt(0).toUpperCase() + p.slice(1) : p))
    .join(" ");
}
