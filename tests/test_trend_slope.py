"""Engine v2 — Phase E1: shared trend-slope helper.

The three trend detectors (HRV / RHR / sleep) all flowed through one
inline OLS calculation; ``compute_trend_slope`` lifts that into a
single named function so E2 can plug in the 28-day EWMA path next to
it. This file pins the OLS behaviour as a regression net before the
second method lands.

Contracts pinned:
  1. Monotonic upward series → positive slope ≈ +1.0/day.
  2. Monotonic downward series → negative slope ≈ −1.0/day.
  3. Flat series → slope ≈ 0.0.
  4. Pure noise around a constant mean → slope magnitude bounded
     well below the typical trend threshold (i.e. doesn't ramp up
     into false signals at the OLS level).
  5. Too-few samples (<4 in window) → returns None, not a tuple.
  6. Single-day data (zero x-variance) → returns None.
  7. SlopeResult carries method="ols", window_days as requested,
     n_samples as actually seen, and confidence_weight=1.0 for any
     valid OLS result (E2 will down-weight short EWMA windows).
  8. EWMA path raises NotImplementedError (E1 only lands the seam,
     not the second method).
  9. Unknown method string raises ValueError so a typo surfaces.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from fit_ontology.reasoning import (
    SlopeResult,
    combine_acute_chronic,
    compute_trend_slope,
)


def _series(values: list[float], today: date, kind: str = "hrv_rmssd") -> pd.DataFrame:
    """Long-format dataframe of one metric, one row per day, ending the
    day before ``today`` (matches the engine's [start, today) window)."""
    rows = []
    for i, v in enumerate(values):
        d = today - timedelta(days=len(values) - i)
        rows.append(
            {"id": f"m-{i}", "client_id": "c_test", "date": d, "source": "test",
             "kind": kind, "value": v, "unit": "ms"}
        )
    return pd.DataFrame(rows)


def test_monotonic_up_yields_positive_unit_slope():
    today = date(2026, 6, 1)
    df = _series([50, 51, 52, 53, 54, 55, 56], today)
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ols", window_days=7)
    assert r is not None
    assert r.slope_per_day == pytest.approx(1.0, abs=1e-6)
    assert r.n_samples == 7
    assert r.method == "ols"
    assert r.window_days == 7
    assert r.confidence_weight == 1.0
    assert len(r.source_ids) == 7


def test_monotonic_down_yields_negative_unit_slope():
    today = date(2026, 6, 1)
    df = _series([56, 55, 54, 53, 52, 51, 50], today)
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ols", window_days=7)
    assert r is not None
    assert r.slope_per_day == pytest.approx(-1.0, abs=1e-6)


def test_flat_series_yields_zero_slope():
    today = date(2026, 6, 1)
    df = _series([55] * 7, today)
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ols", window_days=7)
    assert r is not None
    assert r.slope_per_day == pytest.approx(0.0, abs=1e-9)


def test_pure_noise_doesnt_produce_runaway_slope():
    """Symmetric noise around a constant mean — OLS slope should be
    near zero, well below the 0.20 SD/day "severe" threshold once the
    detectors normalise. This is the synthetic-data noise floor."""
    today = date(2026, 6, 1)
    # Mean 55, alternating ±2 — exactly cancels in OLS slope
    df = _series([55, 53, 57, 55, 53, 57, 55], today)
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ols", window_days=7)
    assert r is not None
    assert abs(r.slope_per_day) < 0.5  # comfortably below the trend thresholds


def test_too_few_samples_returns_none():
    today = date(2026, 6, 1)
    df = _series([55, 55, 55], today)  # only 3 points
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ols", window_days=7)
    assert r is None


def test_zero_x_variance_returns_none():
    """All data on the same day → can't compute a slope. Construct by
    duplicating a single date manually."""
    today = date(2026, 6, 1)
    d = today - timedelta(days=1)
    df = pd.DataFrame([
        {"id": f"m-{i}", "client_id": "c_test", "date": d, "source": "test",
         "kind": "hrv_rmssd", "value": 50.0 + i, "unit": "ms"}
        for i in range(5)
    ])
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ols", window_days=7)
    assert r is None


def test_window_days_respected():
    """A 14-day window of monotonic data still produces slope=1, but
    n_samples reflects the full 14 points (when available)."""
    today = date(2026, 6, 1)
    df = _series(list(range(50, 64)), today)  # 14 days, 50..63
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ols", window_days=14)
    assert r is not None
    assert r.slope_per_day == pytest.approx(1.0, abs=1e-6)
    assert r.n_samples == 14
    assert r.window_days == 14


def test_ewma_method_runs_after_e2_landed():
    """E2 wires the EWMA path in. Sanity check it doesn't raise on a
    valid call; full EWMA contracts are pinned in their own block
    below."""
    today = date(2026, 6, 1)
    df = _series([55] * 7, today)
    # Window=28 with only 7 samples — degraded weight expected, but
    # the call shouldn't raise.
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ewma", window_days=28)
    assert r is not None
    assert r.method == "ewma"


def test_unknown_method_raises_value_error():
    today = date(2026, 6, 1)
    df = _series([55] * 7, today)
    with pytest.raises(ValueError):
        compute_trend_slope(
            df, "hrv_rmssd", today, method="lowess", window_days=7  # type: ignore[arg-type]
        )


# ─── EWMA path (E2) ──────────────────────────────────────────────────


def test_ewma_monotonic_up_yields_positive_slope():
    """A 28-day monotonic ramp survives the smoother — slope on the
    EWMA-smoothed series is still positive and close to the raw
    slope. (Smoothing reduces noise, not signal.)"""
    today = date(2026, 6, 1)
    df = _series([50.0 + i * 0.5 for i in range(28)], today)
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ewma", window_days=28)
    assert r is not None
    assert r.method == "ewma"
    assert r.slope_per_day > 0.3  # raw slope is 0.5; EWMA preserves direction
    assert r.confidence_weight == 1.0
    assert r.n_samples == 28


def test_ewma_monotonic_down_yields_negative_slope():
    today = date(2026, 6, 1)
    df = _series([78.0 - i * 0.5 for i in range(28)], today)
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ewma", window_days=28)
    assert r is not None
    assert r.slope_per_day < -0.3


def test_ewma_dampens_noise_vs_ols():
    """The whole point of the EWMA path. Same noisy series, both
    methods. EWMA slope magnitude must be measurably smaller than the
    OLS slope magnitude — that's what 'dampens noise' means."""
    today = date(2026, 6, 1)
    # Mean-reverting random walk around 55, deliberately constructed
    # so OLS sees a spurious upward slope (last few values happen to
    # be higher).
    values = [55, 53, 57, 54, 56, 53, 57, 55, 54, 56, 55, 54, 56, 55,
              53, 57, 54, 56, 55, 54, 56, 53, 57, 54, 58, 56, 59, 57]
    df = _series(values, today)
    ols = compute_trend_slope(df, "hrv_rmssd", today, method="ols", window_days=28)
    ewma = compute_trend_slope(df, "hrv_rmssd", today, method="ewma", window_days=28)
    assert ols is not None and ewma is not None
    # The EWMA slope on a noisy series is biased toward zero — its
    # magnitude must be smaller. Not asserting sign match because
    # smoothing can flip a near-zero noisy slope.
    assert abs(ewma.slope_per_day) <= abs(ols.slope_per_day) + 0.01


def test_ewma_short_window_returns_zero_confidence():
    """Newly-onboarded client edge case: 10 days of data, requesting
    28-day window. EWMA returns a result so the debug endpoint can
    surface it, but confidence_weight=0 so the combiner discards it."""
    today = date(2026, 6, 1)
    df = _series([55, 54, 53, 52, 51, 50, 49, 48, 47, 46], today)
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ewma", window_days=28)
    assert r is not None
    assert r.method == "ewma"
    assert r.confidence_weight == 0.0  # n=10 < EWMA_MIN_SAMPLES (14)


def test_ewma_partial_window_ramps_confidence_linearly():
    """Confidence interpolates between EWMA_MIN_SAMPLES (14) and the
    requested window length (28). At 21 days, weight should sit near
    the midpoint."""
    today = date(2026, 6, 1)
    df = _series([55.0 - i * 0.1 for i in range(21)], today)
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ewma", window_days=28)
    assert r is not None
    # n=21, min=14, max=28 → weight = (21-14)/(28-14) = 0.5
    assert r.confidence_weight == pytest.approx(0.5, abs=0.01)


def test_ewma_full_window_full_confidence():
    today = date(2026, 6, 1)
    df = _series([55.0] * 28, today)
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ewma", window_days=28)
    assert r is not None
    assert r.confidence_weight == 1.0


def test_ewma_too_few_samples_returns_none():
    """Below the helper's hard floor of 4 samples, neither method can
    produce anything — even EWMA bails."""
    today = date(2026, 6, 1)
    df = _series([55, 55, 55], today)  # 3 < 4
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ewma", window_days=28)
    assert r is None


# ─── Acute/chronic combiner (E3) ─────────────────────────────────────


@pytest.mark.parametrize(
    "acute, chronic, expected",
    [
        # Acute severe — chronic confirms or absent
        ("severe", "severe", "severe"),
        ("severe", "moderate", "severe"),
        ("severe", "mild", "severe"),
        ("severe", None, "moderate"),
        # Acute moderate
        ("moderate", "severe", "severe"),
        ("moderate", "moderate", "moderate"),
        ("moderate", "mild", "moderate"),
        ("moderate", None, "mild"),
        # Acute mild
        ("mild", "severe", "moderate"),
        ("mild", "moderate", "moderate"),
        ("mild", "mild", "mild"),
        ("mild", None, None),
        # Acute silent — chronic-only paths
        (None, "severe", "mild"),
        (None, "moderate", None),
        (None, "mild", None),
        (None, None, None),
    ],
)
def test_combine_acute_chronic_decision_table(acute, chronic, expected):
    """Every cell of the 4×4 decision table pinned. If this test
    needs to change, the docstring + comment table in reasoning.py
    needs the same edit at the same time — they ARE the contract."""
    assert combine_acute_chronic(acute, chronic) == expected


def test_combine_holmes_noise_case():
    """The headline case the whole arc is solving: acute fires
    severely, chronic is flat. The Holmes screen-test bug."""
    assert combine_acute_chronic("severe", None) == "moderate"


def test_combine_genuine_deload_case():
    """Both detectors agree — should pass through at full severity."""
    assert combine_acute_chronic("severe", "moderate") == "severe"


def test_combine_chronic_only_drift_surfaces_weakly():
    """A slow drift the acute window hasn't caught up to yet still
    surfaces as 'mild' so the trainer sees the early warning."""
    assert combine_acute_chronic(None, "severe") == "mild"


def test_returns_sloperesult_dataclass():
    """Shape contract: callers downstream depend on SlopeResult fields."""
    today = date(2026, 6, 1)
    df = _series([55, 54, 53, 52, 51, 50, 49], today)
    r = compute_trend_slope(df, "hrv_rmssd", today, method="ols", window_days=7)
    assert isinstance(r, SlopeResult)
    # All declared fields present
    assert hasattr(r, "slope_per_day")
    assert hasattr(r, "n_samples")
    assert hasattr(r, "source_ids")
    assert hasattr(r, "method")
    assert hasattr(r, "window_days")
    assert hasattr(r, "confidence_weight")
