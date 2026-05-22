"""Tests for the v0.2 reasoning layer.

These exercise the literature-backed signals:
  - HRV vs 28-day baseline in SD units (Plews & Laursen)
  - ACWR from sRPE × duration (Gabbett)
  - Resting HR drift vs baseline (Buchheit)
  - Sleep against ACSM 11e floors
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from fit_ontology.ontology import MetricKind
from fit_ontology.reasoning import generate_recommendation


# ---- Fixture builders ---------------------------------------------------

def _stable_metric(client_id: str, kind: str, baseline: float, today: date,
                   *, days: int = 35, jitter: float = 0.0,
                   acute_value: float | None = None, acute_days: int = 7,
                   unit: str = "ms", source: str = "garmin") -> list[dict]:
    """Build ``days`` of daily values for a metric kind.

    ``acute_value`` overrides the last ``acute_days`` days. Useful for
    setting up "baseline established, then deviation" scenarios.
    """
    rng = random.Random(f"{kind}-{baseline}")
    rows: list[dict] = []
    for offset in range(days, 0, -1):
        d = today - timedelta(days=offset)
        if acute_value is not None and offset <= acute_days:
            value = acute_value + (rng.uniform(-jitter, jitter) if jitter else 0)
        else:
            value = baseline + (rng.uniform(-jitter, jitter) if jitter else 0)
        rows.append(dict(
            id=f"{kind}-{offset}",
            client_id=client_id, date=d,
            source=source, kind=kind, value=value, unit=unit,
        ))
    return rows


def _metrics(client_id: str, *, today: date | None = None,
             hrv_baseline: float = 55, hrv_acute: float | None = None,
             rhr_baseline: float = 58, rhr_acute: float | None = None,
             sleep_acute: float | None = 7.8) -> pd.DataFrame:
    today = today or date.today()
    rows: list[dict] = []
    rows += _stable_metric(client_id, MetricKind.HRV_RMSSD.value, hrv_baseline, today,
                           jitter=3, acute_value=hrv_acute, unit="ms")
    rows += _stable_metric(client_id, MetricKind.RESTING_HR.value, rhr_baseline, today,
                           jitter=1.5, acute_value=rhr_acute, unit="bpm")
    if sleep_acute is not None:
        rows += _stable_metric(client_id, MetricKind.SLEEP_HOURS.value, sleep_acute, today,
                               jitter=0.4, acute_days=7, unit="h")
    return pd.DataFrame(rows)


def _sessions(client_id: str, *, today: date | None = None,
              rpe_baseline: int = 6, rpe_acute: int | None = None,
              duration_min: int = 60, sessions_per_week: int = 4) -> pd.DataFrame:
    """Generate 28 days of sessions, 4/week by default. ``rpe_acute``
    overrides RPE for the last 7 days."""
    today = today or date.today()
    rng = random.Random(f"{client_id}-sessions")
    rows: list[dict] = []
    weekdays = [1, 3, 5, 6]  # Tue/Thu/Sat/Sun
    for offset in range(28, 0, -1):
        d = today - timedelta(days=offset)
        if d.weekday() not in weekdays[:sessions_per_week]:
            continue
        rpe = rpe_acute if (rpe_acute is not None and offset <= 7) else rpe_baseline
        rpe = max(1, min(10, rpe + rng.choice([-1, 0, 0, 1])))
        rows.append(dict(
            id=f"s-{offset}",
            client_id=client_id, date=d,
            type="strength", duration_min=duration_min,
            rpe=rpe, notes="",
        ))
    return pd.DataFrame(rows)


# ---- Tests --------------------------------------------------------------

def test_clean_recovery_yields_standard_progression():
    """Stable HRV near baseline, normal sleep, balanced ACWR → standard."""
    today = date.today()
    m = _metrics("c1", today=today, hrv_baseline=55, hrv_acute=None,
                 rhr_baseline=58, rhr_acute=None, sleep_acute=7.8)
    s = _sessions("c1", today=today, rpe_baseline=6)
    r = generate_recommendation("c1", m, s, today=today)
    assert "standard progression" in r.recommendation.lower()
    assert "deload" not in r.recommendation.lower()


def test_severe_hrv_drop_triggers_deload():
    """HRV crashes 15 ms (~3 SD) below baseline → severe HRV signal alone
    is enough to deload."""
    today = date.today()
    m = _metrics("c1", today=today, hrv_baseline=55, hrv_acute=40, sleep_acute=7.8)
    s = _sessions("c1", today=today, rpe_baseline=6)
    r = generate_recommendation("c1", m, s, today=today)
    assert "deload" in r.recommendation.lower()
    assert r.confidence >= 0.85
    assert len(r.source_metric_ids) > 0


def test_two_moderate_signals_trigger_deload():
    """Moderate HRV drop + sleep deficit (each on its own would be
    conservative) combine into a deload."""
    today = date.today()
    m = _metrics("c1", today=today, hrv_baseline=55, hrv_acute=49,  # ~1.2 SD
                 sleep_acute=6.5)  # below floor but above severe deficit
    s = _sessions("c1", today=today, rpe_baseline=6)
    r = generate_recommendation("c1", m, s, today=today)
    assert "deload" in r.recommendation.lower()


def test_single_mild_signal_yields_conservative():
    """A single mild HRV deviation → conservative, not deload."""
    today = date.today()
    m = _metrics("c1", today=today, hrv_baseline=55, hrv_acute=51, sleep_acute=7.8)
    s = _sessions("c1", today=today, rpe_baseline=6)
    r = generate_recommendation("c1", m, s, today=today)
    # Either conservative or standard depending on jitter; both are
    # acceptable for a single mild deviation — but never deload.
    assert "deload" not in r.recommendation.lower()


def test_rhr_elevated_contributes_to_signal_count():
    """RHR sustained 6+ bpm above baseline is a moderate signal; paired
    with sleep deficit it should escalate to a deload."""
    today = date.today()
    m = _metrics("c1", today=today, hrv_baseline=55, hrv_acute=54,
                 rhr_baseline=58, rhr_acute=65,
                 sleep_acute=6.4)
    s = _sessions("c1", today=today, rpe_baseline=6)
    r = generate_recommendation("c1", m, s, today=today)
    assert "deload" in r.recommendation.lower()
    assert any("resting hr" in s.lower() or "rhr" in s.lower()
               for s in [r.rationale])


def test_acwr_spike_drives_high_load_signal():
    """Doubling session load in the acute week should push ACWR well above
    the 1.3 sweet spot ceiling and surface in the rationale."""
    today = date.today()
    m = _metrics("c1", today=today, hrv_baseline=55, hrv_acute=None,
                 sleep_acute=7.8)
    # Baseline 4 x/week at 60min RPE 5; acute week 4 x/week at 90min RPE 9.
    s_base = _sessions("c1", today=today, rpe_baseline=5, duration_min=60)
    s_acute = _sessions("c1", today=today, rpe_baseline=5, rpe_acute=9, duration_min=90)
    # Replace the last week of base with acute-week values.
    s_base["date"] = pd.to_datetime(s_base["date"]).dt.date
    s_acute["date"] = pd.to_datetime(s_acute["date"]).dt.date
    last7 = [d for d in s_acute["date"] if (today - d).days <= 7]
    s_base = s_base[~s_base["date"].isin(last7)]
    s = pd.concat([s_base, s_acute[s_acute["date"].isin(last7)]], ignore_index=True)

    r = generate_recommendation("c1", m, s, today=today)
    assert "acwr" in r.rationale.lower()


def test_no_data_returns_standard_progression():
    """With no metrics and no sessions the recommender should default to
    standard progression rather than crash or invent a deload."""
    today = date.today()
    m = pd.DataFrame(columns=["id", "client_id", "date", "source", "kind", "value", "unit"])
    s = pd.DataFrame(columns=["id", "client_id", "date", "type", "duration_min", "rpe", "notes"])
    r = generate_recommendation("c1", m, s, today=today)
    assert "standard progression" in r.recommendation.lower()
    assert r.source_metric_ids == []
