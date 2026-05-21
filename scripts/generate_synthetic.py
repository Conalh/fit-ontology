"""
Generate synthetic clients, sessions, and wearable metrics.

Produces realistic-ish data so the dashboard runs end-to-end from a fresh
clone without anyone needing a Strava account. Three clients chosen to
exercise different reasoning branches:

  alice   — clean recovery, should get standard progression
  ben     — HRV dropping + low sleep, should get deload
  carla   — rising RPE only, should get conservative progression
"""
from __future__ import annotations

import csv
import json
import random
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

random.seed(42)

OUT = Path("data/synthetic")
OUT.mkdir(parents=True, exist_ok=True)

TODAY = date.today()

CLIENTS = [
    dict(
        id="c_alice", name="Alice Romero", sex="F", age=34, height_cm=168, weight_kg=62,
        goal="Half-marathon under 1:50", injury_history="L knee meniscus 2022",
        created_at=datetime(2025, 1, 12, 10, 0).isoformat(sep=" "),
    ),
    dict(
        id="c_ben", name="Ben Okafor", sex="M", age=41, height_cm=183, weight_kg=88,
        goal="General strength, lose 5kg", injury_history="",
        created_at=datetime(2025, 3, 4, 9, 30).isoformat(sep=" "),
    ),
    dict(
        id="c_carla", name="Carla Mendes", sex="F", age=28, height_cm=171, weight_kg=68,
        goal="First powerlifting meet Q4", injury_history="Lower-back strain 2024",
        created_at=datetime(2025, 6, 18, 17, 15).isoformat(sep=" "),
    ),
]


def _write_clients() -> None:
    with (OUT / "clients.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(CLIENTS[0].keys()))
        w.writeheader()
        w.writerows(CLIENTS)


def _gen_sessions(client_id: str, rpe_baseline: int, rpe_drift: float = 0.0) -> list[dict]:
    """Sessions across the last 21 days, 4x/week, drifting RPE optionally."""
    sessions = []
    for d_off in range(21, 0, -1):
        d = TODAY - timedelta(days=d_off)
        if d.weekday() in (1, 3, 5, 6):  # Tue/Thu/Sat/Sun
            week_age = d_off / 7.0
            rpe = max(1, min(10, round(rpe_baseline + random.uniform(-0.5, 0.5)
                                       - rpe_drift * week_age)))
            sessions.append(dict(
                id=f"s_{uuid.uuid4().hex[:10]}",
                client_id=client_id,
                date=d.isoformat(),
                type=random.choice(["strength", "cardio", "mixed", "mobility"]),
                duration_min=random.choice([45, 60, 75]),
                rpe=rpe,
                notes="",
            ))
    return sessions


def _write_sessions() -> None:
    all_s = []
    all_s += _gen_sessions("c_alice", rpe_baseline=6)
    all_s += _gen_sessions("c_ben", rpe_baseline=7)
    all_s += _gen_sessions("c_carla", rpe_baseline=6, rpe_drift=-1.0)  # rising RPE → past weeks lower
    with (OUT / "sessions.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "client_id", "date", "type", "duration_min", "rpe", "notes"])
        w.writeheader()
        w.writerows(all_s)


def _gen_whoop(client_id: str, hrv_mean: float, hrv_drop_last_week: float, sleep_mean: float) -> list[dict]:
    days = []
    for d_off in range(21, 0, -1):
        d = TODAY - timedelta(days=d_off)
        in_last_week = d_off <= 7
        hrv = hrv_mean - (hrv_mean * hrv_drop_last_week if in_last_week else 0) + random.uniform(-3, 3)
        sleep = sleep_mean + random.uniform(-0.6, 0.6)
        days.append(dict(
            date=d.isoformat(),
            hrv_rmssd=round(hrv, 1),
            resting_hr=round(58 + random.uniform(-3, 5), 0),
            sleep_hours=round(sleep, 1),
        ))
    return days


def _write_whoop() -> None:
    (OUT / "whoop_c_alice.json").write_text(json.dumps(
        _gen_whoop("c_alice", hrv_mean=55, hrv_drop_last_week=0.02, sleep_mean=7.6), indent=2))
    (OUT / "whoop_c_ben.json").write_text(json.dumps(
        _gen_whoop("c_ben", hrv_mean=48, hrv_drop_last_week=0.18, sleep_mean=6.3), indent=2))
    (OUT / "whoop_c_carla.json").write_text(json.dumps(
        _gen_whoop("c_carla", hrv_mean=62, hrv_drop_last_week=0.03, sleep_mean=7.4), indent=2))


def _write_strava() -> None:
    """One Strava-style CSV per client with avg/max HR per activity."""
    for cid in ("c_alice", "c_ben", "c_carla"):
        rows = []
        for d_off in range(21, 0, -1):
            d = TODAY - timedelta(days=d_off)
            if d.weekday() in (1, 3, 5):
                rows.append(dict(**{
                    "Activity Date": d.strftime("%b %d, %Y, %I:%M:%S %p"),
                    "Activity Type": random.choice(["Run", "Ride", "Workout"]),
                    "Average Heart Rate": round(random.uniform(135, 158), 0),
                    "Max Heart Rate": round(random.uniform(165, 185), 0),
                    "Elapsed Time": random.choice([2700, 3600, 4500]),
                }))
        path = OUT / f"strava_{cid}.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    _write_clients()
    _write_sessions()
    _write_whoop()
    _write_strava()
    print(f"Synthetic data written to {OUT.resolve()}")
