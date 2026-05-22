"""
The reasoning layer.

This is deliberately rules-based, not ML. For a trainer with one practice,
explainable beats clever — every recommendation must carry its source-data
trail so the trainer can audit it and override it.

References:
  - ACSM (American College of Sports Medicine) Guidelines for Exercise
    Testing and Prescription, 11th ed. Progressive overload: 2-10% weekly
    load increase, conditional on recovery markers.
  - Buchheit M. (2014), "Monitoring training status with HR measures."
    HRV decreases of >10% week-over-week signal autonomic stress.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pandas as pd

from .ontology import MetricKind, Recommendation


HRV_DROP_THRESHOLD = 0.10            # 10% week-over-week
SLEEP_FLOOR_HOURS = 7.0              # ACSM general adult guideline
DELOAD_INTENSITY_CUT = 0.15          # reduce load 15% on deload weeks
ACSM_WEEKLY_PROGRESSION = (0.05, 0.10)  # 5-10% weekly load increase


def _rid() -> str:
    return f"r_{uuid.uuid4().hex[:12]}"


def _as_dates(series: pd.Series) -> pd.Series:
    """Coerce a date-shaped column to a Series of Python ``date`` objects.
    DuckDB returns DATE columns as ``datetime64[ns]`` Timestamps; pandas 2.x
    refuses to compare those directly to Python ``date`` literals. This
    normalizes both code paths (synthetic CSV, real Garmin sync) to the
    same dtype before any window comparisons run."""
    if series.empty:
        return series
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dt.date
    return series


def _weekly_mean(metrics: pd.DataFrame, kind: str, week_start: date) -> tuple[float | None, list[str]]:
    """Return (mean value, list of metric ids) for the 7-day window starting `week_start`."""
    week_end = week_start + timedelta(days=7)
    dates = _as_dates(metrics["date"])
    sub = metrics[(metrics["kind"] == kind) & (dates >= week_start) & (dates < week_end)]
    if sub.empty:
        return None, []
    return float(sub["value"].mean()), sub["id"].tolist()


def _rpe_trend(sessions: pd.DataFrame, week_start: date) -> float | None:
    """Mean RPE for the 7-day window starting `week_start`."""
    week_end = week_start + timedelta(days=7)
    dates = _as_dates(sessions["date"])
    sub = sessions[(dates >= week_start) & (dates < week_end)]
    if sub.empty:
        return None
    return float(sub["rpe"].mean())


def generate_recommendation(
    client_id: str,
    metrics: pd.DataFrame,
    sessions: pd.DataFrame,
    today: date | None = None,
) -> Recommendation:
    """
    Decide a recommendation for the upcoming training week.

    Algorithm:
      1. Compare last week's HRV mean to the prior week. Drop >10% → autonomic stress.
      2. Check last week's mean sleep. Below 7h floor → recovery deficit.
      3. Check RPE trend. Rising RPE with steady load → undertraining the recovery.
      4. If any two of (HRV drop, low sleep, rising RPE) → recommend deload (-15%).
         If one → recommend conservative progression (5%).
         If none → recommend standard progression (5-10%).
    """
    today = today or date.today()
    this_week = today - timedelta(days=today.weekday())  # Monday
    last_week = this_week - timedelta(days=7)
    prior_week = last_week - timedelta(days=7)

    source_ids: list[str] = []
    flags: list[str] = []
    notes: list[str] = []

    # HRV signal
    hrv_last, ids = _weekly_mean(metrics, MetricKind.HRV_RMSSD.value, last_week)
    source_ids += ids
    hrv_prior, ids = _weekly_mean(metrics, MetricKind.HRV_RMSSD.value, prior_week)
    source_ids += ids
    if hrv_last is not None and hrv_prior is not None:
        delta = (hrv_last - hrv_prior) / hrv_prior
        notes.append(f"HRV last week {hrv_last:.1f} ms vs prior {hrv_prior:.1f} ms ({delta:+.0%}).")
        if delta < -HRV_DROP_THRESHOLD:
            flags.append("hrv_drop")
    else:
        notes.append("HRV data insufficient for week-over-week comparison.")

    # Sleep signal
    sleep_last, ids = _weekly_mean(metrics, MetricKind.SLEEP_HOURS.value, last_week)
    source_ids += ids
    if sleep_last is not None:
        notes.append(f"Mean sleep last week: {sleep_last:.1f} h.")
        if sleep_last < SLEEP_FLOOR_HOURS:
            flags.append("low_sleep")
    else:
        notes.append("No sleep data for last week.")

    # RPE signal
    rpe_last = _rpe_trend(sessions, last_week)
    rpe_prior = _rpe_trend(sessions, prior_week)
    if rpe_last is not None and rpe_prior is not None:
        notes.append(f"Mean RPE last week {rpe_last:.1f} vs prior {rpe_prior:.1f}.")
        if rpe_last > rpe_prior + 1.0:
            flags.append("rising_rpe")

    # Decide
    if len(flags) >= 2:
        rec_text = f"Deload week: reduce training load by {int(DELOAD_INTENSITY_CUT * 100)}%."
        confidence = 0.85
    elif len(flags) == 1:
        rec_text = "Conservative progression: hold volume, increase load ~5%."
        confidence = 0.7
    else:
        lo, hi = ACSM_WEEKLY_PROGRESSION
        rec_text = f"Standard progression per ACSM: increase load {int(lo * 100)}–{int(hi * 100)}%."
        confidence = 0.75

    rationale = " ".join(notes)
    if flags:
        rationale += f" Flags: {', '.join(flags)}."

    return Recommendation(
        id=_rid(),
        client_id=client_id,
        generated_at=datetime.now(),
        week_of=this_week,
        recommendation=rec_text,
        rationale=rationale,
        source_metric_ids=source_ids,
        confidence=confidence,
    )
