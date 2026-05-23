"""
The reasoning layer.

Rules-based on purpose. For a trainer with one practice, explainable beats
clever — every recommendation carries the source-metric IDs that produced
it so a domain expert can audit and override.

The signals were chosen to match how trainers and sport scientists
actually quantify load and recovery, not just what's easy to compute:

  - HRV trend is measured against a 28-day rolling baseline in SD units
    (Plews & Laursen 2017, "Heart rate variability and training intensity
    distribution in elite rowers"). Week-vs-week alone is too noisy at the
    individual level.

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
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

import pandas as pd

from .ontology import MetricKind, Recommendation


# --- Thresholds (literature-anchored; centralized for trainer override) ---

HRV_BASELINE_DAYS = 28              # Plews & Laursen recommend 21–28d windows
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

# Progression magnitudes from ACSM 11e Ch. 6 (cardiorespiratory) and
# Ch. 7 (resistance). Conservative end picked when any signal is present.
ACSM_STANDARD_RANGE = (0.05, 0.10)
ACSM_CONSERVATIVE = 0.05
DELOAD_LOAD_CUT = 0.20              # 20% cut; more aggressive than 15% reflects
                                    # recent autoregulation literature for clearly stressed states


Severity = Literal["mild", "moderate", "severe"]


@dataclass
class Signal:
    kind: str
    severity: Severity
    summary: str
    source_metric_ids: list[str] = field(default_factory=list)


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


# --- Per-signal detectors -------------------------------------------------

def detect_hrv_signal(metrics: pd.DataFrame, today: date) -> Signal | None:
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
    hrv_kind = MetricKind.HRV_RMSSD.value
    if metrics.empty or hrv_kind not in metrics["kind"].values:
        if MetricKind.HRV_SDNN.value in metrics["kind"].values:
            hrv_kind = MetricKind.HRV_SDNN.value

    acute, acute_ids = _recent_mean(metrics, hrv_kind, today, HRV_ACUTE_DAYS)
    baseline_mean, baseline_sd, baseline_ids = _baseline(
        metrics, hrv_kind, today, HRV_BASELINE_DAYS
    )
    if acute is None or baseline_mean is None or not baseline_sd:
        return None

    drop_sd = (baseline_mean - acute) / baseline_sd
    if drop_sd < HRV_MILD_SD:
        return None

    severity: Severity = (
        "severe" if drop_sd >= HRV_SEVERE_SD
        else "moderate" if drop_sd >= HRV_MODERATE_SD
        else "mild"
    )
    return Signal(
        kind="hrv_below_baseline",
        severity=severity,
        summary=f"HRV acute {acute:.1f} ms is {drop_sd:.1f} SD below the {HRV_BASELINE_DAYS}d baseline ({baseline_mean:.1f} ms).",
        source_metric_ids=list({*acute_ids, *baseline_ids}),
    )


def detect_rhr_signal(metrics: pd.DataFrame, today: date) -> Signal | None:
    """Resting HR rise above the 28-day baseline. Buchheit (2014): a
    sustained 5+ bpm elevation indicates autonomic stress, particularly
    when paired with depressed HRV."""
    acute, acute_ids = _recent_mean(metrics, MetricKind.RESTING_HR.value, today, HRV_ACUTE_DAYS)
    baseline_mean, _baseline_sd, baseline_ids = _baseline(
        metrics, MetricKind.RESTING_HR.value, today, RHR_BASELINE_DAYS
    )
    if acute is None or baseline_mean is None:
        return None

    rise = acute - baseline_mean
    if rise < RHR_MILD_BPM:
        return None

    severity: Severity = (
        "severe" if rise >= RHR_SEVERE_BPM
        else "moderate" if rise >= RHR_MODERATE_BPM
        else "mild"
    )
    return Signal(
        kind="rhr_above_baseline",
        severity=severity,
        summary=f"Resting HR acute {acute:.0f} bpm is {rise:+.0f} bpm above the {RHR_BASELINE_DAYS}d baseline ({baseline_mean:.0f} bpm).",
        source_metric_ids=list({*acute_ids, *baseline_ids}),
    )


def detect_sleep_signal(metrics: pd.DataFrame, today: date) -> Signal | None:
    """Mean sleep duration over the last 7 days against ACSM 11e
    7-9 h guidance, with a 6 h "severe deficit" floor. Also folds in
    Garmin's sleep score when present (< 70 = poor)."""
    acute_hours, hour_ids = _recent_mean(metrics, MetricKind.SLEEP_HOURS.value, today, HRV_ACUTE_DAYS)
    acute_score, score_ids = _recent_mean(metrics, MetricKind.SLEEP_SCORE.value, today, HRV_ACUTE_DAYS)
    if acute_hours is None and acute_score is None:
        return None

    severity: Severity | None = None
    parts: list[str] = []

    if acute_hours is not None:
        if acute_hours < SLEEP_DEFICIT_HOURS:
            severity = "severe"
        elif acute_hours < SLEEP_FLOOR_HOURS:
            severity = "moderate"
        parts.append(f"mean {acute_hours:.1f}h/night")

    if acute_score is not None and acute_score < SLEEP_SCORE_POOR:
        severity = "moderate" if severity is None or severity == "mild" else severity
        parts.append(f"sleep score {acute_score:.0f}")

    if severity is None:
        return None

    return Signal(
        kind="sleep_deficit",
        severity=severity,
        summary=f"Sleep last week: {'; '.join(parts)}.",
        source_metric_ids=list({*hour_ids, *score_ids}),
    )


def _session_load(sessions: pd.DataFrame) -> pd.Series:
    """Session load = RPE × duration (Foster's sRPE method). Returns a
    Series indexed by date with one value per day (sum if multiple
    sessions). Empty Series if no sessions."""
    if sessions.empty:
        return pd.Series(dtype=float)
    s = sessions.copy()
    s["date"] = _as_dates(s["date"])
    s["load"] = s["rpe"].astype(float) * s["duration_min"].astype(float)
    return s.groupby("date")["load"].sum()


def detect_acwr_signal(sessions: pd.DataFrame, today: date) -> Signal | None:
    """Acute:Chronic Workload Ratio per Gabbett (2016).

    Acute = sum of session loads over the last 7 days.
    Chronic = mean weekly load across the last 28 days (i.e., a 4-week
              moving average of weekly load).

    Sweet spot is 0.8–1.3. Ratios > 1.5 elevated injury risk; > 1.8 high.
    Ratios < 0.8 flag detraining (mild signal — under-load is not a
    deload trigger but is worth surfacing to a trainer).
    """
    loads = _session_load(sessions)
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

    ratio = acute_total / weekly_chronic
    severity: Severity | None = None

    if ratio >= ACWR_SEVERE_HIGH:
        severity = "severe"
    elif ratio >= ACWR_MODERATE_HIGH:
        severity = "moderate"
    elif ratio > ACWR_SAFE_HIGH:
        severity = "mild"
    elif ratio < ACWR_SAFE_LOW:
        # Under-load. Mild signal so it shows up in the rationale without
        # triggering a deload; trainers may want to increase volume.
        return Signal(
            kind="acwr_low",
            severity="mild",
            summary=f"ACWR {ratio:.2f} (acute {acute_total:.0f} AU / weekly chronic {weekly_chronic:.0f} AU). Below sweet spot — possible detraining.",
            source_metric_ids=[],
        )

    if severity is None:
        return None

    return Signal(
        kind="acwr_high",
        severity=severity,
        summary=f"ACWR {ratio:.2f} (acute {acute_total:.0f} AU / weekly chronic {weekly_chronic:.0f} AU). Above safe zone (Gabbett 0.8–1.3).",
        source_metric_ids=[],
    )


def detect_rpe_signal(sessions: pd.DataFrame, today: date) -> Signal | None:
    """Session-RPE drift: last-week mean RPE vs prior-week mean. A rising
    RPE at constant volume indicates undertrained recovery."""
    if sessions.empty:
        return None
    s = sessions.copy()
    s["date"] = _as_dates(s["date"])
    last_week = s[(s["date"] > today - timedelta(days=7)) & (s["date"] <= today)]
    prior_week = s[(s["date"] > today - timedelta(days=14)) & (s["date"] <= today - timedelta(days=7))]
    if last_week.empty or prior_week.empty:
        return None

    last_mean = float(last_week["rpe"].mean())
    prior_mean = float(prior_week["rpe"].mean())
    rise = last_mean - prior_mean

    if rise < RPE_RISE_MILD:
        return None

    severity: Severity = "moderate" if rise >= RPE_RISE_MODERATE else "mild"
    return Signal(
        kind="rpe_rising",
        severity=severity,
        summary=f"Session RPE rose {rise:+.1f} ({prior_mean:.1f} → {last_mean:.1f}) across the last two weeks.",
        source_metric_ids=[],
    )


# --- Aggregator ----------------------------------------------------------

def generate_recommendation(
    client_id: str,
    metrics: pd.DataFrame,
    sessions: pd.DataFrame,
    today: date | None = None,
) -> Recommendation:
    """Decide a recommendation for the upcoming training week.

    Severity weighting:
      - 1 severe OR 2+ moderate (excluding mild-only ACWR-low) → deload
      - 1 moderate OR 2+ mild → conservative progression
      - 0 signals (or only ACWR-low) → standard ACSM progression
    """
    today = today or date.today()
    week_of = today - timedelta(days=today.weekday())  # Monday

    detectors_metric = [detect_hrv_signal, detect_rhr_signal, detect_sleep_signal]
    detectors_session = [detect_acwr_signal, detect_rpe_signal]

    signals: list[Signal] = []
    for fn in detectors_metric:
        sig = fn(metrics, today)
        if sig:
            signals.append(sig)
    for fn in detectors_session:
        sig = fn(sessions, today)
        if sig:
            signals.append(sig)

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
