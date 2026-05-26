"""
The reasoning layer.

Rules-based on purpose. For a trainer with one practice, explainable beats
clever — every recommendation carries the source-metric IDs that produced
it so a domain expert can audit and override.

The signals were chosen to match how trainers and sport scientists
actually quantify load and recovery, not just what's easy to compute:

  - HRV trend is measured against a 28-day rolling baseline in SD units
    (Plews, Laursen, et al. 2013, "Training Adaptation and Heart Rate
    Variability in Elite Endurance Athletes," Sports Med 43:773-781).
    Week-vs-week alone is too noisy at the individual level.

  - Acute:Chronic Workload Ratio (ACWR) from session-RPE × duration follows
    Gabbett (2016), "The training-injury prevention paradox." Acute = 7-day
    load sum; chronic = 28-day rolling average of weekly loads. Ratios
    >1.5 carry elevated injury risk; <0.8 indicates detraining.

  - Resting HR drift uses Buchheit (2014) recommendations: a sustained
    5+ bpm rise above 28-day baseline marks autonomic stress, especially
    when paired with reduced HRV.

  - Sleep follows ACSM 11th ed. general adult guidance (7-9h) with a 6h
    floor for "recovery deficit."

  - Progression magnitudes follow ACSM 11e Resistance Training
    Prescription: 2-10% weekly increase when recovery markers are clean,
    deload every 4-6 weeks regardless.

Each signal is graded mild / moderate / severe. The aggregator weighs them
together rather than counting binary flags — one severe signal alone
triggers a deload; two moderate signals do the same; mixed mild signals
yield a conservative progression.

Engine v2 — dual-window trend detection
---------------------------------------

Trend signals (hrv_trend_down / rhr_trend_up / sleep_trend_down) use a
dual-window combiner rather than a single 7-day OLS slope:

  - Acute window: 7-day ordinary least-squares slope, normalised by the
    28-day baseline SD. Responsive to recent changes, but noisy on
    short samples — a ±3-bpm random fluctuation over 7 days can trip
    the severe threshold by chance.

  - Chronic window: 28-day exponentially-weighted moving average (halflife
    10 days), with OLS slope taken on the smoothed series. Damps short-
    window noise so the slope reflects sustained direction. Plews,
    Laursen et al. (2013) explicitly favour rolling-mean windows on the
    order of 4 weeks for monitoring purposes, exactly because the
    7-day variance is too high at the individual level.

  - Combiner (combine_acute_chronic): chronic absence demotes acute by
    one severity band (the noise-suppression rule — Holmes' acute-only
    HRV crash collapses from severe to moderate), chronic dominance
    promotes acute by one (early warning of a slow drift), chronic
    confirmation holds at acute.

  - Level-dominates-trend safety rule: when composite recovery score is
    ≥ 90, every trend signal is demoted one more band before counting.
    The "recovery markers across the board are great but two trends
    are technically firing" UX contradiction (the original Bennet
    screen-test) collapses cleanly with this in place.

The acute thresholds (SLOPE_*_SD_PER_DAY) and chronic thresholds
(CHRONIC_SLOPE_*_SD_PER_DAY) live as separate constants because the
EWMA smoother halves the slope variance — what fires at 0.20 SD/day on
the raw 7-day OLS would barely register on the 28-day EWMA. Both sets
are tunable per client via the thresholds plumbing.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

import pandas as pd

from .ontology import MetricKind, Recommendation

# --- Thresholds (literature-anchored; centralized for trainer override) ---

HRV_BASELINE_DAYS = 28              # Plews & Laursen recommend 21–28d windows; per-client
                                    # tunable via ``baseline_window_days`` threshold
HRV_ACUTE_DAYS = 7
HRV_MILD_SD = 0.5                   # > 0.5 SD below baseline = early stress
HRV_MODERATE_SD = 1.0               # > 1 SD below baseline = clear stress
HRV_SEVERE_SD = 1.5

ACWR_CHRONIC_WEEKS = 4              # 28-day chronic window
ACWR_SAFE_LOW, ACWR_SAFE_HIGH = 0.8, 1.3
ACWR_MODERATE_HIGH = 1.5            # Gabbett "danger zone" boundary
ACWR_SEVERE_HIGH = 1.8

RHR_BASELINE_DAYS = 28
RHR_MILD_BPM = 3
RHR_MODERATE_BPM = 5
RHR_SEVERE_BPM = 8

SLEEP_FLOOR_HOURS = 7.0             # ACSM general adult guideline
SLEEP_DEFICIT_HOURS = 6.0           # severe deficit threshold
SLEEP_SCORE_POOR = 70               # Garmin sleep score < 70 = poor night

RPE_RISE_MILD = 0.7                 # session RPE upward drift session-over-session
RPE_RISE_MODERATE = 1.5

# Garmin Training Readiness (0–100) is Garmin's own composite of recent
# HRV, stress, sleep, recovery time, and acute load. The thresholds
# below collapse Garmin's published color bands — Excellent ≥ 75, High
# 50–74, Moderate 25–49, Low < 25 — into our severity scale. Because
# TR is itself a composite, we treat it as a corroborator: it can
# escalate a borderline call (one mild signal + TR mild → conservative)
# without firing solo as a deload trigger.
TR_MILD = 60                        # below this is "moderate" zone — recovery deficit forming
TR_MODERATE = 45                    # mid-Low Garmin band
TR_SEVERE = 30                      # well into Low band — multi-day under-recovery

# Trend slope thresholds. We compute least-squares slope over the last 7
# days and express it in baseline-SD units per day so the same boundaries
# apply across HRV (ms), RHR (bpm), and sleep (hours). At 0.1 SD/day a
# signal that started "normal" today would be -0.7 SD below baseline a
# week from now — already mild-territory by Plews & Laursen — so it's
# worth flagging before the level signal trips.
SLOPE_MILD_SD_PER_DAY = 0.05
SLOPE_MODERATE_SD_PER_DAY = 0.10
SLOPE_SEVERE_SD_PER_DAY = 0.20

# Chronic-trend (EWMA, 28-day) thresholds. The chronic detector
# applies the smoother *before* OLS so the resulting slope reflects
# sustained direction rather than week-over-week fluctuation. On the
# synthetic dataset that drops the slope-magnitude variance roughly
# in half, so chronic thresholds sit at about half the acute values.
# Calibrated empirically (E3) against the five-client lit roster —
# the goal was to keep chronic firing on the clients designed to need
# it (Macbeth, Quixote: chronic HRV ~0.03-0.05 SD/day) while staying
# silent on the noise-only case (Holmes: chronic HRV 0.001).
CHRONIC_SLOPE_MILD_SD_PER_DAY = 0.02
CHRONIC_SLOPE_MODERATE_SD_PER_DAY = 0.04
CHRONIC_SLOPE_SEVERE_SD_PER_DAY = 0.08

# E4 — Level-dominates-trend safety rule.
#
# When a client's composite recovery score is ≥ this threshold, the
# engine demotes every trend signal (hrv_trend_down / rhr_trend_up /
# sleep_trend_down) by one severity band before the verdict combiner
# runs. Levels-based signals (HRV below baseline, sleep deficit,
# ACWR, RPE rising) are unaffected — if the levels are still good
# AND a level signal is firing, that signal is the truth, not the
# trend reading.
#
# 90 was picked from the original screen-test: Bennet at composite 97
# with two trend signals that the recovery-score narrative
# ("strong recovery markers across the board") visibly contradicted.
# Holmes at composite 86 is intentionally below the threshold — his
# acute HRV drop IS real, just chronic-unconfirmed, and that's
# already handled by E3's combiner. The rule's job is the
# tail-of-the-distribution case where recovery is genuinely
# excellent, not the borderline-good middle.
#
# Tunable per-client via the existing thresholds plumbing (added to
# DEFAULT_THRESHOLDS below). A coach with an outlier athlete who
# runs hot recovery numbers under cumulative load could lower it.
LEVEL_DOMINATES_RECOVERY_FLOOR = 90

# Trend-signal kinds the E4 rule downweights. Spelled out as a set so
# adding a new trend detector (e.g. body-battery trend) is a one-line
# change here, not a hunt across the file.
TREND_SIGNAL_KINDS: frozenset[str] = frozenset({
    "hrv_trend_down",
    "rhr_trend_up",
    "sleep_trend_down",
})

# Progression magnitudes from ACSM 11e Ch. 6 (cardiorespiratory) and
# Ch. 7 (resistance). Conservative end picked when any signal is present.
ACSM_STANDARD_RANGE = (0.05, 0.10)
ACSM_CONSERVATIVE = 0.05
DELOAD_LOAD_CUT = 0.20              # 20% cut; more aggressive than 15% reflects
                                    # recent autoregulation literature for clearly stressed states


# Source authority for each rule. Kept as a dict so the API can serve
# it to the UI (chip tooltips + a methodology footer) rather than each
# rationale string carrying the citation inline — that interrupted the
# reading flow without buying the trainer anything they couldn't see in
# a static reference list.
CITATIONS = {
    # HRV: Plews, Laursen, Stanley, Kilding, Buchheit (2013), Sports Med
    # 43(9):773-781 — "Training Adaptation and Heart Rate Variability in
    # Elite Endurance Athletes: Opening the Door to Effective Monitoring."
    # Earlier copy of this map cited "Plews & Laursen 2017" — the year
    # was wrong (Conal flagged the link going to an off-topic paper);
    # the 2013 paper is the methodology source.
    "hrv":   "Plews & Laursen 2013",
    "rhr":   "Buchheit 2014",
    "sleep": "ACSM 11e §7",
    "acwr":  "Gabbett 2016",
    # RPE: Foster (1998), Med Sci Sports Exerc 30(7):1164-1168 —
    # "Monitoring Training in Athletes With Reference to Overtraining
    # Syndrome." The canonical session-RPE method paper. Earlier copy
    # cited "Foster sRPE 1995" but there is no canonical 1995 Foster
    # paper for sRPE; 1998 is the literature reference.
    "rpe":   "Foster 1998",
}

# Map each emitted flag kind to its citation key. Used by the API so
# the front-end can show "Source: Plews & Laursen 2013" as a tooltip
# on the corresponding flag chip without needing its own copy of this
# routing logic.
FLAG_CITATIONS: dict[str, str] = {
    "hrv_below_baseline":     CITATIONS["hrv"],
    "hrv_trend_down":         CITATIONS["hrv"],
    "rhr_above_baseline":     CITATIONS["rhr"],
    "rhr_trend_up":           CITATIONS["rhr"],
    "sleep_deficit":          CITATIONS["sleep"],
    "sleep_trend_down":       CITATIONS["sleep"],
    "rpe_rising":             CITATIONS["rpe"],
    "acwr_high":              CITATIONS["acwr"],
    "acwr_low":               CITATIONS["acwr"],
    # training_readiness_low is a Garmin proprietary composite, not an
    # academic source — left out of the citations map. The flag still
    # renders, the chip just has no tooltip source.
}


# Severity thresholds the trainer can override per client. The names here
# match the rows in the client_thresholds table; unset rows fall back to
# these defaults. Window-day constants (HRV_BASELINE_DAYS, ACWR_CHRONIC_WEEKS,
# etc.) and progression magnitudes stay global — they're methodology, not
# per-athlete tuning.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "hrv_mild_sd":          HRV_MILD_SD,
    "hrv_moderate_sd":      HRV_MODERATE_SD,
    "hrv_severe_sd":        HRV_SEVERE_SD,
    "acwr_safe_low":        ACWR_SAFE_LOW,
    "acwr_safe_high":       ACWR_SAFE_HIGH,
    "acwr_moderate_high":   ACWR_MODERATE_HIGH,
    "acwr_severe_high":     ACWR_SEVERE_HIGH,
    "rhr_mild_bpm":         RHR_MILD_BPM,
    "rhr_moderate_bpm":     RHR_MODERATE_BPM,
    "rhr_severe_bpm":       RHR_SEVERE_BPM,
    "sleep_floor_hours":    SLEEP_FLOOR_HOURS,
    "sleep_deficit_hours":  SLEEP_DEFICIT_HOURS,
    "sleep_score_poor":     SLEEP_SCORE_POOR,
    "rpe_rise_mild":        RPE_RISE_MILD,
    "rpe_rise_moderate":    RPE_RISE_MODERATE,
    "tr_mild":              TR_MILD,
    "tr_moderate":          TR_MODERATE,
    "tr_severe":            TR_SEVERE,
    "slope_mild_sd_per_day":     SLOPE_MILD_SD_PER_DAY,
    "slope_moderate_sd_per_day": SLOPE_MODERATE_SD_PER_DAY,
    "slope_severe_sd_per_day":   SLOPE_SEVERE_SD_PER_DAY,
    "chronic_slope_mild_sd_per_day":     CHRONIC_SLOPE_MILD_SD_PER_DAY,
    "chronic_slope_moderate_sd_per_day": CHRONIC_SLOPE_MODERATE_SD_PER_DAY,
    "chronic_slope_severe_sd_per_day":   CHRONIC_SLOPE_SEVERE_SD_PER_DAY,
    "level_dominates_recovery_floor":    float(LEVEL_DOMINATES_RECOVERY_FLOOR),
    # Per-client tunable baseline window. 28 days follows Plews & Laursen
    # 2017; some highly-variable athletes benefit from a tighter 14-day
    # window (more responsive to recent state) while very stable elite
    # athletes settle better at 56 days. ``recommend_baseline_window``
    # picks one of {14, 28, 56} from the data; trainers can override.
    "baseline_window_days":      float(HRV_BASELINE_DAYS),
}

BASELINE_WINDOW_CHOICES: tuple[int, ...] = (14, 28, 56)


def _merge_thresholds(overrides: Mapping[str, float] | None) -> dict[str, float]:
    """Compose the per-call threshold dict: defaults shadowed by any
    per-client overrides the caller passes in."""
    if not overrides:
        return DEFAULT_THRESHOLDS.copy()
    merged = DEFAULT_THRESHOLDS.copy()
    merged.update(overrides)
    return merged


Severity = Literal["mild", "moderate", "severe"]


@dataclass
class Signal:
    kind: str
    severity: Severity
    summary: str
    source_metric_ids: list[str] = field(default_factory=list)


@dataclass
class TrendSignalDetail:
    """Per-signal-kind detector diagnostics surfaced to the API for the
    recommendation card's trend chips. Populated whether or not the
    signal actually fired — so the frontend can render an "acute fires
    / chronic doesn't" badge (or vice versa) on a chip the engine
    decided to surface, plus the underlying numbers in the popover.

    All slope/SD fields are absolute magnitudes — direction is implicit
    in the signal kind (hrv_trend_down means down, rhr_trend_up means
    up). The boolean ``acute_fired`` / ``chronic_fired`` flags mean
    "this window's grade was non-None before the combiner ran" — i.e.
    its raw severity crossed the relevant threshold.
    """
    kind: str                       # e.g. "hrv_trend_down"
    acute_window_days: int          # always HRV_ACUTE_DAYS (7) today
    acute_slope_per_day: float | None
    acute_sd_per_day: float | None
    acute_fired: bool
    chronic_window_days: int        # always HRV_CHRONIC_DAYS (28) today
    chronic_slope_per_day: float | None
    chronic_sd_per_day: float | None
    chronic_fired: bool
    chronic_confidence_weight: float


@dataclass
class SlopeResult:
    """Output of ``compute_trend_slope``. Carries enough metadata that
    the caller can decide whether the slope is trustworthy and which
    direction it's pointing.

    Phase-E1 surface: only the OLS path produces results today, and
    ``confidence_weight`` is always 1.0 when n_samples ≥ the helper's
    minimum (4). Phase E2 wires in EWMA which can return weight < 1.0
    on short windows; the consumers already plumb it through so
    landing E2 is a one-file change.

    Fields:
      slope_per_day      Signed slope in metric-units per day. None
                         when the window had too few samples or was
                         degenerate (all-equal x values).
      n_samples          How many daily points contributed.
      source_ids         Metric row IDs feeding the slope — surfaced
                         to the trainer as "the data behind this call."
      method             Which slope estimator produced this result.
                         Lets the verdict combiner weight acute vs
                         chronic differently in E3.
      window_days        The window we tried to use. May be larger
                         than n_samples if the dataset is short — the
                         delta is what confidence_weight reflects.
      confidence_weight  0.0 → ignore; 1.0 → fully trusted. The
                         combiner multiplies severity-grade impact by
                         this weight. E1 emits 1.0 for any valid OLS;
                         E2 will down-weight short EWMA windows.
    """
    slope_per_day: float
    n_samples: int
    source_ids: list[str]
    method: Literal["ols", "ewma"]
    window_days: int
    confidence_weight: float = 1.0


# --- Helpers --------------------------------------------------------------

def _rid() -> str:
    return f"r_{uuid.uuid4().hex[:12]}"


def _as_dates(series: pd.Series) -> pd.Series:
    """Coerce a date-shaped column to a Series of Python ``date`` objects.
    DuckDB returns DATE columns as ``datetime64[ns]`` Timestamps; pandas 2.x
    refuses to compare those directly to Python ``date`` literals."""
    if series.empty:
        return series
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dt.date
    return series


def _window(metrics: pd.DataFrame, kind: str, start: date, end: date) -> pd.DataFrame:
    """Subset metrics to a single kind across [start, end)."""
    if metrics.empty:
        return metrics
    dates = _as_dates(metrics["date"])
    return metrics[(metrics["kind"] == kind) & (dates >= start) & (dates < end)]


def _baseline(metrics: pd.DataFrame, kind: str, today: date, days: int) -> tuple[float | None, float | None, list[str]]:
    """Mean and SD over the ``days`` window ending today (exclusive), plus
    the source IDs that contributed."""
    window = _window(metrics, kind, today - timedelta(days=days), today)
    if window.empty or len(window) < 3:
        return None, None, []
    return float(window["value"].mean()), float(window["value"].std(ddof=0)), window["id"].tolist()


def _recent_mean(metrics: pd.DataFrame, kind: str, today: date, days: int) -> tuple[float | None, list[str]]:
    window = _window(metrics, kind, today - timedelta(days=days), today)
    if window.empty:
        return None, []
    return float(window["value"].mean()), window["id"].tolist()


# Halflife (days) for the EWMA chronic-trend smoother. Ten days means
# the most-recent 10-day block holds ~50% of the total weight; older
# days fade out exponentially. Buchheit (2014) doesn't specify a
# halflife but recommends "windows comparable to the recovery cycle"
# (~1-2 weeks). 10 sits in that band and produces a smoother that
# halves the noise variance of a raw 7-day OLS slope on the synthetic
# dataset. Tunable later, but parameterizing here means the chronic
# detector's threshold tuning (E3) is keyed against this constant.
EWMA_HALFLIFE_DAYS = 10

# Minimum sample count for the EWMA estimator to produce a usable
# confidence weight. Below this the smoother hasn't accumulated enough
# data for the slope-on-smoothed-series to be meaningfully different
# from the OLS one — so we surface a SlopeResult with weight=0 and
# let the combiner ignore it rather than tripping a false signal off
# the smoother's initial conditions. Linear ramp 14 → window_days
# (typically 28) for partial windows.
EWMA_MIN_SAMPLES = 14


def _ols_slope(days_x, values) -> float | None:
    """OLS slope of values vs days_x. Returns None if x-variance is
    zero. Shared by both compute_trend_slope methods so the EWMA path
    and the raw OLS path don't drift apart in numerical details."""
    mean_x = float(days_x.mean())
    mean_y = float(values.mean())
    num = ((days_x - mean_x) * (values - mean_y)).sum()
    den = ((days_x - mean_x) ** 2).sum()
    if den == 0:
        return None
    return float(num / den)


def compute_trend_slope(
    metrics: pd.DataFrame,
    kind: str,
    today: date,
    *,
    method: Literal["ols", "ewma"] = "ols",
    window_days: int = 7,
) -> SlopeResult | None:
    """Estimate a per-day slope of a metric across a trailing window.

    The shared seam for the engine's trend detectors. Two methods:

      ``ols``  Acute detector (default). Ordinary least-squares slope
               of value-vs-day-index on the raw 7-day window. Fast,
               responsive to recent changes, but noisy on synthetic
               data — a ±3-bpm random fluctuation over 7 points can
               trip a 0.20 SD/day slope by chance. This is the
               original engine's detector, extracted from inline.

      ``ewma`` Chronic detector. EWMA-smooths the value series first
               (halflife=10 days, see EWMA_HALFLIFE_DAYS) and then
               takes the OLS slope on the *smoothed* series. The
               smoothing damps short-window noise so a slope at this
               layer reflects a sustained direction rather than a
               recent fluctuation. Recommended window is 28 days;
               shorter windows produce a weight < 1.0 (or 0 if too
               short) so the combiner can ignore them gracefully.

    Both paths return the same ``SlopeResult`` shape so the E3 verdict
    combiner can treat them uniformly.

    Args:
        metrics: long-format wearable dataframe.
        kind: metric kind (e.g. MetricKind.HRV_RMSSD.value).
        today: reference date — window is [today - window_days, today).
        method: ``"ols"`` for acute, ``"ewma"`` for chronic.
        window_days: window length in days. Defaults to 7 (matches
            the historical acute behaviour); chronic callers pass 28.

    Returns:
        ``SlopeResult`` on success, ``None`` if the window is too
        short or degenerate (zero x-variance). EWMA results with
        ``n_samples < EWMA_MIN_SAMPLES`` are still returned but with
        ``confidence_weight = 0.0`` so the caller can decide whether
        to drop them.
    """
    if method not in ("ols", "ewma"):
        raise ValueError(f"unknown trend slope method: {method!r}")

    window = _window(metrics, kind, today - timedelta(days=window_days), today)
    if len(window) < 4:
        return None
    df = window.sort_values("date")
    dates = pd.to_datetime(df["date"])
    days_x = (dates - dates.iloc[0]).dt.days.astype(float).to_numpy()
    raw_values = df["value"].astype(float).to_numpy()

    if method == "ols":
        slope = _ols_slope(days_x, raw_values)
        if slope is None:
            return None
        return SlopeResult(
            slope_per_day=slope,
            n_samples=len(df),
            source_ids=df["id"].tolist(),
            method="ols",
            window_days=window_days,
            confidence_weight=1.0,
        )

    # EWMA path: smooth then OLS-slope on the smoothed series. The
    # smoother is applied to value order (sorted by date above) so the
    # exponential weighting respects time, not row order.
    smoothed = pd.Series(raw_values).ewm(halflife=EWMA_HALFLIFE_DAYS).mean().to_numpy()
    slope = _ols_slope(days_x, smoothed)
    if slope is None:
        return None

    # Confidence weight: 0 if we don't have enough samples for the
    # smoother to stabilise; linearly ramped from 0 → 1 across
    # [EWMA_MIN_SAMPLES, window_days]; 1.0 at a full window. The
    # combiner multiplies severity by this weight, so a 5-day EWMA on
    # a newly-onboarded client effectively contributes nothing — and
    # the acute (OLS) signal carries the verdict alone, as intended.
    n = len(df)
    if n < EWMA_MIN_SAMPLES:
        weight = 0.0
    elif n >= window_days:
        weight = 1.0
    else:
        weight = (n - EWMA_MIN_SAMPLES) / max(1, window_days - EWMA_MIN_SAMPLES)
    return SlopeResult(
        slope_per_day=slope,
        n_samples=n,
        source_ids=df["id"].tolist(),
        method="ewma",
        window_days=window_days,
        confidence_weight=float(weight),
    )


def _trend_severity(sd_per_day: float, th: Mapping[str, float]) -> Severity | None:
    """Map an absolute SD/day slope magnitude to a severity bucket using
    the *acute* (7-day OLS) thresholds. The acute detector's job is
    early warning, so its thresholds are deliberately sensitive.
    The chronic detector uses tighter thresholds — see
    ``_chronic_trend_severity``."""
    if sd_per_day >= th["slope_severe_sd_per_day"]:
        return "severe"
    if sd_per_day >= th["slope_moderate_sd_per_day"]:
        return "moderate"
    if sd_per_day >= th["slope_mild_sd_per_day"]:
        return "mild"
    return None


def _chronic_trend_severity(
    sd_per_day: float, th: Mapping[str, float],
) -> Severity | None:
    """Map an absolute SD/day slope magnitude to a severity bucket
    using the *chronic* (28-day EWMA) thresholds. Calibrated against
    the synthetic dataset to fire on real sustained drift while
    staying silent on the noise-floor that acute trips over.
    """
    if sd_per_day >= th["chronic_slope_severe_sd_per_day"]:
        return "severe"
    if sd_per_day >= th["chronic_slope_moderate_sd_per_day"]:
        return "moderate"
    if sd_per_day >= th["chronic_slope_mild_sd_per_day"]:
        return "mild"
    return None


# E3: acute (7-day OLS) and chronic (28-day EWMA) severity grades
# combine into one final grade per signal kind. The combiner encodes
# three rules; the decision table below is what they produce.
#
# Rules (apply in order):
#   1. If chronic is silent (none), the acute reading is unconfirmed.
#      Demote it by one band — a noise-driven acute that the chronic
#      detector doesn't see is most likely just noise. This is the
#      headline fix for the Holmes case: HRV acute severe + chronic
#      flat collapses to moderate.
#   2. If chronic is stronger than acute (e.g. mild acute + moderate
#      chronic), promote acute by one band. The chronic detector is
#      seeing a slow drift the acute window can't fully resolve yet —
#      surfacing it gives the trainer early warning.
#   3. Otherwise (chronic confirms acute at the same or weaker level),
#      hold at the acute reading. The chronic doesn't have to MATCH
#      acute to confirm — it just has to be non-zero in the same
#      direction. A severe acute + mild chronic is "the trend is real,
#      acute is showing the acute phase of it" → keep severe.
#
# Decision table the rules produce (matches the docstring above):
#
#   Acute    Chronic   →  Final     Notes
#   severe   severe       severe    full agreement
#   severe   moderate     severe    chronic confirms acute
#   severe   mild         severe    chronic confirms direction
#   severe   none         moderate  noise-only acute, demote (rule 1)
#   moderate severe       severe    chronic-led, promote (rule 2)
#   moderate moderate     moderate  consistent
#   moderate mild         moderate  chronic confirms
#   moderate none         mild      acute-only, demote (rule 1)
#   mild     severe       moderate  promote (rule 2)
#   mild     moderate     moderate  promote (rule 2)
#   mild     mild         mild      both weak, hold
#   mild     none         none      acute-only weak signal, suppress (rule 1)
#   none     severe       mild      chronic-only, surface weakly
#   none     moderate     none      chronic alone too weak below severe
#   none     mild         none      noise
#   none     none         none      clean
#
# Ranking levels low→high: none(0) → mild(1) → moderate(2) → severe(3).
_SEVERITY_RANK: dict[Severity | None, int] = {
    None: 0, "mild": 1, "moderate": 2, "severe": 3,
}
_RANK_SEVERITY: list[Severity | None] = [None, "mild", "moderate", "severe"]


def _demote_one_band(s: Severity) -> Severity | None:
    """Drop a severity by one band. mild → none (which the caller maps
    to dropping the signal). Used by the E4 level-dominates-trend rule.
    """
    if s == "severe":
        return "moderate"
    if s == "moderate":
        return "mild"
    return None  # mild → drop


def _apply_level_dominates(signals: list[Signal]) -> tuple[list[Signal], int]:
    """E4: demote every trend signal in ``signals`` by one severity
    band. Signals demoted from mild → none are dropped from the
    returned list entirely; the trainer doesn't need to see a
    "would-have-fired-but-suppressed" chip on top of a Standard
    verdict (the rationale sentence captures the rule firing).

    Returns (filtered_signals, n_demoted_or_dropped).
    """
    out: list[Signal] = []
    n_changed = 0
    for s in signals:
        if s.kind not in TREND_SIGNAL_KINDS:
            out.append(s)
            continue
        new_severity = _demote_one_band(s.severity)
        if new_severity != s.severity:
            n_changed += 1
        if new_severity is None:
            continue  # dropped below threshold; suppress entirely
        out.append(Signal(
            kind=s.kind,
            severity=new_severity,
            summary=s.summary,
            source_metric_ids=s.source_metric_ids,
        ))
    return out, n_changed


def combine_acute_chronic(
    acute: Severity | None,
    chronic: Severity | None,
) -> Severity | None:
    """Combine acute and chronic severity grades into a final grade
    per the E3 decision table.

    Three principles encoded:
      - **Acute alone is noise-prone.** When acute fires but chronic
        is silent, demote the final by one band. Holmes' HRV (acute
        severe, chronic flat) drops to moderate; an acute mild without
        chronic backing suppresses to none entirely.
      - **Chronic stronger than acute = early warning of a slow drift.**
        Promote acute by one band when chronic is on a higher tier —
        the chronic detector is seeing what the acute window can't yet.
      - **Chronic confirms acute even at a weaker level.** A severe
        acute + mild chronic isn't "partial confirmation, demote" — it's
        "sustained trend in acute phase, hold severe."

    See the lookup table comment above for the full 4×4 mapping.
    """
    a = _SEVERITY_RANK[acute]
    c = _SEVERITY_RANK[chronic]
    if a == 0 and c == 0:
        return None
    if a == 0:
        # Chronic-only: severe → mild surface, weaker → none.
        return "mild" if c == 3 else None
    if c == 0:
        # Acute-only: demote by one band. severe→moderate, mod→mild,
        # mild→none. The headline noise-suppression rule.
        return _RANK_SEVERITY[max(0, a - 1)]
    if c > a:
        # Chronic stronger: promote acute by one band, cap at severe.
        return _RANK_SEVERITY[min(3, a + 1)]
    # Chronic confirms acute at same or lower tier: trust the acute.
    return _RANK_SEVERITY[a]


# --- Per-signal detectors -------------------------------------------------

def detect_hrv_signal(
    metrics: pd.DataFrame,
    today: date,
    thresholds: Mapping[str, float] | None = None,
) -> Signal | None:
    """Acute HRV mean vs 28-day baseline, expressed in baseline-SD units.

    Plews & Laursen (2017): individual HRV reactivity is best measured
    against the athlete's own 21–28 day rolling baseline, not against
    population norms or simple week-over-week deltas. We use the more
    stable 28-day window.

    HRV metric selection: Garmin / Whoop report RMSSD; Apple Health
    reports SDNN. They measure different things but the SD-deviation-
    from-baseline reasoning is within-subject and within-metric, so
    whichever one this client has is fine. We prefer RMSSD when both
    exist (more common in sport-science literature), falling back to
    SDNN. Mixing the two within a single signal would distort baselines.
    """
    th = _merge_thresholds(thresholds)
    hrv_kind = MetricKind.HRV_RMSSD.value
    if (
        (metrics.empty or hrv_kind not in metrics["kind"].values)
        and not metrics.empty
        and MetricKind.HRV_SDNN.value in metrics["kind"].values
    ):
        hrv_kind = MetricKind.HRV_SDNN.value

    baseline_days = int(th["baseline_window_days"])
    acute, acute_ids = _recent_mean(metrics, hrv_kind, today, HRV_ACUTE_DAYS)
    baseline_mean, baseline_sd, baseline_ids = _baseline(
        metrics, hrv_kind, today, baseline_days
    )
    if acute is None or baseline_mean is None or not baseline_sd:
        return None

    drop_sd = (baseline_mean - acute) / baseline_sd
    if drop_sd < th["hrv_mild_sd"]:
        return None

    severity: Severity = (
        "severe" if drop_sd >= th["hrv_severe_sd"]
        else "moderate" if drop_sd >= th["hrv_moderate_sd"]
        else "mild"
    )
    return Signal(
        kind="hrv_below_baseline",
        severity=severity,
        summary=(
            f"HRV averaged {acute:.0f} ms over the last {HRV_ACUTE_DAYS} days "
            f"vs. a {baseline_days}-day baseline of {baseline_mean:.0f} ms "
            f"(-{drop_sd:.1f} SD)."
        ),
        source_metric_ids=list({*acute_ids, *baseline_ids}),
    )


def detect_rhr_signal(
    metrics: pd.DataFrame,
    today: date,
    thresholds: Mapping[str, float] | None = None,
) -> Signal | None:
    """Resting HR rise above the 28-day baseline. Buchheit (2014): a
    sustained 5+ bpm elevation indicates autonomic stress, particularly
    when paired with depressed HRV."""
    th = _merge_thresholds(thresholds)
    baseline_days = int(th["baseline_window_days"])
    acute, acute_ids = _recent_mean(metrics, MetricKind.RESTING_HR.value, today, HRV_ACUTE_DAYS)
    baseline_mean, _baseline_sd, baseline_ids = _baseline(
        metrics, MetricKind.RESTING_HR.value, today, baseline_days
    )
    if acute is None or baseline_mean is None:
        return None

    rise = acute - baseline_mean
    if rise < th["rhr_mild_bpm"]:
        return None

    severity: Severity = (
        "severe" if rise >= th["rhr_severe_bpm"]
        else "moderate" if rise >= th["rhr_moderate_bpm"]
        else "mild"
    )
    return Signal(
        kind="rhr_above_baseline",
        severity=severity,
        summary=(
            f"Resting HR averaged {acute:.0f} bpm over the last {HRV_ACUTE_DAYS} days "
            f"vs. a {baseline_days}-day baseline of {baseline_mean:.0f} bpm "
            f"(+{rise:.0f} bpm)."
        ),
        source_metric_ids=list({*acute_ids, *baseline_ids}),
    )


def detect_sleep_signal(
    metrics: pd.DataFrame,
    today: date,
    thresholds: Mapping[str, float] | None = None,
) -> Signal | None:
    """Mean sleep duration over the last 7 days against ACSM 11e
    7-9 h guidance, with a 6 h "severe deficit" floor. Also folds in
    Garmin's sleep score when present (< 70 = poor)."""
    th = _merge_thresholds(thresholds)
    acute_hours, hour_ids = _recent_mean(metrics, MetricKind.SLEEP_HOURS.value, today, HRV_ACUTE_DAYS)
    acute_score, score_ids = _recent_mean(metrics, MetricKind.SLEEP_SCORE.value, today, HRV_ACUTE_DAYS)
    if acute_hours is None and acute_score is None:
        return None

    severity: Severity | None = None
    parts: list[str] = []

    if acute_hours is not None:
        if acute_hours < th["sleep_deficit_hours"]:
            severity = "severe"
        elif acute_hours < th["sleep_floor_hours"]:
            severity = "moderate"
        # Count how many nights were actually below the floor — the mean
        # hides the shape ("6.8 average" can mean five 8h nights and two
        # 4h nights; the latter is the real signal).
        hour_window = _window(
            metrics, MetricKind.SLEEP_HOURS.value,
            today - timedelta(days=HRV_ACUTE_DAYS), today,
        )
        nights = len(hour_window)
        below_floor = int((hour_window["value"] < th["sleep_floor_hours"]).sum())
        if nights > 0 and below_floor > 0:
            parts.append(
                f"averaged {acute_hours:.1f} h/night with {below_floor} of {nights} "
                f"nights below the {th['sleep_floor_hours']:.0f} h floor"
            )
        else:
            parts.append(f"averaged {acute_hours:.1f} h/night")

    if acute_score is not None and acute_score < th["sleep_score_poor"]:
        severity = "moderate" if severity is None or severity == "mild" else severity
        parts.append(f"Garmin sleep score {acute_score:.0f}")

    if severity is None:
        return None

    return Signal(
        kind="sleep_deficit",
        severity=severity,
        summary=f"Sleep {'; '.join(parts)}.",
        source_metric_ids=list({*hour_ids, *score_ids}),
    )


def _session_load(sessions: pd.DataFrame) -> tuple[pd.Series, dict[date, list[str]]]:
    """Session load = RPE × duration (Foster's sRPE method). Returns
    a tuple of:
      - a Series indexed by date with the daily summed load
      - a dict mapping each date to the session IDs that fed that load

    The dict closes the audit trail for ACWR / RPE signals — without
    it, those signals couldn't cite which sessions drove them.
    """
    if sessions.empty:
        return pd.Series(dtype=float), {}
    s = sessions.copy()
    s["date"] = _as_dates(s["date"])
    s["load"] = s["rpe"].astype(float) * s["duration_min"].astype(float)
    loads = s.groupby("date")["load"].sum()
    if "id" in s.columns:
        ids_by_date = s.groupby("date")["id"].apply(list).to_dict()
    else:
        ids_by_date = {}
    return loads, ids_by_date


def detect_acwr_signal(
    sessions: pd.DataFrame,
    today: date,
    thresholds: Mapping[str, float] | None = None,
) -> Signal | None:
    """Acute:Chronic Workload Ratio per Gabbett (2016).

    Acute = sum of session loads over the last 7 days.
    Chronic = mean weekly load across the last 28 days (i.e., a 4-week
              moving average of weekly load).

    Sweet spot is 0.8–1.3. Ratios > 1.5 elevated injury risk; > 1.8 high.
    Ratios < 0.8 flag detraining (mild signal — under-load is not a
    deload trigger but is worth surfacing to a trainer).
    """
    th = _merge_thresholds(thresholds)
    loads, ids_by_date = _session_load(sessions)
    if loads.empty:
        return None

    acute_window = [d for d in loads.index if (today - d).days <= HRV_ACUTE_DAYS and (today - d).days >= 0]
    chronic_window = [d for d in loads.index if (today - d).days <= ACWR_CHRONIC_WEEKS * 7 and (today - d).days >= 0]

    if not acute_window or not chronic_window:
        return None

    acute_total = float(loads.loc[acute_window].sum())
    weekly_chronic = float(loads.loc[chronic_window].sum()) / ACWR_CHRONIC_WEEKS
    if weekly_chronic <= 0:
        return None

    # All session IDs in the chronic window — that's the data the
    # detector reasoned over. Sufficient for audit; the trainer can
    # filter by date in the dashboard if they want to drill in further.
    contributing_ids = [sid for d in chronic_window for sid in ids_by_date.get(d, [])]

    ratio = acute_total / weekly_chronic
    severity: Severity | None = None

    if ratio >= th["acwr_severe_high"]:
        severity = "severe"
    elif ratio >= th["acwr_moderate_high"]:
        severity = "moderate"
    elif ratio > th["acwr_safe_high"]:
        severity = "mild"
    elif ratio < th["acwr_safe_low"]:
        # Under-load. Mild signal so it shows up in the rationale without
        # triggering a deload; trainers may want to increase volume.
        return Signal(
            kind="acwr_low",
            severity="mild",
            summary=(
                f"ACWR {ratio:.2f} (acute {acute_total:,.0f} AU vs. weekly chronic "
                f"{weekly_chronic:,.0f} AU) — below the 0.8–1.3 safe zone, possible "
                f"detraining."
            ),
            source_metric_ids=contributing_ids,
        )

    if severity is None:
        return None

    return Signal(
        kind="acwr_high",
        severity=severity,
        summary=(
            f"ACWR {ratio:.2f} (acute {acute_total:,.0f} AU vs. weekly chronic "
            f"{weekly_chronic:,.0f} AU) — above the 0.8–1.3 safe zone."
        ),
        source_metric_ids=contributing_ids,
    )


def detect_rpe_signal(
    sessions: pd.DataFrame,
    today: date,
    thresholds: Mapping[str, float] | None = None,
) -> Signal | None:
    """Session-RPE drift: last-week mean RPE vs prior-week mean. A rising
    RPE at constant volume indicates undertrained recovery."""
    if sessions.empty:
        return None
    th = _merge_thresholds(thresholds)
    s = sessions.copy()
    s["date"] = _as_dates(s["date"])
    last_week = s[(s["date"] > today - timedelta(days=7)) & (s["date"] <= today)]
    prior_week = s[(s["date"] > today - timedelta(days=14)) & (s["date"] <= today - timedelta(days=7))]
    if last_week.empty or prior_week.empty:
        return None

    last_mean = float(last_week["rpe"].mean())
    prior_mean = float(prior_week["rpe"].mean())
    rise = last_mean - prior_mean

    if rise < th["rpe_rise_mild"]:
        return None

    severity: Severity = "moderate" if rise >= th["rpe_rise_moderate"] else "mild"
    # All sessions from both compared weeks form the audit set.
    contributing_ids: list[str] = []
    if "id" in s.columns:
        contributing_ids = list(last_week["id"]) + list(prior_week["id"])
    return Signal(
        kind="rpe_rising",
        severity=severity,
        summary=(
            f"Session RPE rose from {prior_mean:.1f} to {last_mean:.1f} across the last "
            f"two weeks (+{rise:.1f})."
        ),
        source_metric_ids=contributing_ids,
    )


def _hrv_kind(metrics: pd.DataFrame) -> str:
    """Pick HRV metric kind to reason over — RMSSD if present, else SDNN.
    Centralized so the level and trend detectors agree."""
    if metrics.empty:
        return MetricKind.HRV_RMSSD.value
    if MetricKind.HRV_RMSSD.value in metrics["kind"].values:
        return MetricKind.HRV_RMSSD.value
    if MetricKind.HRV_SDNN.value in metrics["kind"].values:
        return MetricKind.HRV_SDNN.value
    return MetricKind.HRV_RMSSD.value


# Chronic-trend window. 28 days matches Plews & Laursen 2013's
# recommendation for rolling-mean HRV monitoring (≈4 weeks of data
# smooths out training-week boundaries). Engine v2 / E3.
HRV_CHRONIC_DAYS = 28


def _dual_window_trend(
    metrics: pd.DataFrame,
    kind: str,
    today: date,
    th: Mapping[str, float],
    *,
    direction: Literal["down", "up"],
) -> tuple[Severity | None, SlopeResult | None, SlopeResult | None, float | None]:
    """Compute acute + chronic detectors for one signal kind and
    combine their severities via the E3 decision table. Returns the
    combined severity, both raw SlopeResults (for the caller's
    rationale string), and the acute-window SD/day value (the number
    the trainer is used to seeing in the rationale).

    ``direction`` is the concerning sign: "down" for HRV/sleep (where
    a falling slope is bad), "up" for RHR (where rising is bad). The
    helper folds the sign check in so the three detectors stay
    one-liners around it.
    """
    _, baseline_sd, _ = _baseline(metrics, kind, today, int(th["baseline_window_days"]))
    if not baseline_sd:
        return None, None, None, None

    acute = compute_trend_slope(
        metrics, kind, today, method="ols", window_days=HRV_ACUTE_DAYS,
    )
    chronic = compute_trend_slope(
        metrics, kind, today, method="ewma", window_days=HRV_CHRONIC_DAYS,
    )

    def _grade(
        sr: SlopeResult | None,
        *,
        method: Literal["acute", "chronic"],
    ) -> Severity | None:
        if sr is None:
            return None
        # Direction check: rule out slopes pointing the "good" way.
        if direction == "down" and sr.slope_per_day >= 0:
            return None
        if direction == "up" and sr.slope_per_day <= 0:
            return None
        # Chronic with weight=0 (insufficient samples) is reported as
        # silent so the combiner falls back to acute-only. The acute
        # detector doesn't use confidence_weight (the 7-day window
        # either has enough data or returns None).
        if method == "chronic" and sr.confidence_weight <= 0.0:
            return None
        sd_per_day = abs(sr.slope_per_day) / baseline_sd
        return (
            _trend_severity(sd_per_day, th)
            if method == "acute"
            else _chronic_trend_severity(sd_per_day, th)
        )

    acute_severity = _grade(acute, method="acute")
    chronic_severity = _grade(chronic, method="chronic")
    combined = combine_acute_chronic(acute_severity, chronic_severity)

    # The legacy summary string reports the acute SD/day even when the
    # combiner downgraded from severe → moderate — that's the number
    # the trainer recognizes from the chart. E5 will surface chronic
    # context alongside.
    acute_sd: float | None = None
    if acute is not None and baseline_sd:
        acute_sd = abs(acute.slope_per_day) / baseline_sd

    return combined, acute, chronic, acute_sd


# E5: per-kind trend diagnostics surfaced to the API so the
# recommendation card can render acute/chronic distinction on its
# chips. Each TrendSignalDetail carries enough numbers to populate
# both the badge and the popover, without the frontend needing a
# second round-trip.
_TREND_KIND_MAPPING: tuple[tuple[str, Literal["down", "up"], str], ...] = (
    (MetricKind.HRV_RMSSD.value, "down", "hrv_trend_down"),
    (MetricKind.RESTING_HR.value, "up", "rhr_trend_up"),
    (MetricKind.SLEEP_HOURS.value, "down", "sleep_trend_down"),
)


def _fired_in_direction(
    sr: SlopeResult | None,
    *,
    direction: Literal["down", "up"],
    baseline_sd: float | None,
    th: Mapping[str, float],
    chronic_path: bool,
) -> tuple[bool, float | None]:
    """Helper for compute_trend_diagnostics — returns (fired, sd_per_day)
    for one detector output. Module-level rather than nested so the
    loop-iteration values don't get captured by closure (ruff B023).
    """
    if sr is None:
        return False, None
    if direction == "down" and sr.slope_per_day >= 0:
        return False, None
    if direction == "up" and sr.slope_per_day <= 0:
        return False, None
    if chronic_path and sr.confidence_weight <= 0.0:
        return False, None
    if not baseline_sd:
        return False, None
    sd = abs(sr.slope_per_day) / baseline_sd
    grade = (
        _chronic_trend_severity(sd, th)
        if chronic_path
        else _trend_severity(sd, th)
    )
    return grade is not None, sd


def compute_trend_diagnostics(
    metrics: pd.DataFrame,
    today: date,
    thresholds: Mapping[str, float] | None = None,
) -> dict[str, TrendSignalDetail]:
    """Per-kind acute + chronic detector outputs for the three trend
    signals (HRV down, RHR up, sleep down). The frontend's
    recommendation card calls into this via the API to render the
    acute/chronic badge + the dual-window popover.

    Returns details for ALL three signal kinds — caller filters to
    "the ones that actually fired" by intersecting with rec.flags.
    Returning the unfired ones too keeps the door open for surfacing
    chronic-only "watch this" chips in a future iteration.

    The acute kind is picked the same way the engine does for HRV
    — RMSSD if present, else SDNN. The engine and the diagnostics
    must agree on which series they're reading, or the popover would
    show numbers that don't match the verdict.
    """
    th = _merge_thresholds(thresholds)
    out: dict[str, TrendSignalDetail] = {}

    for metric_kind, direction, signal_kind in _TREND_KIND_MAPPING:
        # HRV is the only one that has a fallback kind; the helper
        # picks the right one. RHR and sleep are single-kind, so the
        # tuple kind is what we use directly.
        kind = _hrv_kind(metrics) if signal_kind == "hrv_trend_down" else metric_kind
        _, baseline_sd, _ = _baseline(
            metrics, kind, today, int(th["baseline_window_days"])
        )

        acute = compute_trend_slope(
            metrics, kind, today, method="ols", window_days=HRV_ACUTE_DAYS,
        )
        chronic = compute_trend_slope(
            metrics, kind, today, method="ewma", window_days=HRV_CHRONIC_DAYS,
        )

        # "Fired" means severity-non-None on this window in the
        # direction-of-concern. Mirrors the gating in _dual_window_trend.
        # Loop-iteration values (direction, baseline_sd, th) are passed
        # explicitly rather than captured by closure so ruff's B023
        # late-binding lint stays quiet.
        acute_fired, acute_sd = _fired_in_direction(
            acute, direction=direction, baseline_sd=baseline_sd, th=th,
            chronic_path=False,
        )
        chronic_fired, chronic_sd = _fired_in_direction(
            chronic, direction=direction, baseline_sd=baseline_sd, th=th,
            chronic_path=True,
        )

        out[signal_kind] = TrendSignalDetail(
            kind=signal_kind,
            acute_window_days=HRV_ACUTE_DAYS,
            acute_slope_per_day=acute.slope_per_day if acute else None,
            acute_sd_per_day=acute_sd,
            acute_fired=acute_fired,
            chronic_window_days=HRV_CHRONIC_DAYS,
            chronic_slope_per_day=chronic.slope_per_day if chronic else None,
            chronic_sd_per_day=chronic_sd,
            chronic_fired=chronic_fired,
            chronic_confidence_weight=chronic.confidence_weight if chronic else 0.0,
        )

    return out


def detect_hrv_trend_signal(
    metrics: pd.DataFrame,
    today: date,
    thresholds: Mapping[str, float] | None = None,
) -> Signal | None:
    """Dual-window HRV trend detector (engine-v2 / E3).

    Computes both the acute (7-day OLS) and chronic (28-day EWMA)
    slopes and combines them per the ``combine_acute_chronic``
    decision table. The acute window catches recent changes; the
    chronic window confirms whether the change is a sustained pattern
    or short-window noise. A severe acute + flat chronic — the
    headline Holmes false-alarm case — downgrades to moderate; a
    chronic-confirmed acute trend stays at its full severity.

    Plews & Laursen 2013 recommend reacting to trajectory rather than
    instantaneous values; the dual-window combiner is what that
    recommendation looks like once you account for short-window noise
    sensitivity.
    """
    th = _merge_thresholds(thresholds)
    kind = _hrv_kind(metrics)
    severity, acute, chronic, acute_sd = _dual_window_trend(
        metrics, kind, today, th, direction="down",
    )
    if severity is None or acute is None or acute_sd is None:
        return None
    ids = list(acute.source_ids)
    if chronic is not None:
        ids.extend(chronic.source_ids)
    return Signal(
        kind="hrv_trend_down",
        severity=severity,
        summary=(
            f"HRV trending down: {acute.slope_per_day:+.1f} ms/day across the last "
            f"{HRV_ACUTE_DAYS} days ({acute_sd:.2f} SD/day)."
        ),
        source_metric_ids=ids,
    )


def detect_rhr_trend_signal(
    metrics: pd.DataFrame,
    today: date,
    thresholds: Mapping[str, float] | None = None,
) -> Signal | None:
    """Dual-window resting HR trend detector. Same combiner logic as
    HRV — rising RHR is the concerning direction; acute reads early
    warning, chronic confirms sustained drift."""
    th = _merge_thresholds(thresholds)
    kind = MetricKind.RESTING_HR.value
    severity, acute, chronic, acute_sd = _dual_window_trend(
        metrics, kind, today, th, direction="up",
    )
    if severity is None or acute is None or acute_sd is None:
        return None
    ids = list(acute.source_ids)
    if chronic is not None:
        ids.extend(chronic.source_ids)
    return Signal(
        kind="rhr_trend_up",
        severity=severity,
        summary=(
            f"Resting HR trending up: {acute.slope_per_day:+.1f} bpm/day across the last "
            f"{HRV_ACUTE_DAYS} days ({acute_sd:.2f} SD/day)."
        ),
        source_metric_ids=ids,
    )


def detect_sleep_trend_signal(
    metrics: pd.DataFrame,
    today: date,
    thresholds: Mapping[str, float] | None = None,
) -> Signal | None:
    """Dual-window sleep-hours trend detector. Falling sleep is the
    concerning direction; same combiner logic as HRV."""
    th = _merge_thresholds(thresholds)
    kind = MetricKind.SLEEP_HOURS.value
    severity, acute, chronic, acute_sd = _dual_window_trend(
        metrics, kind, today, th, direction="down",
    )
    if severity is None or acute is None or acute_sd is None:
        return None
    ids = list(acute.source_ids)
    if chronic is not None:
        ids.extend(chronic.source_ids)
    return Signal(
        kind="sleep_trend_down",
        severity=severity,
        summary=(
            f"Sleep trending down: {acute.slope_per_day:+.2f} h/day across the last "
            f"{HRV_ACUTE_DAYS} days ({acute_sd:.2f} SD/day)."
        ),
        source_metric_ids=ids,
    )


# --- Auto-fit baseline window -------------------------------------------
#
# Pick the per-client baseline window length from the data. The trick:
# split each candidate window into a newer half and older half, compute
# the mean of each, and ask "did the mean drift across this window?"
# Drift in baseline-SD units < 0.5 → the window is internally
# consistent. We pick the shortest stable window so the baseline is as
# responsive as possible without admitting noise.
#
# Falls back to the 28-day default if no window settles (insufficient
# data, or the athlete's signal is genuinely non-stationary across all
# candidates — which is itself a signal worth raising on the calibration
# page later).

@dataclass
class BaselineWindowSuggestion:
    """The auto-fit's pick + why. ``stable`` flags whether the chosen
    window actually meets the drift criterion — when False, the caller
    can mention that the recommendation is the literature default rather
    than a data-driven choice."""
    days: int
    stable: bool
    reason: str


def recommend_baseline_window(
    metrics: pd.DataFrame,
    today: date | None = None,
    *,
    candidates: tuple[int, ...] = BASELINE_WINDOW_CHOICES,
    drift_threshold_sd: float = 0.5,
) -> BaselineWindowSuggestion:
    """Pick the shortest baseline window whose mean is stable across its
    newer/older halves. Looks at HRV (preferring RMSSD over SDNN — same
    rule as _hrv_kind). Returns the 28-day default if no candidate
    settles."""
    today = today or date.today()
    kind = _hrv_kind(metrics)
    if metrics.empty:
        return BaselineWindowSuggestion(
            days=HRV_BASELINE_DAYS, stable=False,
            reason="no metrics yet — using literature default (28d)",
        )

    for days in sorted(candidates):
        window = _window(metrics, kind, today - timedelta(days=days), today)
        if len(window) < max(10, days // 2):
            # Not enough data inside this window to judge stability;
            # don't pick it, try the next.
            continue
        # Halve the window and check drift across the two halves.
        sorted_w = window.sort_values("date")
        mid = len(sorted_w) // 2
        older = sorted_w.iloc[:mid]
        newer = sorted_w.iloc[mid:]
        if older.empty or newer.empty:
            continue
        within_sd = float(sorted_w["value"].std(ddof=0))
        if within_sd == 0:
            # Pathologically flat — treat as stable (no drift to measure).
            return BaselineWindowSuggestion(
                days=days, stable=True,
                reason=f"signal flat across {days}d window — picking shortest stable window",
            )
        drift = abs(float(newer["value"].mean()) - float(older["value"].mean())) / within_sd
        if drift < drift_threshold_sd:
            return BaselineWindowSuggestion(
                days=days, stable=True,
                reason=(
                    f"{days}d window settled: drift between older and newer halves "
                    f"is {drift:.2f} SD (< {drift_threshold_sd:.1f})"
                ),
            )
    return BaselineWindowSuggestion(
        days=HRV_BASELINE_DAYS, stable=False,
        reason=(
            "No candidate window settled — signal is non-stationary across "
            "14, 28, and 56 days. Falling back to the literature default."
        ),
    )


# --- Composite recovery score ---------------------------------------------
#
# A single 0–100 number combining the four primary recovery markers, with
# every component (and the formula that produced the composite) visible
# alongside it so the trainer can audit how the gauge moved. Same rules
# the verdict engine uses — anchored at the severity bands — so the
# gauge and the verdict can never disagree about what's driving the call.

# Component weights. HRV and sleep are the two most-cited recovery
# markers in the literature (Plews & Laursen, ACSM 11e), so they carry
# more weight than the corroborators.
RECOVERY_WEIGHTS = {"hrv": 0.30, "sleep": 0.30, "rhr": 0.20, "acwr": 0.20}


@dataclass
class RecoveryScore:
    """Snapshot of current recovery state. The composite is a weighted
    mean of whichever components are measurable — if a client has no
    sleep data, the remaining components' weights re-normalize to 1.

    None values mean "no data" — display as a dash, not as zero. A zero
    component score is real ("at or past the severe threshold"); ``None``
    means we couldn't compute it.
    """
    composite: int | None
    hrv: int | None
    sleep: int | None
    rhr: int | None
    acwr: int | None


def _band_score(value: float, mild: float, moderate: float, severe: float) -> float:
    """Map an absolute deviation value to a 0–100 score, with anchored
    stops at the severity boundaries: clean (0 deviation) = 100, mild
    boundary = 75, moderate boundary = 50, severe boundary = 25, and
    1.5x severe or worse = 0. Piecewise linear in between."""
    if value <= 0:
        return 100.0
    if value < mild:
        return 100 - 25 * (value / mild)
    if value < moderate:
        return 75 - 25 * ((value - mild) / (moderate - mild))
    if value < severe:
        return 50 - 25 * ((value - moderate) / (severe - moderate))
    if value < severe * 1.5:
        return 25 - 25 * ((value - severe) / (severe * 0.5))
    return 0.0


def _sleep_component_score(mean_hours: float, floor: float, deficit: float) -> float:
    """Sleep score anchored at the ACSM floor (= 75) and deficit threshold
    (= 25). 8 h+ caps the score at 100; well-below-deficit clamps to 0."""
    upper = 8.0  # ACSM general adult target ceiling
    if mean_hours >= upper:
        return 100.0
    if mean_hours >= floor:
        return 75 + 25 * (mean_hours - floor) / max(1e-9, upper - floor)
    if mean_hours >= deficit:
        return 25 + 50 * (mean_hours - deficit) / max(1e-9, floor - deficit)
    # Below deficit — linear ramp from 25 down to 0 across the next 2 h.
    if mean_hours >= deficit - 2:
        return 25 * (mean_hours - (deficit - 2)) / 2
    return 0.0


def _acwr_component_score(ratio: float, safe_low: float, safe_high: float,
                          moderate_high: float, severe_high: float) -> float:
    """ACWR score: 100 across the Gabbett sweet spot, decaying to 50 at
    the moderate boundary, 25 at the severe boundary, 0 well past that.
    Under-load (ACWR below safe_low) returns 75 — detraining is a soft
    flag, not a recovery problem worth tanking the composite for."""
    if safe_low <= ratio <= safe_high:
        return 100.0
    if ratio < safe_low:
        return 75.0  # under-load — not a recovery deficit
    # ratio > safe_high
    if ratio < moderate_high:
        return 100 - 50 * (ratio - safe_high) / max(1e-9, moderate_high - safe_high)
    if ratio < severe_high:
        return 50 - 25 * (ratio - moderate_high) / max(1e-9, severe_high - moderate_high)
    upper_zero = severe_high + 0.4  # ratio 2.2 → 0 with default thresholds
    if ratio < upper_zero:
        return 25 - 25 * (ratio - severe_high) / max(1e-9, upper_zero - severe_high)
    return 0.0


def compute_recovery_score(
    metrics: pd.DataFrame,
    sessions: pd.DataFrame,
    today: date | None = None,
    thresholds: Mapping[str, float] | None = None,
) -> RecoveryScore:
    """Build the 0–100 composite recovery score plus its four
    sub-components. Same windows, same baselines, same thresholds as
    the verdict engine — so the gauge can never contradict the verdict."""
    today = today or date.today()
    th = _merge_thresholds(thresholds)

    # HRV component — drop_sd in baseline-SD units below baseline.
    baseline_days = int(th["baseline_window_days"])
    hrv_kind = _hrv_kind(metrics)
    hrv_acute, _ = _recent_mean(metrics, hrv_kind, today, HRV_ACUTE_DAYS)
    hrv_base, hrv_sd, _ = _baseline(metrics, hrv_kind, today, baseline_days)
    hrv_score: float | None = None
    if hrv_acute is not None and hrv_base is not None and hrv_sd:
        drop_sd = max(0.0, (hrv_base - hrv_acute) / hrv_sd)
        hrv_score = _band_score(drop_sd, th["hrv_mild_sd"], th["hrv_moderate_sd"], th["hrv_severe_sd"])

    # Sleep component — mean hours over the last 7 days.
    sleep_acute, _ = _recent_mean(metrics, MetricKind.SLEEP_HOURS.value, today, HRV_ACUTE_DAYS)
    sleep_score: float | None = None
    if sleep_acute is not None:
        sleep_score = _sleep_component_score(sleep_acute, th["sleep_floor_hours"], th["sleep_deficit_hours"])

    # RHR component — bpm rise above baseline.
    rhr_acute, _ = _recent_mean(metrics, MetricKind.RESTING_HR.value, today, HRV_ACUTE_DAYS)
    rhr_base, _, _ = _baseline(metrics, MetricKind.RESTING_HR.value, today, baseline_days)
    rhr_score: float | None = None
    if rhr_acute is not None and rhr_base is not None:
        rise = max(0.0, rhr_acute - rhr_base)
        rhr_score = _band_score(rise, th["rhr_mild_bpm"], th["rhr_moderate_bpm"], th["rhr_severe_bpm"])

    # ACWR component — acute/chronic load ratio.
    acwr_score: float | None = None
    loads, _ = _session_load(sessions)
    if not loads.empty:
        acute_window = [d for d in loads.index if 0 <= (today - d).days <= HRV_ACUTE_DAYS]
        chronic_window = [d for d in loads.index if 0 <= (today - d).days <= ACWR_CHRONIC_WEEKS * 7]
        if acute_window and chronic_window:
            acute_total = float(loads.loc[acute_window].sum())
            weekly_chronic = float(loads.loc[chronic_window].sum()) / ACWR_CHRONIC_WEEKS
            if weekly_chronic > 0:
                ratio = acute_total / weekly_chronic
                acwr_score = _acwr_component_score(
                    ratio, th["acwr_safe_low"], th["acwr_safe_high"],
                    th["acwr_moderate_high"], th["acwr_severe_high"],
                )

    # Composite — weights re-normalize over whichever components are
    # measurable. Missing components don't drag the score down to zero;
    # they just don't contribute.
    components = {"hrv": hrv_score, "sleep": sleep_score, "rhr": rhr_score, "acwr": acwr_score}
    total_weight = sum(RECOVERY_WEIGHTS[k] for k, v in components.items() if v is not None)
    composite: int | None
    if total_weight == 0:
        composite = None
    else:
        composite = round(
            sum(RECOVERY_WEIGHTS[k] * v for k, v in components.items() if v is not None) / total_weight
        )

    return RecoveryScore(
        composite=composite,
        hrv=round(hrv_score) if hrv_score is not None else None,
        sleep=round(sleep_score) if sleep_score is not None else None,
        rhr=round(rhr_score) if rhr_score is not None else None,
        acwr=round(acwr_score) if acwr_score is not None else None,
    )


def detect_training_readiness_signal(
    metrics: pd.DataFrame,
    today: date,
    thresholds: Mapping[str, float] | None = None,
) -> Signal | None:
    """Garmin Training Readiness (0–100) — Garmin's composite of recent
    HRV, stress, sleep, recovery time, and acute load.

    Used as a corroborator: it can escalate a borderline call but
    doesn't trigger a deload solo (we already have HRV / sleep / RHR
    looking at the same underlying signals). When Garmin's own
    composite says "Low" for a sustained period, that's worth surfacing
    even if the individual signals each fell just short of mild.

    Bands: Excellent ≥75, High 50–74, Moderate 25–49, Low <25 per
    Garmin's published documentation; we collapse to mild / moderate /
    severe over a 7-day mean to smooth daily noise.
    """
    th = _merge_thresholds(thresholds)
    acute, acute_ids = _recent_mean(metrics, MetricKind.TRAINING_READINESS.value, today, HRV_ACUTE_DAYS)
    if acute is None or acute >= th["tr_mild"]:
        return None

    severity: Severity = (
        "severe" if acute < th["tr_severe"]
        else "moderate" if acute < th["tr_moderate"]
        else "mild"
    )
    return Signal(
        kind="training_readiness_low",
        severity=severity,
        summary=f"Garmin Training Readiness 7d mean is {acute:.0f}/100 (Garmin's composite of HRV, sleep, stress, and acute load).",
        source_metric_ids=acute_ids,
    )


# --- Aggregator ----------------------------------------------------------

def generate_recommendation(
    client_id: str,
    metrics: pd.DataFrame,
    sessions: pd.DataFrame,
    today: date | None = None,
    thresholds: Mapping[str, float] | None = None,
) -> Recommendation:
    """Decide a recommendation for the upcoming training week.

    Severity weighting:
      - 1 severe OR 2+ moderate (excluding mild-only ACWR-low) → deload
      - 1 moderate OR 2+ mild → conservative progression
      - 0 signals (or only ACWR-low) → standard ACSM progression

    ``thresholds`` is a sparse per-client override dict — only the
    severity boundaries the trainer customized appear here; everything
    else falls back to DEFAULT_THRESHOLDS. None / empty means use the
    population defaults across the board.
    """
    today = today or date.today()
    week_of = today - timedelta(days=today.weekday())  # Monday

    # Both detector lists have the same call shape:
    # ``(data, today, thresholds) -> Signal | None``. mypy infers the
    # narrowest function type from the first list entry, so without an
    # explicit Callable annotation the second detector list (with a
    # different concrete function type) trips an assignment error.
    from collections.abc import Callable
    from typing import Any
    _Detector = Callable[[Any, date, Mapping[str, float] | None], "Signal | None"]
    detectors_metric: list[_Detector] = [
        detect_hrv_signal,
        detect_hrv_trend_signal,
        detect_rhr_signal,
        detect_rhr_trend_signal,
        detect_sleep_signal,
        detect_sleep_trend_signal,
        detect_training_readiness_signal,
    ]
    detectors_session: list[_Detector] = [detect_acwr_signal, detect_rpe_signal]

    signals: list[Signal] = []
    for fn in detectors_metric:
        sig = fn(metrics, today, thresholds)
        if sig:
            signals.append(sig)
    for fn in detectors_session:
        sig = fn(sessions, today, thresholds)
        if sig:
            signals.append(sig)

    # E4: level-dominates-trend safety rule. Compute the recovery
    # composite first; if it's at or above the floor (default 90), demote
    # every trend signal by one band before the verdict combiner reads
    # severity counts. Levels-based signals stay as-is — the rule is
    # specifically about trend noise on a clean recovery picture, not a
    # blanket "ignore everything when recovery is high."
    th = _merge_thresholds(thresholds)
    level_floor = int(th["level_dominates_recovery_floor"])
    recovery = compute_recovery_score(metrics, sessions, today=today, thresholds=thresholds)
    level_dominates_fired = False
    n_demoted = 0
    if recovery.composite is not None and recovery.composite >= level_floor:
        signals, n_demoted = _apply_level_dominates(signals)
        level_dominates_fired = n_demoted > 0

    # Severity counts — ACWR-low is informational, not a recovery flag.
    weighting_signals = [s for s in signals if s.kind != "acwr_low"]
    severe = sum(1 for s in weighting_signals if s.severity == "severe")
    moderate = sum(1 for s in weighting_signals if s.severity == "moderate")
    mild = sum(1 for s in weighting_signals if s.severity == "mild")

    if severe >= 1 or moderate >= 2:
        rec_text = f"Deload week: reduce training load by {int(DELOAD_LOAD_CUT * 100)}%."
        confidence = 0.9 if severe >= 1 else 0.82
    elif moderate >= 1 or mild >= 2:
        rec_text = f"Conservative progression: hold volume, increase load ~{int(ACSM_CONSERVATIVE * 100)}%."
        confidence = 0.72
    else:
        lo, hi = ACSM_STANDARD_RANGE
        rec_text = f"Standard progression per ACSM 11e: increase load {int(lo * 100)}–{int(hi * 100)}%."
        confidence = 0.78

    if signals:
        rationale = " ".join(s.summary for s in signals)
        flags = [s.kind for s in signals]
        rationale += f" Flags: {', '.join(flags)}."
    else:
        rationale = "Recovery markers within baseline range; no flags. Proceed with planned progression."

    if level_dominates_fired and recovery.composite is not None:
        plural = "signal" if n_demoted == 1 else "signals"
        rationale += (
            f" Recovery composite {recovery.composite}/100 — {n_demoted} trend "
            f"{plural} downweighted (early-warning only; levels still strong)."
        )

    source_ids: list[str] = []
    for s in signals:
        source_ids.extend(s.source_metric_ids)

    return Recommendation(
        id=_rid(),
        client_id=client_id,
        generated_at=datetime.now(),
        week_of=week_of,
        recommendation=rec_text,
        rationale=rationale,
        source_metric_ids=list(dict.fromkeys(source_ids)),  # dedupe, preserve order
        confidence=confidence,
    )
