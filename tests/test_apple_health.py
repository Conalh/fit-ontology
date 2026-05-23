"""Apple Health Export ingestion.

Tests the XML parser end-to-end including:
  - The handful of record types we map (HRV SDNN, RHR, body mass).
  - Daily aggregation when the Watch writes multiple samples per day.
  - Reasoning falls back to SDNN when no RMSSD is present (the
    Apple-Health-only client case).
  - Zip-wrapped export.xml files are unwrapped.
"""
from __future__ import annotations

import sys
import zipfile
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fit_ontology.ingest import from_apple_health_export
from fit_ontology.ontology import MetricKind, MetricSource
from fit_ontology.reasoning import detect_hrv_signal


def _sample_xml(records: list[dict]) -> str:
    rows = "".join(
        f'<Record type="{r["type"]}" value="{r["value"]}" '
        f'startDate="{r["start"]}" endDate="{r["end"]}" unit="{r.get("unit", "")}" />'
        for r in records
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [<!ELEMENT HealthData (Record*)>]>
<HealthData locale="en_US">{rows}</HealthData>"""


def test_apple_health_parses_canonical_record_types(tmp_path: Path) -> None:
    xml = _sample_xml([
        # Two HRV samples on the same day → mean = 50.0
        {"type": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
         "value": "45.0", "start": "2026-05-18 06:00:00 -0700", "end": "2026-05-18 06:00:01 -0700"},
        {"type": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
         "value": "55.0", "start": "2026-05-18 23:00:00 -0700", "end": "2026-05-18 23:00:01 -0700"},
        # Different day
        {"type": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
         "value": "60.0", "start": "2026-05-19 06:00:00 -0700", "end": "2026-05-19 06:00:01 -0700"},
        # RHR
        {"type": "HKQuantityTypeIdentifierRestingHeartRate",
         "value": "58.0", "start": "2026-05-18 07:00:00 -0700", "end": "2026-05-18 07:00:01 -0700"},
        # Body mass
        {"type": "HKQuantityTypeIdentifierBodyMass",
         "value": "72.4", "start": "2026-05-18 07:30:00 -0700", "end": "2026-05-18 07:30:01 -0700"},
        # An ignored type — should not appear in output
        {"type": "HKQuantityTypeIdentifierStepCount",
         "value": "10000", "start": "2026-05-18 23:59:00 -0700", "end": "2026-05-18 23:59:01 -0700"},
    ])
    xml_path = tmp_path / "export.xml"
    xml_path.write_text(xml, encoding="utf-8")

    df = from_apple_health_export(xml_path, "c_iphone_user")

    assert (df["source"] == MetricSource.APPLE_HEALTH.value).all()
    assert (df["client_id"] == "c_iphone_user").all()
    assert "id" in df.columns and df["id"].is_unique

    hrv = df[df["kind"] == MetricKind.HRV_SDNN.value].sort_values("date").reset_index(drop=True)
    assert len(hrv) == 2
    assert hrv.loc[0, "date"] == date(2026, 5, 18)
    assert hrv.loc[0, "value"] == 50.0  # daily mean of 45 and 55
    assert hrv.loc[1, "value"] == 60.0

    rhr = df[df["kind"] == MetricKind.RESTING_HR.value]
    assert len(rhr) == 1 and rhr.iloc[0]["value"] == 58.0

    mass = df[df["kind"] == MetricKind.BODY_WEIGHT_KG.value]
    assert len(mass) == 1 and mass.iloc[0]["value"] == 72.4

    # Step count was filtered out.
    assert (df["kind"] != "step_count").all()


def test_apple_health_unwraps_zip(tmp_path: Path) -> None:
    xml = _sample_xml([
        {"type": "HKQuantityTypeIdentifierRestingHeartRate",
         "value": "55.0", "start": "2026-05-18 07:00:00 -0700", "end": "2026-05-18 07:00:01 -0700"},
    ])
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("apple_health_export/export.xml", xml)

    df = from_apple_health_export(zip_path, "c_iphone_user")
    assert len(df) == 1
    assert df.iloc[0]["value"] == 55.0


def test_hrv_detector_falls_back_to_sdnn() -> None:
    """A client with only Apple Health (SDNN) should still get an HRV
    signal if their values drop below baseline."""
    import pandas as pd

    today = date(2026, 5, 23)
    rows = []
    # 28 days of stable baseline ~ 50 ms
    for offset in range(28, 7, -1):
        d = today - timedelta(days=offset)
        rows.append({
            "id": f"m_b{offset}", "client_id": "c", "date": d,
            "source": "apple_health", "kind": MetricKind.HRV_SDNN.value,
            "value": 50.0 + (offset % 3) - 1, "unit": "ms",
        })
    # 7 days of acute drop ~ 40 ms
    for offset in range(7, 0, -1):
        d = today - timedelta(days=offset)
        rows.append({
            "id": f"m_a{offset}", "client_id": "c", "date": d,
            "source": "apple_health", "kind": MetricKind.HRV_SDNN.value,
            "value": 40.0, "unit": "ms",
        })
    metrics = pd.DataFrame(rows)

    signal = detect_hrv_signal(metrics, today)
    assert signal is not None
    assert signal.kind == "hrv_below_baseline"
