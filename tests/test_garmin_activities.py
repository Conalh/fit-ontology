"""fetch_activities mapping contract.

Pins what comes out of Garmin's get_activities_by_date response when
fed through fetch_activities: type bucketing, RPE derivation from
Training Effect, deterministic ID dedup, the duration sanity guards.
"""
from __future__ import annotations

from datetime import date

from fit_ontology.garmin import (
    _bucket_type,
    _notes_from_activity,
    _rpe_from_training_effect,
    _session_id,
    fetch_activities,
)
from fit_ontology.ontology import SessionType


class _FakeGarmin:
    """Minimal stand-in — only the methods fetch_activities calls."""

    def __init__(self, activities):
        self._activities = activities

    def get_activities_by_date(self, start: str, end: str):
        return self._activities


def _activity(
    activity_id: int,
    type_key: str,
    *,
    start: str,
    duration_s: float,
    aerobic: float | None = None,
    anaerobic: float | None = None,
    avg_hr: float | None = None,
    distance: float | None = None,
    name: str | None = None,
) -> dict:
    return {
        "activityId": activity_id,
        "activityType": {"typeKey": type_key},
        "startTimeLocal": start,
        "duration": duration_s,
        "aerobicTrainingEffect": aerobic,
        "anaerobicTrainingEffect": anaerobic,
        "averageHR": avg_hr,
        "distance": distance,
        "activityName": name,
    }


# --- Helpers --------------------------------------------------------------

def test_bucket_type_known_keys_route_correctly():
    assert _bucket_type("running") == SessionType.CARDIO
    assert _bucket_type("trail_running") == SessionType.CARDIO
    assert _bucket_type("strength_training") == SessionType.STRENGTH
    assert _bucket_type("yoga") == SessionType.MOBILITY
    assert _bucket_type("hiit") == SessionType.MIXED


def test_bucket_type_unknown_falls_through_to_mixed():
    """Unknown activity types must never silently drop — they bucket to
    MIXED and the trainer can re-classify in the UI."""
    assert _bucket_type("unicycling") == SessionType.MIXED
    assert _bucket_type(None) == SessionType.MIXED


def test_rpe_from_training_effect_takes_max_then_doubles():
    # max(aerobic=3.0, anaerobic=2.0) = 3.0 → RPE 6
    assert _rpe_from_training_effect(3.0, 2.0, None) == 6
    # anaerobic dominant
    assert _rpe_from_training_effect(1.0, 4.5, None) == 9


def test_rpe_falls_back_to_hr_when_te_missing():
    """Lifters / HIIT often produce no aerobicTrainingEffect; we still
    want a meaningful RPE so ACWR isn't silenced."""
    rpe = _rpe_from_training_effect(None, None, 160)
    assert 7 <= rpe <= 9


def test_rpe_defaults_to_moderate_when_nothing_available():
    assert _rpe_from_training_effect(None, None, None) == 5


def test_session_id_is_deterministic():
    a = _session_id(123456789)
    b = _session_id(123456789)
    c = _session_id(987654321)
    assert a == b
    assert a != c
    assert a.startswith("s_garmin_")


def test_notes_combines_name_distance_hr():
    n = _notes_from_activity({
        "activityName": "Tempo Run",
        "distance": 8200,
        "averageHR": 152,
    })
    assert "Tempo Run" in n
    assert "8.2 km" in n
    assert "avg HR 152" in n


def test_notes_drops_default_activity_names():
    n = _notes_from_activity({"activityName": "Activity", "distance": 5000})
    assert "Activity" not in n  # generic name should be filtered
    assert "5.0 km" in n


# --- End-to-end fetch_activities ----------------------------------------

def test_fetch_activities_maps_a_typical_garmin_run():
    fake = _FakeGarmin([
        _activity(
            1001, "running",
            start="2026-05-20 07:15:00",
            duration_s=3000,         # 50 min
            aerobic=3.2,
            anaerobic=0.8,
            avg_hr=158,
            distance=10000,
            name="Tuesday run",
        ),
    ])
    df = fetch_activities(fake, "c_self", lookback_days=14, today=date(2026, 5, 23))
    assert len(df) == 1
    row = df.iloc[0]
    assert row["id"].startswith("s_garmin_")
    assert row["client_id"] == "c_self"
    assert row["date"] == date(2026, 5, 20)
    assert row["type"] == SessionType.CARDIO.value
    assert row["duration_min"] == 50
    # max TE = 3.2 → RPE 6
    assert row["rpe"] == 6
    assert "Tuesday run" in row["notes"]
    assert "10.0 km" in row["notes"]


def test_fetch_activities_skips_zero_and_under_5min_stubs():
    """Heart-rate broadcasts and other Garmin stub entries have zero or
    near-zero duration. They'd pollute ACWR with phantom load."""
    fake = _FakeGarmin([
        _activity(1, "running", start="2026-05-20 07:00:00", duration_s=0),
        _activity(2, "running", start="2026-05-20 08:00:00", duration_s=180),  # 3min
        _activity(3, "running", start="2026-05-20 09:00:00", duration_s=2400),  # 40min — keep
    ])
    df = fetch_activities(fake, "c_self", lookback_days=14, today=date(2026, 5, 23))
    assert len(df) == 1
    assert df.iloc[0]["duration_min"] == 40


def test_fetch_activities_dedupes_within_call():
    """Defensive against Garmin's listing endpoint occasionally
    returning the same activityId twice across paginated pages."""
    fake = _FakeGarmin([
        _activity(42, "running", start="2026-05-20 07:00:00", duration_s=1800),
        _activity(42, "running", start="2026-05-20 07:00:00", duration_s=1800),
    ])
    df = fetch_activities(fake, "c_self", lookback_days=14, today=date(2026, 5, 23))
    assert len(df) == 1


def test_fetch_activities_handles_empty_response():
    fake = _FakeGarmin([])
    df = fetch_activities(fake, "c_self", lookback_days=14, today=date(2026, 5, 23))
    assert df.empty
    # Schema still right so callers don't break.
    assert list(df.columns) == ["id", "client_id", "date", "type", "duration_min", "rpe", "notes"]


def test_fetch_activities_handles_garmin_returning_none():
    """The library returns None when the listing endpoint 401s mid-
    session; _safe_call catches the exception and we fall through to
    an empty frame."""
    class _Broken:
        def get_activities_by_date(self, start, end):
            raise RuntimeError("session expired")

    df = fetch_activities(_Broken(), "c_self", lookback_days=14, today=date(2026, 5, 23))
    assert df.empty


def test_fetch_activities_buckets_strength_correctly():
    fake = _FakeGarmin([
        _activity(
            2001, "strength_training",
            start="2026-05-21 18:00:00",
            duration_s=2700,
            aerobic=1.5,
            anaerobic=3.5,
            avg_hr=120,
        ),
    ])
    df = fetch_activities(fake, "c_self", today=date(2026, 5, 23))
    assert df.iloc[0]["type"] == SessionType.STRENGTH.value
    # max(1.5, 3.5) = 3.5 → RPE 7
    assert df.iloc[0]["rpe"] == 7
