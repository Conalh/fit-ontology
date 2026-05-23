"""API surface tests — FastAPI's TestClient with a seeded temp DB.

Verifies every route the front-end will hit returns the shape we
promised. Doesn't go through the real network stack; runs the ASGI
app in-process.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import fit_ontology.api as api_mod
from fit_ontology.db import connect, ensure_client, insert_metrics, insert_sessions
from fit_ontology.ontology import MetricKind


@pytest.fixture()
def app_with_db(tmp_path: Path, monkeypatch):
    """Point the API at a temp DuckDB and seed it with one client +
    some recent metrics + sessions. Patches DEFAULT_DB_PATH used by the
    write endpoints, and shadows the read-only dependency so reads come
    from the same temp DB."""
    db_path = tmp_path / "fit_ontology.duckdb"

    con = connect(db_path)
    ensure_client(con, "c_test", name="Test Client")

    today = date.today()
    metric_rows = []
    for offset in range(28, 0, -1):
        d = today - timedelta(days=offset)
        metric_rows.append({
            "id": f"m-hrv-{offset}", "client_id": "c_test", "date": d,
            "source": "garmin", "kind": MetricKind.HRV_RMSSD.value,
            "value": 55.0, "unit": "ms",
        })
        metric_rows.append({
            "id": f"m-sleep-{offset}", "client_id": "c_test", "date": d,
            "source": "garmin", "kind": MetricKind.SLEEP_HOURS.value,
            "value": 7.5, "unit": "h",
        })
    insert_metrics(con, pd.DataFrame(metric_rows))

    session_rows = []
    for i, offset in enumerate([2, 4, 6, 9, 11, 13]):
        session_rows.append({
            "id": f"s-{i}", "client_id": "c_test",
            "date": today - timedelta(days=offset),
            "type": "strength", "duration_min": 60, "rpe": 6, "notes": "",
        })
    insert_sessions(con, pd.DataFrame(session_rows))
    con.close()

    monkeypatch.setattr(api_mod, "DEFAULT_DB_PATH", db_path)

    def _ro():
        c = connect(db_path, read_only=True)
        try:
            yield c
        finally:
            c.close()

    api_mod.app.dependency_overrides[api_mod._read_only_conn] = _ro
    try:
        yield TestClient(api_mod.app)
    finally:
        api_mod.app.dependency_overrides.pop(api_mod._read_only_conn, None)


def test_health(app_with_db):
    r = app_with_db.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_get_clients_returns_seeded_client(app_with_db):
    r = app_with_db.get("/api/clients")
    assert r.status_code == 200
    rows = r.json()
    assert any(c["id"] == "c_test" for c in rows)


def test_get_client_404_for_unknown(app_with_db):
    assert app_with_db.get("/api/clients/c_missing").status_code == 404


def test_get_metrics_returns_seeded_rows(app_with_db):
    r = app_with_db.get("/api/clients/c_test/metrics?days=14")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) > 0
    kinds = {row["kind"] for row in rows}
    assert {"hrv_rmssd", "sleep_hours"} <= kinds


def test_get_recommendation_returns_structured_payload(app_with_db):
    r = app_with_db.get("/api/clients/c_test/recommendation")
    assert r.status_code == 200
    data = r.json()
    assert "recommendation" in data and "rationale" in data
    assert 0 <= data["confidence"] <= 1
    assert isinstance(data["source_metric_ids"], list)
    assert "contraindications" in data


def test_recommendation_surfaces_contraindications_from_injury(app_with_db):
    """Editing the client's injury_history should make matching
    contraindications appear in the next recommendation response."""
    app_with_db.patch(
        "/api/clients/c_test",
        json={"injury_history": "ACL reconstruction 2022; lumbar stiffness on heavy days"},
    )
    r = app_with_db.get("/api/clients/c_test/recommendation")
    data = r.json()
    kinds = {c["kind"] for c in data["contraindications"]}
    assert "acl" in kinds
    assert "knee" in kinds
    assert "lumbar" in kinds


def test_get_roster_includes_seeded_client(app_with_db):
    r = app_with_db.get("/api/roster")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    me = next(r for r in rows if r["client_id"] == "c_test")
    assert me["label"] in {"Standard", "Conservative", "Deload", "No recent data"}


def test_override_roundtrip(app_with_db):
    payload = {
        "week_of": str(date.today()),
        "system_recommendation": "Standard progression per ACSM 11e: increase load 5-10%.",
        "system_confidence": 0.78,
        "trainer_action": "accept",
        "applied_load_change_pct": None,
        "trainer_note": "looks fine",
    }
    post = app_with_db.post("/api/clients/c_test/overrides", json=payload)
    assert post.status_code == 200, post.text
    ov = post.json()
    assert ov["trainer_action"] == "accept"

    get = app_with_db.get("/api/clients/c_test/overrides")
    assert get.status_code == 200
    rows = get.json()
    assert any(r["id"] == ov["id"] for r in rows)


def test_calibration_with_one_override(app_with_db):
    # Seed an override first.
    payload = {
        "week_of": str(date.today()),
        "system_recommendation": "Deload week: reduce training load by 20%.",
        "system_confidence": 0.85,
        "trainer_action": "reject",
        "applied_load_change_pct": None,
        "trainer_note": "client felt great, kept training",
    }
    app_with_db.post("/api/clients/c_test/overrides", json=payload)

    r = app_with_db.get("/api/calibration")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert data["rejects"] >= 1
    assert "Deload" in data["matrix"]


def test_pdf_endpoint_returns_pdf_bytes(app_with_db):
    r = app_with_db.post(
        "/api/clients/c_test/pdf",
        json={"coach_message": "Great work this week."},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert "attachment" in r.headers.get("content-disposition", "")


def test_post_client_creates_row(app_with_db):
    payload = {
        "name": "New Client",
        "sex": "F",
        "age": 31,
        "height_cm": 168.0,
        "weight_kg": 62.0,
        "goal": "Half marathon Q3",
        "injury_history": None,
    }
    r = app_with_db.post("/api/clients", json=payload)
    assert r.status_code == 200, r.text
    new_id = r.json()["id"]
    assert new_id.startswith("c_")

    # Confirm it actually landed in the roster.
    listed = app_with_db.get("/api/clients").json()
    assert any(c["id"] == new_id for c in listed)

    detail = app_with_db.get(f"/api/clients/{new_id}").json()
    assert detail["name"] == "New Client"
    assert detail["sex"] == "F"
    assert detail["goal"] == "Half marathon Q3"


def test_post_client_validates_ranges(app_with_db):
    bad = {
        "name": "Bad", "sex": "F", "age": 5,  # below range
        "height_cm": 165.0, "weight_kg": 60.0, "goal": "x",
    }
    assert app_with_db.post("/api/clients", json=bad).status_code == 422


def test_patch_client_partial_update(app_with_db):
    # The fixture seeds c_test as "Test Client". Rename + change goal,
    # leave the other fields untouched and confirm they survive.
    r = app_with_db.patch(
        "/api/clients/c_test", json={"name": "Renamed Client", "goal": "Strength + GPP"}
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["updated"]) == {"name", "goal"}

    detail = app_with_db.get("/api/clients/c_test").json()
    assert detail["name"] == "Renamed Client"
    assert detail["goal"] == "Strength + GPP"
    # Age, height, weight from the fixture's ensure_client call must
    # still be there.
    assert detail["age"] == 30


def test_patch_client_404_for_unknown(app_with_db):
    r = app_with_db.patch("/api/clients/c_missing", json={"name": "Nope"})
    assert r.status_code == 404


def test_patch_client_noop_returns_ok(app_with_db):
    r = app_with_db.patch("/api/clients/c_test", json={})
    assert r.status_code == 200
    assert r.json()["updated"] == []


def test_thresholds_get_returns_defaults_and_overrides(app_with_db):
    r = app_with_db.get("/api/clients/c_test/thresholds")
    assert r.status_code == 200
    data = r.json()
    assert "defaults" in data and "overrides" in data
    assert data["defaults"]["hrv_mild_sd"] == 0.5
    assert data["overrides"] == {}


def test_thresholds_patch_upsert_and_revert(app_with_db):
    # Upsert two overrides.
    r = app_with_db.patch(
        "/api/clients/c_test/thresholds",
        json={"overrides": {"hrv_mild_sd": 0.7, "sleep_floor_hours": 6.5}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["overrides"] == {"hrv_mild_sd": 0.7, "sleep_floor_hours": 6.5}

    # Update one + revert the other to default in the same call.
    r = app_with_db.patch(
        "/api/clients/c_test/thresholds",
        json={"overrides": {"hrv_mild_sd": 0.6, "sleep_floor_hours": None}},
    )
    assert r.json()["overrides"] == {"hrv_mild_sd": 0.6}


def test_thresholds_patch_rejects_unknown_keys(app_with_db):
    r = app_with_db.patch(
        "/api/clients/c_test/thresholds",
        json={"overrides": {"bogus_threshold": 1.0}},
    )
    assert r.status_code == 400
    assert "Unknown threshold" in r.json()["detail"]


def test_upload_apple_health_xml(app_with_db, tmp_path: Path):
    xml = """<?xml version="1.0"?>
<HealthData>
<Record type="HKQuantityTypeIdentifierRestingHeartRate" value="55" startDate="2026-05-22 07:00:00 -0700" endDate="2026-05-22 07:00:01 -0700" unit="count/min"/>
</HealthData>"""
    files = {"file": ("export.xml", xml.encode(), "application/xml")}
    r = app_with_db.post("/api/clients/c_test/upload", files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["inserted"] == 1
    assert "resting_hr" in data["kinds"]
