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

What we extract: HRV Status, sleep, resting HR, Body Battery, stress, and
training readiness — the daily-cadence signals the reasoning layer joins
against. Activities (workouts) come in a later pass.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd

from .ingest import _assign_metric_ids
from .ontology import MetricKind, MetricSource

DEFAULT_TOKEN_DIR = Path.home() / ".garminconnect"
DEFAULT_LOOKBACK_DAYS = 14


def make_garmin_client(
    email: str,
    password: str,
    *,
    token_dir: Path = DEFAULT_TOKEN_DIR,
    mfa_prompt: Optional[Callable[[], str]] = None,
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
    # if MFA isn't enabled on the account.
    kwargs = {"email": email, "password": password}
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
    today: Optional[date] = None,
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
