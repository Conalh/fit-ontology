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

from fit_ontology.reasoning import SlopeResult, compute_trend_slope


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


def test_ewma_method_raises_not_implemented():
    """E1 lands the seam, not the method. EWMA callers should fail
    loudly until E2 wires it in — a silent fallback to OLS would
    produce identical-looking but quietly-wrong verdicts."""
    today = date(2026, 6, 1)
    df = _series([55] * 7, today)
    with pytest.raises(NotImplementedError):
        compute_trend_slope(df, "hrv_rmssd", today, method="ewma", window_days=28)


def test_unknown_method_raises_value_error():
    today = date(2026, 6, 1)
    df = _series([55] * 7, today)
    with pytest.raises(ValueError):
        compute_trend_slope(
            df, "hrv_rmssd", today, method="lowess", window_days=7  # type: ignore[arg-type]
        )


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
