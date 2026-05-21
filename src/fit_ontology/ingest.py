"""
Ingestion adapters.

Each adapter normalizes its source into the long-format `metrics` schema
defined in ontology.py. Adding a new wearable means writing a new adapter
function and nothing else — no schema migration, no downstream changes.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .ontology import MetricKind, MetricSource


def _mid() -> str:
    return f"m_{uuid.uuid4().hex[:12]}"


def from_strava_export(path: Path, client_id: str) -> pd.DataFrame:
    """
    Strava bulk export ships a CSV of activities. We extract heart-rate and
    duration signals as daily metrics.

    Expected columns (Strava's actual export): Activity Date, Activity Type,
    Average Heart Rate, Max Heart Rate, Elapsed Time
    """
    raw = pd.read_csv(path)
    raw = raw.rename(columns={
        "Activity Date": "date",
        "Average Heart Rate": "hr_avg",
        "Max Heart Rate": "hr_max",
    })
    raw["date"] = pd.to_datetime(raw["date"]).dt.date

    rows = []
    for _, r in raw.iterrows():
        if pd.notna(r.get("hr_avg")):
            rows.append((client_id, r["date"], MetricSource.STRAVA.value,
                         MetricKind.HR_AVG.value, float(r["hr_avg"]), "bpm"))
        if pd.notna(r.get("hr_max")):
            rows.append((client_id, r["date"], MetricSource.STRAVA.value,
                         MetricKind.HR_MAX.value, float(r["hr_max"]), "bpm"))
    df = pd.DataFrame(rows, columns=["client_id", "date", "source", "kind", "value", "unit"])
    df.insert(0, "id", [_mid() for _ in range(len(df))])
    return df[["id", "client_id", "date", "source", "kind", "value", "unit"]]


def from_whoop_json(path: Path, client_id: str) -> pd.DataFrame:
    """
    Whoop's API returns daily recovery records with HRV (RMSSD), resting HR,
    and a sleep score. We use a simplified JSON shape here:
      [{"date": "2026-05-14", "hrv_rmssd": 52.3, "resting_hr": 58, "sleep_hours": 7.4}, ...]
    """
    data = json.loads(Path(path).read_text())
    rows = []
    for d in data:
        day = date.fromisoformat(d["date"])
        if "hrv_rmssd" in d:
            rows.append((client_id, day, MetricSource.WHOOP.value,
                         MetricKind.HRV_RMSSD.value, float(d["hrv_rmssd"]), "ms"))
        if "resting_hr" in d:
            rows.append((client_id, day, MetricSource.WHOOP.value,
                         MetricKind.RESTING_HR.value, float(d["resting_hr"]), "bpm"))
        if "sleep_hours" in d:
            rows.append((client_id, day, MetricSource.WHOOP.value,
                         MetricKind.SLEEP_HOURS.value, float(d["sleep_hours"]), "h"))
    df = pd.DataFrame(rows, columns=["client_id", "date", "source", "kind", "value", "unit"])
    df.insert(0, "id", [_mid() for _ in range(len(df))])
    return df


def from_intake_csv(path: Path) -> pd.DataFrame:
    """
    Trainer's own intake form export. Required columns:
      id, name, sex, age, height_cm, weight_kg, goal, injury_history, created_at
    """
    df = pd.read_csv(path)
    df["created_at"] = pd.to_datetime(df["created_at"])
    return df


def from_session_log_csv(path: Path) -> pd.DataFrame:
    """Required columns: id, client_id, date, type, duration_min, rpe, notes"""
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df
