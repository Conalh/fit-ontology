"""Tests for the planning layer.

The planner is rules-based, so the contract is: given a verdict + a
plausible session history + a list of contraindications, the emitted
plan should have the expected shape (count, types, targets).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from fit_ontology.ontology import PlanSource, SessionType
from fit_ontology.planning import (
    _plan_id,
    _recent_weekly_load,
    generate_plan,
    parse_contraindications,
    serialize_contraindications,
)


def _sessions_df(today: date, *, per_week: int, weeks: int = 4,
                 duration_min: int = 60, rpe: int = 7) -> pd.DataFrame:
    """Build a session history with ``per_week`` sessions over ``weeks``
    weeks. Used to anchor _recent_weekly_load for plan tests."""
    rows = []
    for w in range(weeks):
        for i in range(per_week):
            # Spread sessions across the week — Mon/Wed/Fri pattern up to 5
            offsets = [1, 3, 5, 6, 0][:per_week]
            d = today - timedelta(days=w * 7 + offsets[i])
            rows.append({
                "id": f"s-{w}-{i}",
                "client_id": "c1",
                "date": d,
                "type": "strength",
                "duration_min": duration_min,
                "rpe": rpe,
                "notes": "",
            })
    return pd.DataFrame(rows)


def test_plan_id_is_deterministic():
    """Same (client, week, slot) input always yields the same id so
    persistence treats regeneration as INSERT OR REPLACE rather than
    accidental row duplication."""
    a = _plan_id("c1", date(2026, 5, 18), 1)
    b = _plan_id("c1", date(2026, 5, 18), 1)
    c = _plan_id("c1", date(2026, 5, 18), 2)
    assert a == b
    assert a != c
    assert a.startswith("p_")


def test_deload_plan_emits_three_sessions_with_light_targets():
    """Deload week should hold 3 slots: mobility/technique, Z2 aerobic,
    light strength. Target loads should be a clear fraction of recent
    weekly load."""
    today = date(2026, 5, 18)
    sessions = _sessions_df(today, per_week=4)
    weekly = _recent_weekly_load(sessions, today)
    plan = generate_plan(
        client_id="c1",
        week_of=today,
        verdict="DELOAD",
        sessions=sessions,
        contraindications=(),
        today=today,
    )
    assert len(plan) == 3
    assert plan[0].type == SessionType.MOBILITY
    assert plan[1].type == SessionType.CARDIO
    assert plan[2].type == SessionType.STRENGTH
    # All slots should carry low RPE (cap at 6) and target loads well
    # below 100% of recent weekly average.
    for ps in plan:
        assert ps.target_rpe is not None and ps.target_rpe <= 6
        assert ps.target_load_au is not None
        assert ps.target_load_au < weekly  # each slot < weekly total
    # Strength slot is 25% — sanity check the load math.
    assert abs(plan[2].target_load_au - weekly * 0.25) < 1


def test_conservative_plan_emits_four_sessions():
    today = date(2026, 5, 18)
    sessions = _sessions_df(today, per_week=4)
    plan = generate_plan("c1", today, "CONSERVATIVE", sessions, today=today)
    assert len(plan) == 4
    # Should include at least one strength slot.
    assert any(p.type == SessionType.STRENGTH for p in plan)


def test_standard_plan_emits_four_sessions_with_higher_load_targets():
    today = date(2026, 5, 18)
    sessions = _sessions_df(today, per_week=4)
    deload = generate_plan("c1", today, "DELOAD", sessions, today=today)
    standard = generate_plan("c1", today, "STANDARD", sessions, today=today)
    # Standard week's strength sessions should target higher loads than
    # deload's strength slot.
    standard_strength = [p for p in standard if p.type == SessionType.STRENGTH]
    deload_strength = [p for p in deload if p.type == SessionType.STRENGTH][0]
    assert standard_strength
    assert standard_strength[0].target_load_au > deload_strength.target_load_au


def test_contraindications_attach_to_strength_and_mobility_only():
    """Generic warnings like "avoid deep bilateral squats" matter for
    movement-pattern slots (strength + mobility) but not for cardio."""
    today = date(2026, 5, 18)
    sessions = _sessions_df(today, per_week=3)
    plan = generate_plan(
        "c1", today, "STANDARD", sessions,
        contraindications=("avoid deep bilateral squats",),
        today=today,
    )
    for ps in plan:
        if ps.type in (SessionType.STRENGTH, SessionType.MOBILITY):
            assert "avoid deep bilateral squats" in ps.contraindications
        else:
            assert ps.contraindications == []


def test_empty_session_history_yields_null_targets():
    """A brand-new client with no session history shouldn't get a
    fabricated load target — the column stays null so the UI can show
    "—" until enough sessions accumulate."""
    today = date(2026, 5, 18)
    empty = pd.DataFrame(columns=["id", "client_id", "date", "type", "duration_min", "rpe", "notes"])
    plan = generate_plan("c_new", today, "STANDARD", empty, today=today)
    assert plan  # still emits slots (the template count)
    for ps in plan:
        assert ps.target_load_au is None  # no anchor to compute against


def test_engine_source_set_on_every_generated_slot():
    """Every slot from the generator is engine-sourced. Trainer edits
    flip it to PlanSource.TRAINER via the API; that's tested separately
    once the API lands."""
    today = date(2026, 5, 18)
    sessions = _sessions_df(today, per_week=4)
    for verdict in ("DELOAD", "CONSERVATIVE", "STANDARD"):
        plan = generate_plan("c1", today, verdict, sessions, today=today)
        for ps in plan:
            assert ps.source == PlanSource.ENGINE


def test_contraindications_roundtrip_through_json():
    items = ["avoid deep bilateral squats", "cap plyometrics"]
    raw = serialize_contraindications(items)
    parsed = parse_contraindications(raw)
    assert parsed == items
    # Empty/null defensive paths
    assert parse_contraindications(None) == []
    assert parse_contraindications("") == []
    assert parse_contraindications("not json") == []
