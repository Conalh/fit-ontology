"""
Garmin Connect adapter.

Garmin doesn't publish a free consumer API; we use the community-maintained
python-garminconnect library, which authenticates against the same SSO flow
the Garmin Connect website uses. Token state is cached in ~/.garminconnect/
so re-runs are seamless until the session expires (~30 days). MFA is
supported via a prompt callback that only fires when Garmin demands a code.

Trade-offs called out so a reader of the README knows what they're using:
  - Unofficial. Garmin can change the SSO flow at any time.
  - Personal-use only. Don't ship this in a hosted product without applying
    to the Garmin Health API.
  - Slow first login (~5-10s); subsequent calls hit the cached token.

What we extract:
  - HRV Status, sleep, resting HR, Body Battery, stress, training readiness
    — the daily-cadence signals the reasoning layer joins against.
  - Workout activities — auto-imported as Session rows so the trainer
    doesn't manually log every workout. RPE is derived from Garmin's
    Training Effect (the closest analogue Garmin exposes); the trainer
    can still log their own session separately for perceived effort.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .ingest import _assign_metric_ids
from .ontology import MetricKind, MetricSource, SessionType

DEFAULT_TOKEN_DIR = Path.home() / ".garminconnect"
DEFAULT_LOOKBACK_DAYS = 14


def make_garmin_client(
    email: str,
    password: str,
    *,
    token_dir: Path = DEFAULT_TOKEN_DIR,
    mfa_prompt: Callable[[], str] | None = None,
):
    """
    Return an authenticated garminconnect.Garmin client.

    On first run (or after token expiry) Garmin SSO will run; if the account
    has 2FA, ``mfa_prompt`` is invoked exactly once for a code. We import
    inside the function so the rest of the package (and its tests) don't
    require garminconnect at import time.
    """
    from garminconnect import Garmin  # local import: optional dep

    token_dir.mkdir(parents=True, exist_ok=True)

    # The library accepts prompt_mfa starting at 0.2.x; passing it is a no-op
    # if MFA isn't enabled on the account. dict[str, Any] because mfa_prompt
    # is a Callable and the literal init would otherwise narrow to dict[str, str].
    kwargs: dict[str, object] = {"email": email, "password": password}
    if mfa_prompt is not None:
        kwargs["prompt_mfa"] = mfa_prompt

    client = Garmin(**kwargs)
    # Try to resume cached session; fall back to fresh login.
    try:
        client.login(str(token_dir))
    except Exception:
        client.login(str(token_dir))
    return client


def fetch_daily_metrics(
    client,
    client_id: str,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    today: date | None = None,
) -> pd.DataFrame:
    """
    Pull the daily-cadence signals we care about into the long-format
    metrics schema. One row per (client, date, kind, source).

    Returns an empty DataFrame on no data — never raises for missing days.
    """
    today = today or date.today()
    days = [today - timedelta(days=offset) for offset in range(lookback_days, 0, -1)]
    rows: list[tuple] = []

    for day in days:
        iso = day.isoformat()
        rows.extend(_extract_hrv(client, client_id, iso))
        rows.extend(_extract_sleep(client, client_id, iso))
        rows.extend(_extract_resting_hr(client, client_id, iso))
        rows.extend(_extract_body_battery(client, client_id, iso))
        rows.extend(_extract_stress(client, client_id, iso))
        rows.extend(_extract_training_readiness(client, client_id, iso))

    df = pd.DataFrame(rows, columns=["client_id", "date", "source", "kind", "value", "unit"])
    if df.empty:
        return df.assign(id=[]).loc[:, ["id", "client_id", "date", "source", "kind", "value", "unit"]]

    df["date"] = pd.to_datetime(df["date"]).dt.date
    return _assign_metric_ids(df)[["id", "client_id", "date", "source", "kind", "value", "unit"]]


# Each extractor is wrapped in a guarded call: Garmin endpoints occasionally
# 404 for a day with no data, or return a partial shape. We swallow per-day
# errors so one bad day doesn't take down the whole sync.

def _safe_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


def _extract_hrv(client, client_id: str, iso: str) -> Iterable[tuple]:
    data = _safe_call(client.get_hrv_data, iso)
    if not data:
        return []
    summary = data.get("hrvSummary") or {}
    last_night = summary.get("lastNightAvg")
    if last_night is None:
        return []
    return [(client_id, iso, MetricSource.GARMIN.value, MetricKind.HRV_RMSSD.value, float(last_night), "ms")]


def _extract_sleep(client, client_id: str, iso: str) -> Iterable[tuple]:
    data = _safe_call(client.get_sleep_data, iso)
    if not data:
        return []
    daily = data.get("dailySleepDTO") or {}
    seconds = daily.get("sleepTimeSeconds")
    score_block = daily.get("sleepScores") or {}
    overall = (score_block.get("overall") or {}).get("value")

    rows: list[tuple] = []
    if seconds:
        hours = float(seconds) / 3600.0
        rows.append((client_id, iso, MetricSource.GARMIN.value, MetricKind.SLEEP_HOURS.value, hours, "h"))
    if overall is not None:
        rows.append((client_id, iso, MetricSource.GARMIN.value, MetricKind.SLEEP_SCORE.value, float(overall), "score"))
    return rows


def _extract_resting_hr(client, client_id: str, iso: str) -> Iterable[tuple]:
    # The user-summary endpoint carries restingHeartRate alongside other
    # day-level rollups. It's the same value the watch shows on the device.
    data = _safe_call(client.get_user_summary, iso)
    if not data:
        return []
    rhr = data.get("restingHeartRate")
    if rhr is None:
        return []
    return [(client_id, iso, MetricSource.GARMIN.value, MetricKind.RESTING_HR.value, float(rhr), "bpm")]


def _extract_body_battery(client, client_id: str, iso: str) -> Iterable[tuple]:
    data = _safe_call(client.get_body_battery, iso, iso)
    if not data:
        return []
    # API returns a list of daily entries; for a single day we expect one.
    entry = data[0] if isinstance(data, list) and data else None
    if not entry:
        return []
    high = entry.get("charged") if entry.get("charged") is not None else entry.get("max")
    low = entry.get("drained") if entry.get("drained") is not None else entry.get("min")

    rows: list[tuple] = []
    if high is not None:
        rows.append((client_id, iso, MetricSource.GARMIN.value, MetricKind.BODY_BATTERY_HIGH.value, float(high), "pct"))
    if low is not None:
        rows.append((client_id, iso, MetricSource.GARMIN.value, MetricKind.BODY_BATTERY_LOW.value, float(low), "pct"))
    return rows


def _extract_stress(client, client_id: str, iso: str) -> Iterable[tuple]:
    data = _safe_call(client.get_stress_data, iso)
    if not data:
        return []
    avg = data.get("avgStressLevel")
    if avg is None or avg < 0:
        return []
    return [(client_id, iso, MetricSource.GARMIN.value, MetricKind.STRESS_AVG.value, float(avg), "score")]


def _extract_training_readiness(client, client_id: str, iso: str) -> Iterable[tuple]:
    # Available on devices that compute it (Venu 3, Forerunner 9xx series,
    # Fenix 7/8, etc.). For devices that don't, the call returns an empty
    # list and we skip the day silently.
    data = _safe_call(client.get_training_readiness, iso)
    if not data:
        return []
    entry = data[0] if isinstance(data, list) and data else data
    score = entry.get("score") if isinstance(entry, dict) else None
    if score is None:
        return []
    return [(client_id, iso, MetricSource.GARMIN.value, MetricKind.TRAINING_READINESS.value, float(score), "score")]


# ─── Activities → Sessions ────────────────────────────────────────────
#
# Garmin sees every workout the trainer's client logs on the watch.
# Importing those as Session rows is the difference between a trainer
# manually entering RPE every day and the system having a real view of
# the client's load. RPE is the one thing Garmin doesn't measure
# directly — but Garmin's Training Effect is a sufficient proxy:
# anaerobic + aerobic effect (each 0-5) maps cleanly to perceived
# exertion on the same range the trainer's manual RPE uses.
#
# Trainer-logged sessions and Garmin-imported sessions coexist; they're
# distinguished by ID prefix (``s_garmin_*`` vs ``s_*``) and the
# insert-or-replace upsert dedupes Garmin re-syncs by activity_id.


# Garmin's activityType.typeKey strings map into our four-bucket Session
# scheme. Unknown keys fall through to MIXED so an activity is never
# silently dropped — the trainer can edit the session afterwards if a
# wrong bucket lands.
_TYPE_BUCKETS: dict[str, SessionType] = {
    # Cardio
    "running": SessionType.CARDIO,
    "trail_running": SessionType.CARDIO,
    "treadmill_running": SessionType.CARDIO,
    "track_running": SessionType.CARDIO,
    "cycling": SessionType.CARDIO,
    "indoor_cycling": SessionType.CARDIO,
    "mountain_biking": SessionType.CARDIO,
    "road_biking": SessionType.CARDIO,
    "gravel_cycling": SessionType.CARDIO,
    "swimming": SessionType.CARDIO,
    "lap_swimming": SessionType.CARDIO,
    "open_water_swimming": SessionType.CARDIO,
    "rowing": SessionType.CARDIO,
    "elliptical": SessionType.CARDIO,
    "walking": SessionType.CARDIO,
    "hiking": SessionType.CARDIO,
    # Strength
    "strength_training": SessionType.STRENGTH,
    "weight_training": SessionType.STRENGTH,
    "indoor_climbing": SessionType.STRENGTH,
    "bouldering": SessionType.STRENGTH,
    # Mobility / recovery
    "yoga": SessionType.MOBILITY,
    "pilates": SessionType.MOBILITY,
    "stretching": SessionType.MOBILITY,
    "breathwork": SessionType.MOBILITY,
    # Mixed (intervals / circuit / cross-training)
    "hiit": SessionType.MIXED,
    "circuit_training": SessionType.MIXED,
    "crossfit": SessionType.MIXED,
    "boxing": SessionType.MIXED,
    "martial_arts": SessionType.MIXED,
}


def _bucket_type(type_key: str | None) -> SessionType:
    if not type_key:
        return SessionType.MIXED
    return _TYPE_BUCKETS.get(type_key.lower(), SessionType.MIXED)


def _rpe_from_training_effect(
    aerobic: float | None,
    anaerobic: float | None,
    avg_hr: float | None,
) -> int:
    """Estimate session RPE (1-10) from what Garmin actually measures.

    Training Effect runs 0-5 per channel — Garmin's own model of how
    much stress the workout imposed. We take the max of aerobic +
    anaerobic and double it (0-10 range), then nudge by avg HR for
    short-but-intense sessions Training Effect can underweight.

    Falls back to a low-confidence value of 5 (moderate) when neither
    Training Effect nor HR is available — the trainer can override the
    session if they have a different feel for it.
    """
    candidates: list[float] = []
    if aerobic is not None:
        candidates.append(float(aerobic))
    if anaerobic is not None:
        candidates.append(float(anaerobic))
    if candidates:
        te = max(candidates)
        rpe = te * 2
    elif avg_hr is not None:
        # No TE? Map HR percentage of a fixed reference (180 bpm) to RPE.
        # Rough — but better than zero, which would silence ACWR.
        rpe = min(10.0, max(1.0, (float(avg_hr) / 180.0) * 10.0))
    else:
        rpe = 5.0
    return max(1, min(10, round(rpe)))


def _session_id(activity_id: int | str) -> str:
    """Deterministic session ID from a Garmin activityId so re-syncs
    upsert via the PK instead of duplicating. ``activityId`` is unique
    per workout in Garmin's system."""
    raw = f"garmin:{activity_id}"
    return "s_garmin_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _notes_from_activity(act: dict) -> str:
    """One-line summary the trainer sees in the sessions table. Names +
    key stats, no fluff. Capped at ~80 chars so the sessions UI doesn't
    wrap."""
    parts: list[str] = []
    name = (act.get("activityName") or "").strip()
    if name and name.lower() not in {"activity", "workout"}:
        parts.append(name)
    dist_m = act.get("distance")
    if isinstance(dist_m, (int, float)) and dist_m > 0:
        km = dist_m / 1000.0
        parts.append(f"{km:.1f} km" if km >= 1 else f"{int(dist_m)} m")
    avg_hr = act.get("averageHR")
    if isinstance(avg_hr, (int, float)) and avg_hr > 0:
        parts.append(f"avg HR {int(avg_hr)}")
    out = " · ".join(parts)
    return out[:80]


def fetch_activities(
    client,
    client_id: str,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    today: date | None = None,
) -> pd.DataFrame:
    """Pull recent activities and map them to Session rows.

    The garminconnect library exposes ``get_activities_by_date(start,
    end)`` — Garmin's own paginated activity list. We pull the window,
    bucket each activity's type, derive RPE from Training Effect, and
    return a DataFrame in the Sessions schema shape (id, client_id,
    date, type, duration_min, rpe, notes) ready for ``insert_sessions``.

    Activities with zero duration (heart-rate broadcasts, stub entries)
    are dropped — they'd skew ACWR with phantom load.
    """
    today = today or date.today()
    start = today - timedelta(days=lookback_days)

    raw = _safe_call(client.get_activities_by_date, start.isoformat(), today.isoformat())
    if not raw:
        return pd.DataFrame(columns=["id", "client_id", "date", "type", "duration_min", "rpe", "notes"])

    rows: list[dict] = []
    for act in raw:
        if not isinstance(act, dict):
            continue
        activity_id = act.get("activityId")
        if activity_id is None:
            continue
        duration_s = act.get("duration")
        if not isinstance(duration_s, (int, float)) or duration_s <= 0:
            continue
        # Clamp duration_min into the Session model's 5-300 range. Sub-5
        # is almost certainly a stub; >300 is a multi-day adventure
        # ride; the model rejects either anyway.
        duration_min = int(round(duration_s / 60))
        if duration_min < 5 or duration_min > 300:
            continue

        start_iso = act.get("startTimeLocal") or act.get("startTimeGMT")
        if not start_iso:
            continue
        day = date.fromisoformat(start_iso.split(" ", 1)[0].split("T", 1)[0])

        type_key = (act.get("activityType") or {}).get("typeKey")
        rpe = _rpe_from_training_effect(
            act.get("aerobicTrainingEffect"),
            act.get("anaerobicTrainingEffect"),
            act.get("averageHR"),
        )

        rows.append({
            "id": _session_id(activity_id),
            "client_id": client_id,
            "date": day,
            "type": _bucket_type(type_key).value,
            "duration_min": duration_min,
            "rpe": rpe,
            "notes": _notes_from_activity(act),
        })

    df = pd.DataFrame(
        rows,
        columns=["id", "client_id", "date", "type", "duration_min", "rpe", "notes"],
    )
    if not df.empty:
        # Same-activity dedupe — if Garmin's listing returned the same
        # activity twice (shouldn't, but be defensive), keep the first.
        df = df.drop_duplicates(subset=["id"], keep="first").reset_index(drop=True)
    return df
