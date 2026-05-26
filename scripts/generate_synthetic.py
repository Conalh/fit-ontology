"""
Generate synthetic clients, sessions, and wearable metrics.

Produces realistic-ish data so the dashboard runs end-to-end from a fresh
clone without anyone needing a Strava account. Five clients chosen to
exercise different reasoning branches AND give the roster a five-row
spread of verdicts (so the demo doesn't read as a three-client toy):

  alice    — clean recovery, should get standard progression
  ben      — HRV dropping + low sleep, should get deload
  carla    — rising RPE only, should get conservative progression
  holmes   — clean recovery + higher load tolerance, standard
  quixote  — collapsing HRV + sleep deficit (post-windmill), deload

IDs are stable from the original three-client generation — the new
two are appended so anything that hard-codes c_alice/c_ben/c_carla
keeps working. Display names are classic-literature characters with
silly fitness goals; the timeseries shapes are the same as the
original synthetic dataset, just relabelled.
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

# Classic-literature characters with silly fitness goals — the
# synthetic roster doubles as a portfolio gag without changing any of
# the underlying timeseries shapes. Each maps to the same engine
# behaviour as the previous Alice/Ben/Carla generation (clean recovery
# → Standard, HRV-dropping + low sleep → Deload, rising RPE →
# Conservative); only the names, goals, and injury text changed.
CLIENTS = [
    dict(
        id="c_alice", name="Elizabeth Bennet", sex="F", age=34, height_cm=168, weight_kg=62,
        goal="Walk to Netherfield without muddied petticoats — sub-90 min twice weekly",
        injury_history="L ankle turn on Hertfordshire walks 2024",
        created_at=datetime(2025, 1, 12, 10, 0).isoformat(sep=" "),
    ),
    dict(
        id="c_ben", name="Captain Ahab", sex="M", age=41, height_cm=183, weight_kg=88,
        goal="Single-leg harpoon throw — 50m accuracy by next sighting",
        injury_history="R below-knee amputation (Moby Dick); R rotator cuff strain from harpoon volume",
        created_at=datetime(2025, 3, 4, 9, 30).isoformat(sep=" "),
    ),
    dict(
        id="c_carla", name="Lady Macbeth", sex="F", age=28, height_cm=171, weight_kg=68,
        goal="Build wrist + grip endurance for nightly handwashing routine",
        injury_history="Lower-back strain (candle-lit pacing); R wrist tendinopathy",
        created_at=datetime(2025, 6, 18, 17, 15).isoformat(sep=" "),
    ),
    dict(
        id="c_holmes", name="Sherlock Holmes", sex="M", age=39, height_cm=188, weight_kg=78,
        goal="VO2 max for rooftop chases; four-minute violin endurance unbroken",
        injury_history="R shoulder strain (boxing); L wrist sprain (singlestick fencing)",
        created_at=datetime(2025, 2, 20, 11, 45).isoformat(sep=" "),
    ),
    dict(
        id="c_quixote", name="Don Quixote", sex="M", age=52, height_cm=175, weight_kg=70,
        goal="Joust a windmill — and win",
        injury_history="Multiple rib contusions (windmill incident); chronic lumbar fatigue from sustained tilting",
        created_at=datetime(2025, 4, 30, 14, 20).isoformat(sep=" "),
    ),
]


def _write_clients() -> None:
    # encoding="utf-8" explicit because the default on Windows is the
    # locale codepage (cp1252 on most US installs) which renders
    # em-dashes (U+2014) and other non-ASCII as bytes pandas can't
    # decode on read (the ingest pipeline assumes UTF-8). Without
    # this the file looks fine in Excel but blows up read_csv.
    with (OUT / "clients.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(CLIENTS[0].keys()))
        w.writeheader()
        w.writerows(CLIENTS)


def _gen_sessions(client_id: str, rpe_baseline: int, rpe_drift: float = 0.0) -> list[dict]:
    """Sessions across the last 35 days, 4x/week, drifting RPE optionally.

    Window extended from 21 → 35 days in engine-v2 / E2 so the 28-day
    EWMA chronic detector has room to operate. The session-drift math
    is unchanged — older sessions still get a higher (or lower) RPE
    proportional to ``week_age`` and ``rpe_drift``, so the existing
    "rising RPE" character profiles read the same shape, just longer.
    """
    sessions = []
    for d_off in range(35, 0, -1):
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
    # Holmes: trains hard (higher baseline RPE) but consistent — Standard.
    all_s += _gen_sessions("c_holmes", rpe_baseline=7)
    # Quixote: pushed too hard recently — Deload signal driven by the
    # whoop side (HRV + sleep), with sessions at a higher baseline RPE
    # so the load picture matches.
    all_s += _gen_sessions("c_quixote", rpe_baseline=8)
    with (OUT / "sessions.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "client_id", "date", "type", "duration_min", "rpe", "notes"])
        w.writeheader()
        w.writerows(all_s)


def _gen_whoop(client_id: str, hrv_mean: float, hrv_drop_last_week: float, sleep_mean: float) -> list[dict]:
    days = []
    for d_off in range(35, 0, -1):
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
    # Holmes: high baseline HRV, no last-week drop — the great
    # detective's recovery is impeccable; standard progression.
    (OUT / "whoop_c_holmes.json").write_text(json.dumps(
        _gen_whoop("c_holmes", hrv_mean=58, hrv_drop_last_week=0.01, sleep_mean=7.4), indent=2))
    # Quixote: heavy last-week HRV collapse + sleep deficit. The
    # windmill incident shows up as a textbook deload signal.
    (OUT / "whoop_c_quixote.json").write_text(json.dumps(
        _gen_whoop("c_quixote", hrv_mean=44, hrv_drop_last_week=0.22, sleep_mean=5.8), indent=2))


def _write_strava() -> None:
    """One Strava-style CSV per client with avg/max HR per activity."""
    for cid in ("c_alice", "c_ben", "c_carla", "c_holmes", "c_quixote"):
        rows = []
        for d_off in range(35, 0, -1):
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
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    _write_clients()
    _write_sessions()
    _write_whoop()
    _write_strava()
    print(f"Synthetic data written to {OUT.resolve()}")
