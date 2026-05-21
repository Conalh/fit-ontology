"""Smoke tests for the reasoning layer."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from fit_ontology.ontology import MetricKind
from fit_ontology.reasoning import generate_recommendation


def _metrics(client_id, hrv_last, hrv_prior, sleep_last):
    today = date.today()
    last_monday = today - timedelta(days=today.weekday())
    last_week_start = last_monday - timedelta(days=7)
    prior_week_start = last_monday - timedelta(days=14)
    rows = []
    for i in range(7):
        rows.append(dict(id=f"hl{i}", client_id=client_id,
                         date=last_week_start + timedelta(days=i),
                         source="whoop", kind=MetricKind.HRV_RMSSD.value,
                         value=hrv_last, unit="ms"))
        rows.append(dict(id=f"sl{i}", client_id=client_id,
                         date=last_week_start + timedelta(days=i),
                         source="whoop", kind=MetricKind.SLEEP_HOURS.value,
                         value=sleep_last, unit="h"))
        rows.append(dict(id=f"hp{i}", client_id=client_id,
                         date=prior_week_start + timedelta(days=i),
                         source="whoop", kind=MetricKind.HRV_RMSSD.value,
                         value=hrv_prior, unit="ms"))
    return pd.DataFrame(rows)


def _sessions(client_id, rpe_last, rpe_prior):
    today = date.today()
    last_monday = today - timedelta(days=today.weekday())
    last_week_start = last_monday - timedelta(days=7)
    prior_week_start = last_monday - timedelta(days=14)
    rows = []
    for i in range(4):
        rows.append(dict(date=last_week_start + timedelta(days=i),
                         rpe=rpe_last, client_id=client_id))
        rows.append(dict(date=prior_week_start + timedelta(days=i),
                         rpe=rpe_prior, client_id=client_id))
    return pd.DataFrame(rows)


def test_clean_recovery_yields_standard_progression():
    m = _metrics("c1", hrv_last=55, hrv_prior=54, sleep_last=7.8)
    s = _sessions("c1", rpe_last=6, rpe_prior=6)
    r = generate_recommendation("c1", m, s)
    assert "progression" in r.recommendation.lower()
    assert "deload" not in r.recommendation.lower()


def test_hrv_drop_and_low_sleep_yields_deload():
    m = _metrics("c1", hrv_last=40, hrv_prior=55, sleep_last=6.0)
    s = _sessions("c1", rpe_last=6, rpe_prior=6)
    r = generate_recommendation("c1", m, s)
    assert "deload" in r.recommendation.lower()
    assert r.confidence >= 0.8
    assert len(r.source_metric_ids) > 0


def test_single_flag_yields_conservative():
    m = _metrics("c1", hrv_last=40, hrv_prior=55, sleep_last=7.8)
    s = _sessions("c1", rpe_last=6, rpe_prior=6)
    r = generate_recommendation("c1", m, s)
    assert "conservative" in r.recommendation.lower()
