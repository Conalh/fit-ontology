"""
Generate synthetic clients, sessions, and wearable metrics.

Produces realistic-ish data so the dashboard runs end-to-end from a fresh
clone without anyone needing a Strava account. Five clients chosen to
exercise different reasoning branches AND give the roster a five-row
spread of verdicts (so the demo doesn't read as a three-client toy):

  alice    — clean recovery, should get standard progression
  ben      — HRV dropping + low sleep, should get deload
  carla    — persistent sleep shortfall, should get conservative progression
  holmes   — clean recovery + higher load tolerance, standard
  quixote  — collapsing HRV + sleep deficit, deload

IDs are stable from the original three-client generation — the new
two are appended so anything that hard-codes c_alice/c_ben/c_carla
keeps working. Display names and goals are realistic but entirely
synthetic, so the public demo reads like a credible coaching product.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

OUT = Path("data/synthetic")
OUT.mkdir(parents=True, exist_ok=True)

TODAY = date.today()


def _rng(label: str) -> random.Random:
    """Independent deterministic stream so one persona cannot change another."""
    return random.Random(f"fit-ontology-v2:{label}")

# Realistic fictional coaching profiles. Each maps to the same engine
# behavior as the original Alice/Ben/Carla generation (clean recovery
# → Standard, HRV-dropping + low sleep → Deload, sleep shortfall →
# Conservative); only the public-facing persona changed.
CLIENTS = [
    dict(
        id="c_alice", name="Maya Chen", sex="F", age=34, height_cm=168, weight_kg=62,
        goal="Return to trail running — pain-free 10K by October",
        injury_history="Left ankle sprain in 2024; occasional lateral stiffness",
        created_at=datetime(2025, 1, 12, 10, 0).isoformat(sep=" "),
    ),
    dict(
        id="c_ben", name="Marcus Hill", sex="M", age=41, height_cm=183, weight_kg=88,
        goal="Rebuild half-marathon base — 30 km per week without flare-ups",
        injury_history="Right Achilles tendinopathy history; left shoulder irritation with overhead volume",
        created_at=datetime(2025, 3, 4, 9, 30).isoformat(sep=" "),
    ),
    dict(
        id="c_carla", name="Priya Shah", sex="F", age=28, height_cm=171, weight_kg=68,
        goal="First unassisted pull-up and a 1.5× bodyweight deadlift",
        injury_history="Intermittent low-back stiffness; right wrist tendinopathy",
        created_at=datetime(2025, 6, 18, 17, 15).isoformat(sep=" "),
    ),
    dict(
        id="c_holmes", name="Jordan Brooks", sex="M", age=39, height_cm=188, weight_kg=78,
        goal="Raise cycling FTP for a spring gran fondo",
        injury_history="Right shoulder strain; resolved left wrist sprain",
        created_at=datetime(2025, 2, 20, 11, 45).isoformat(sep=" "),
    ),
    dict(
        id="c_quixote", name="Daniel Ruiz", sex="M", age=52, height_cm=175, weight_kg=70,
        goal="Return to recreational tennis twice weekly",
        injury_history="Prior left knee meniscus repair; chronic lumbar fatigue after long sessions",
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
    rng = _rng(f"sessions:{client_id}")
    for d_off in range(35, 0, -1):
        d = TODAY - timedelta(days=d_off)
        if d.weekday() in (1, 3, 5, 6):  # Tue/Thu/Sat/Sun
            week_age = d_off / 7.0
            rpe = max(1, min(10, round(rpe_baseline + rng.uniform(-0.35, 0.35)
                                       - rpe_drift * week_age)))
            session_key = f"{client_id}|{d.isoformat()}"
            sessions.append(dict(
                id="s_" + hashlib.sha1(session_key.encode("utf-8")).hexdigest()[:10],
                client_id=client_id,
                date=d.isoformat(),
                type=rng.choice(["strength", "cardio", "mixed", "mobility"]),
                duration_min=rng.choice([45, 60, 75]),
                rpe=rpe,
                notes="",
            ))
    return sessions


def _write_sessions() -> None:
    all_s = []
    all_s += _gen_sessions("c_alice", rpe_baseline=6)
    all_s += _gen_sessions("c_ben", rpe_baseline=7)
    all_s += _gen_sessions("c_carla", rpe_baseline=6)
    # Jordan: trains hard (higher baseline RPE) but consistent — Standard.
    all_s += _gen_sessions("c_holmes", rpe_baseline=7)
    # Daniel: pushed too hard recently — Deload signal driven by the
    # whoop side (HRV + sleep), with sessions at a higher baseline RPE
    # so the load picture matches.
    all_s += _gen_sessions("c_quixote", rpe_baseline=8)
    with (OUT / "sessions.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "client_id", "date", "type", "duration_min", "rpe", "notes"])
        w.writeheader()
        w.writerows(all_s)


def _gen_whoop(
    client_id: str,
    hrv_mean: float,
    hrv_drop_last_week: float,
    sleep_mean: float,
    *,
    stable: bool = False,
) -> list[dict]:
    days = []
    rng = _rng(f"whoop:{client_id}")
    for d_off in range(35, 0, -1):
        d = TODAY - timedelta(days=d_off)
        in_last_week = d_off <= 7
        hrv_noise = 0.0 if stable else rng.uniform(-1.8, 1.8)
        sleep_noise = 0.0 if stable else rng.uniform(-0.25, 0.25)
        rhr_noise = 0.0 if stable else rng.uniform(-1.5, 1.5)
        hrv = hrv_mean - (hrv_mean * hrv_drop_last_week if in_last_week else 0) + hrv_noise
        sleep = sleep_mean + sleep_noise
        days.append(dict(
            date=d.isoformat(),
            hrv_rmssd=round(hrv, 1),
            resting_hr=round(58 + rhr_noise, 0),
            sleep_hours=round(sleep, 1),
        ))
    return days


def _write_whoop() -> None:
    (OUT / "whoop_c_alice.json").write_text(json.dumps(
        _gen_whoop("c_alice", hrv_mean=55, hrv_drop_last_week=0.0, sleep_mean=7.6, stable=True), indent=2))
    (OUT / "whoop_c_ben.json").write_text(json.dumps(
        _gen_whoop("c_ben", hrv_mean=48, hrv_drop_last_week=0.18, sleep_mean=6.3), indent=2))
    (OUT / "whoop_c_carla.json").write_text(json.dumps(
        _gen_whoop("c_carla", hrv_mean=62, hrv_drop_last_week=0.0, sleep_mean=6.8, stable=True), indent=2))
    # Jordan: high baseline HRV, no last-week drop; standard progression.
    (OUT / "whoop_c_holmes.json").write_text(json.dumps(
        _gen_whoop("c_holmes", hrv_mean=58, hrv_drop_last_week=0.0, sleep_mean=7.4, stable=True), indent=2))
    # Daniel: heavy last-week HRV collapse + sleep deficit.
    (OUT / "whoop_c_quixote.json").write_text(json.dumps(
        _gen_whoop("c_quixote", hrv_mean=44, hrv_drop_last_week=0.22, sleep_mean=5.8), indent=2))


def _write_strava() -> None:
    """One Strava-style CSV per client with avg/max HR per activity."""
    for cid in ("c_alice", "c_ben", "c_carla", "c_holmes", "c_quixote"):
        rng = _rng(f"strava:{cid}")
        rows = []
        for d_off in range(35, 0, -1):
            d = TODAY - timedelta(days=d_off)
            if d.weekday() in (1, 3, 5):
                rows.append(dict(**{
                    "Activity Date": d.strftime("%b %d, %Y, %I:%M:%S %p"),
                    "Activity Type": rng.choice(["Run", "Ride", "Workout"]),
                    "Average Heart Rate": round(rng.uniform(135, 158), 0),
                    "Max Heart Rate": round(rng.uniform(165, 185), 0),
                    "Elapsed Time": rng.choice([2700, 3600, 4500]),
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
