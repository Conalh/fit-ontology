"""Metric IDs must be deterministic so re-sync upserts instead of duplicating.

The reasoning layer joins on (client_id, date, kind) and assumes a single
row per signal per day per source. Random UUIDs from each sync run
violated that — a Garmin re-sync would write a new row for the same HRV
value on the same day, and a 14-day baseline would silently double-
count it. This file pins the contract that IDs derive from the natural
key.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from fit_ontology.ingest import (
    from_apple_health_export,
    from_whoop_json,
    metric_id,
)


def test_metric_id_is_deterministic():
    a = metric_id("c_ben", date(2026, 5, 18), "hrv_rmssd", "garmin")
    b = metric_id("c_ben", date(2026, 5, 18), "hrv_rmssd", "garmin")
    assert a == b
    assert a.startswith("m_")


def test_metric_id_normalizes_date_type():
    """The migration script reads dates from DuckDB as pandas Timestamps;
    the ingest path passes Python date objects. They must hash to the
    same ID or the migration produces rows that re-sync will duplicate."""
    py_date = metric_id("c_ben", date(2026, 5, 18), "hrv_rmssd", "garmin")
    ts = metric_id("c_ben", pd.Timestamp("2026-05-18"), "hrv_rmssd", "garmin")
    iso = metric_id("c_ben", "2026-05-18", "hrv_rmssd", "garmin")
    iso_with_time = metric_id("c_ben", "2026-05-18 00:00:00", "hrv_rmssd", "garmin")
    assert py_date == ts == iso == iso_with_time


def test_metric_id_changes_with_natural_key():
    base = metric_id("c_ben", date(2026, 5, 18), "hrv_rmssd", "garmin")
    assert base != metric_id("c_alice", date(2026, 5, 18), "hrv_rmssd", "garmin")
    assert base != metric_id("c_ben", date(2026, 5, 19), "hrv_rmssd", "garmin")
    assert base != metric_id("c_ben", date(2026, 5, 18), "resting_hr", "garmin")
    assert base != metric_id("c_ben", date(2026, 5, 18), "hrv_rmssd", "whoop")


def test_whoop_ingest_is_idempotent(tmp_path: Path):
    """Re-running the same Whoop import yields identical IDs, so the
    downstream INSERT OR REPLACE updates rows instead of duplicating."""
    payload = json.dumps([
        {"date": "2026-05-18", "hrv_rmssd": 52.3, "resting_hr": 58, "sleep_hours": 7.4},
        {"date": "2026-05-19", "hrv_rmssd": 48.0, "resting_hr": 60, "sleep_hours": 6.9},
    ])
    p = tmp_path / "whoop.json"
    p.write_text(payload)

    first = from_whoop_json(p, "c_test")
    second = from_whoop_json(p, "c_test")

    pd.testing.assert_frame_equal(first, second)


def test_apple_health_ingest_is_idempotent(tmp_path: Path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData>
<Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" value="50" startDate="2026-05-18 06:00:00 -0700" endDate="2026-05-18 06:00:01 -0700" unit="ms"/>
<Record type="HKQuantityTypeIdentifierRestingHeartRate" value="58" startDate="2026-05-18 07:00:00 -0700" endDate="2026-05-18 07:00:01 -0700" unit="count/min"/>
</HealthData>"""
    p = tmp_path / "export.xml"
    p.write_text(xml)

    first = from_apple_health_export(p, "c_test")
    second = from_apple_health_export(p, "c_test")
    pd.testing.assert_frame_equal(first, second)


def test_strava_collapses_multi_activity_days_to_daily_mean(tmp_path: Path):
    """Two activities on the same day produce one row per kind, valued
    at the mean. Without this, the deterministic ID would cause the
    second activity to overwrite the first silently."""
    csv = (
        "Activity Date,Activity Type,Average Heart Rate,Max Heart Rate,Elapsed Time\n"
        "2026-05-18,Run,140,180,3600\n"
        "2026-05-18,Run,160,190,1800\n"
        "2026-05-19,Run,150,185,3000\n"
    )
    p = tmp_path / "strava.csv"
    p.write_text(csv)

    from fit_ontology.ingest import from_strava_export
    df = from_strava_export(p, "c_test")

    hr_avg_518 = df[(df["date"] == date(2026, 5, 18)) & (df["kind"] == "hr_avg")]
    assert len(hr_avg_518) == 1
    assert hr_avg_518.iloc[0]["value"] == 150.0  # mean of 140 and 160

    hr_max_518 = df[(df["date"] == date(2026, 5, 18)) & (df["kind"] == "hr_max")]
    assert len(hr_max_518) == 1
    assert hr_max_518.iloc[0]["value"] == 185.0  # mean of 180 and 190

    # Other day untouched.
    hr_avg_519 = df[(df["date"] == date(2026, 5, 19)) & (df["kind"] == "hr_avg")]
    assert hr_avg_519.iloc[0]["value"] == 150.0


def test_strava_id_stable_across_runs(tmp_path: Path):
    csv = "Activity Date,Activity Type,Average Heart Rate,Max Heart Rate,Elapsed Time\n2026-05-18,Run,140,180,3600\n"
    p = tmp_path / "strava.csv"
    p.write_text(csv)
    from fit_ontology.ingest import from_strava_export
    a = from_strava_export(p, "c_test")
    b = from_strava_export(p, "c_test")
    assert set(a["id"]) == set(b["id"])
