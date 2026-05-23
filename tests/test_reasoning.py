"""Tests for the v0.2 reasoning layer.

These exercise the literature-backed signals:
  - HRV vs 28-day baseline in SD units (Plews & Laursen)
  - ACWR from sRPE × duration (Gabbett)
  - Resting HR drift vs baseline (Buchheit)
  - Sleep against ACSM 11e floors
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd

from fit_ontology.ontology import MetricKind
from fit_ontology.reasoning import (
    CITATIONS,
    compute_recovery_score,
    detect_acwr_signal,
    detect_hrv_trend_signal,
    detect_rhr_trend_signal,
    detect_rpe_signal,
    detect_sleep_signal,
    detect_sleep_trend_signal,
    detect_training_readiness_signal,
    generate_recommendation,
)

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
    """A single mild HRV deviation → conservative progression.

    The fixture's jitter is deterministically seeded (random.Random
    keyed by metric kind + baseline), so this assertion is stable
    across pytest runs. The earlier hedge "conservative or standard,
    both acceptable" hid the actual contract — pin it.
    """
    today = date.today()
    m = _metrics("c1", today=today, hrv_baseline=55, hrv_acute=51, sleep_acute=7.8)
    s = _sessions("c1", today=today, rpe_baseline=6)
    r = generate_recommendation("c1", m, s, today=today)
    assert "conservative progression" in r.recommendation.lower()


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


# --- Training Readiness (Garmin composite) ----------------------------------

def _tr_metrics(client_id: str, today: date, mean_tr: float) -> pd.DataFrame:
    rows = _stable_metric(
        client_id, MetricKind.TRAINING_READINESS.value, mean_tr, today,
        jitter=2, days=21, acute_days=7, unit="",
    )
    return pd.DataFrame(rows)


def test_training_readiness_high_does_not_fire():
    today = date.today()
    sig = detect_training_readiness_signal(_tr_metrics("c1", today, 75), today)
    assert sig is None


def test_training_readiness_low_fires_moderate_or_severe():
    today = date.today()
    sig = detect_training_readiness_signal(_tr_metrics("c1", today, 40), today)
    assert sig is not None
    assert sig.severity in ("moderate", "mild")
    assert sig.kind == "training_readiness_low"
    assert sig.source_metric_ids  # carries IDs of the 7-day acute window


def test_training_readiness_very_low_is_severe():
    today = date.today()
    sig = detect_training_readiness_signal(_tr_metrics("c1", today, 22), today)
    assert sig is not None
    assert sig.severity == "severe"


# --- Session source IDs on ACWR / RPE signals -------------------------------

def test_acwr_signal_carries_session_source_ids():
    """The ACWR detector should cite session IDs that fed the load math,
    closing the same audit-trail loop the metric-based signals have."""
    today = date.today()
    # Spike acute week's RPE to drive ACWR high.
    s = _sessions("c1", today=today, rpe_baseline=5, rpe_acute=10)
    sig = detect_acwr_signal(s, today)
    assert sig is not None
    assert sig.source_metric_ids, "ACWR signal must cite contributing session IDs"
    assert all(sid.startswith("s-") for sid in sig.source_metric_ids)


def test_rpe_signal_carries_session_source_ids():
    today = date.today()
    s = _sessions("c1", today=today, rpe_baseline=5, rpe_acute=8)
    sig = detect_rpe_signal(s, today)
    assert sig is not None
    assert sig.source_metric_ids
    assert all(sid.startswith("s-") for sid in sig.source_metric_ids)


# --- Rationale upgrade: specifics + inline citations -------------------

def test_signal_summaries_include_their_citations():
    """Each rule's source authority should appear inline in the rationale —
    not just in a module docstring — so the trainer reading the rec
    sees which paper drives each call."""
    today = date.today()
    # HRV crash + sleep deficit + ACWR spike + RPE rise, all at once.
    m = _metrics("c1", today=today, hrv_baseline=55, hrv_acute=40,
                 rhr_baseline=58, rhr_acute=65, sleep_acute=5.5)
    s = _sessions("c1", today=today, rpe_baseline=5, rpe_acute=9, duration_min=90)
    r = generate_recommendation("c1", m, s, today=today)

    # Every citation that *could* have fired should be present given this
    # cocktail of stressors. TR isn't fed by the fixture so we skip it.
    for key in ("hrv", "rhr", "sleep", "acwr", "rpe"):
        assert CITATIONS[key] in r.rationale, f"missing {key} citation in rationale"


# --- Trend slope detection ---------------------------------------------

def _falling_hrv(today: date, start: float = 55, end: float = 45, days: int = 28) -> pd.DataFrame:
    """Build HRV history that falls linearly from `start` to `end` over `days`.
    Used for trend tests — we want a clearly directional slope so the
    detector doesn't have to fight noise."""
    rows = []
    for offset in range(days, 0, -1):
        d = today - timedelta(days=offset)
        # Most-recent day is `end`; oldest is `start`. Linear ramp.
        t = (days - offset) / max(1, days - 1)
        value = start + (end - start) * t
        rows.append(dict(
            id=f"hrv-{offset}",
            client_id="c1", date=d,
            source="garmin", kind=MetricKind.HRV_RMSSD.value,
            value=value, unit="ms",
        ))
    return pd.DataFrame(rows)


def test_hrv_trend_signal_fires_when_falling():
    """A clearly downward HRV trajectory over the last 7 days should fire
    the trend detector even before the level signal trips."""
    today = date.today()
    m = _falling_hrv(today, start=55, end=42, days=28)
    sig = detect_hrv_trend_signal(m, today)
    assert sig is not None
    assert sig.kind == "hrv_trend_down"
    assert "trending down" in sig.summary.lower()
    assert CITATIONS["hrv"] in sig.summary


def test_hrv_trend_signal_does_not_fire_when_rising():
    """Rising HRV is a good thing — detector must not flag it."""
    today = date.today()
    m = _falling_hrv(today, start=42, end=55, days=28)  # reversed: rising
    sig = detect_hrv_trend_signal(m, today)
    assert sig is None


def test_rhr_trend_signal_fires_when_rising():
    """Rising resting HR — the bad direction for RHR — fires the trend
    detector. Symmetric mirror of the HRV-falling case."""
    today = date.today()
    rows = []
    for offset in range(28, 0, -1):
        d = today - timedelta(days=offset)
        t = (28 - offset) / 27
        value = 55 + 8 * t  # 55 → 63 bpm over the window
        rows.append(dict(
            id=f"rhr-{offset}",
            client_id="c1", date=d,
            source="garmin", kind=MetricKind.RESTING_HR.value,
            value=value, unit="bpm",
        ))
    sig = detect_rhr_trend_signal(pd.DataFrame(rows), today)
    assert sig is not None
    assert sig.kind == "rhr_trend_up"


def test_sleep_trend_signal_fires_when_eroding():
    """Mean might still clear the floor, but a clear downward slope on
    nightly hours should fire as an early warning."""
    today = date.today()
    rows = []
    for offset in range(28, 0, -1):
        d = today - timedelta(days=offset)
        t = (28 - offset) / 27
        value = 8.5 - 1.5 * t  # 8.5h → 7.0h over the window
        rows.append(dict(
            id=f"sleep-{offset}",
            client_id="c1", date=d,
            source="garmin", kind=MetricKind.SLEEP_HOURS.value,
            value=value, unit="h",
        ))
    sig = detect_sleep_trend_signal(pd.DataFrame(rows), today)
    assert sig is not None
    assert sig.kind == "sleep_trend_down"


# --- Composite recovery score ------------------------------------------

def test_recovery_score_perfect_when_everything_clean():
    """At-baseline HRV, normal sleep, normal RHR, ACWR in the sweet spot
    → composite should be at or near 100."""
    today = date.today()
    m = _metrics("c1", today=today, hrv_baseline=55, hrv_acute=None,
                 rhr_baseline=58, rhr_acute=None, sleep_acute=7.8)
    s = _sessions("c1", today=today, rpe_baseline=6)
    score = compute_recovery_score(m, s, today=today)
    assert score.composite is not None
    assert score.composite >= 90, f"expected near-perfect, got {score.composite}"


def test_recovery_score_low_when_stressed():
    """HRV crashed, sleep deficit — composite should sit in the low half."""
    today = date.today()
    m = _metrics("c1", today=today, hrv_baseline=55, hrv_acute=40,
                 rhr_baseline=58, rhr_acute=65, sleep_acute=5.5)
    s = _sessions("c1", today=today, rpe_baseline=6)
    score = compute_recovery_score(m, s, today=today)
    assert score.composite is not None
    assert score.composite <= 50, f"expected stressed score, got {score.composite}"


def test_recovery_score_handles_missing_components():
    """If a component has no data, the remaining weights re-normalize.
    Composite should reflect available components, not crash or return 0."""
    today = date.today()
    # No sleep data, no sessions — only HRV + RHR feed the composite.
    m = _metrics("c1", today=today, hrv_baseline=55, hrv_acute=None,
                 rhr_baseline=58, rhr_acute=None, sleep_acute=None)
    s = pd.DataFrame(columns=["id", "client_id", "date", "type", "duration_min", "rpe", "notes"])
    score = compute_recovery_score(m, s, today=today)
    assert score.sleep is None
    assert score.acwr is None
    assert score.hrv is not None and score.rhr is not None
    assert score.composite is not None  # measurable from HRV + RHR alone


def test_recovery_score_components_clamp_into_severe_band():
    """An HRV crash drives the HRV sub-score into the past-severe band.
    We assert <25 rather than ==0 because the 28-day baseline window
    overlaps the 7-day acute window — the crash dilutes the baseline
    mean and inflates its SD, so drop-SD reads smaller than the bare
    delta would suggest. Engine behavior is unchanged; the test just
    accounts for it."""
    today = date.today()
    m = _metrics("c1", today=today, hrv_baseline=55, hrv_acute=33, sleep_acute=7.8)
    s = _sessions("c1", today=today, rpe_baseline=6)
    score = compute_recovery_score(m, s, today=today)
    assert score.hrv is not None and score.hrv < 25


def test_sleep_signal_counts_nights_below_floor():
    """Mean alone hides the shape — a 6.8 h average can mean five 8h nights
    and two 4h nights. Detector should count nights actually below the
    floor so the rationale carries the texture of the deficit."""
    today = date.today()
    # 7 nights of sleep; 4 nights at 5h, 3 nights at 8h → mean ~6.3h
    rows = []
    for offset, hours in enumerate([5, 5, 5, 5, 8, 8, 8], start=1):
        rows.append(dict(
            id=f"sleep-{offset}",
            client_id="c1", date=today - timedelta(days=offset),
            source="garmin", kind=MetricKind.SLEEP_HOURS.value,
            value=hours, unit="h",
        ))
    sig = detect_sleep_signal(pd.DataFrame(rows), today)
    assert sig is not None
    # Both the mean and the count of below-floor nights should appear.
    assert "4 of 7" in sig.summary
    assert "h floor" in sig.summary
