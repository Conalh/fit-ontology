"""Tests for the planning layer.

The planner is rules-based, so the contract is: given a verdict + a
plausible session history + a list of contraindications, the emitted
plan should have the expected shape (count, types, targets).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from fit_ontology.db import DEFAULT_TRAINER_ID
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


# --- Plan-vs-execution matcher ---------------------------------------------

def _seed_db(tmp_path):
    """Seed a tmp DuckDB with a client, a generated plan, and some
    sessions for matcher tests to chew on."""
    from fit_ontology.db import connect, ensure_client, insert_plan, insert_sessions
    db_path = tmp_path / "test.duckdb"
    today = date.today()
    week_of = today - timedelta(days=today.weekday())

    con = connect(db_path)
    ensure_client(con, DEFAULT_TRAINER_ID, "c1", name="Test")

    # Plan with 3 slots — strength, cardio, mobility
    sessions_for_load = _sessions_df(today, per_week=3)
    plan = generate_plan("c1", week_of, "STANDARD", sessions_for_load, today=today)
    insert_plan(con, DEFAULT_TRAINER_ID, plan)

    # Logged sessions — one strength this week, one cardio this week
    sessions_rows = pd.DataFrame([
        {"id": "s_strength", "client_id": "c1", "date": week_of + timedelta(days=1),
         "type": "strength", "duration_min": 60, "rpe": 7, "notes": ""},
        {"id": "s_cardio", "client_id": "c1", "date": week_of + timedelta(days=3),
         "type": "cardio", "duration_min": 40, "rpe": 6, "notes": ""},
    ])
    insert_sessions(con, DEFAULT_TRAINER_ID, sessions_rows)
    con.close()
    return db_path, week_of


def test_matcher_links_same_type_session_to_same_type_slot(tmp_path):
    """A logged strength session should bind to the strength slot of the
    week, not the mobility or cardio slot."""
    from fit_ontology.db import connect, match_planned_sessions, plan_for_week
    db_path, week_of = _seed_db(tmp_path)

    with connect(db_path, read_only=False) as con:
        linked = match_planned_sessions(con, DEFAULT_TRAINER_ID, "c1")
    assert linked == 2  # both seeded sessions match a slot

    with connect(db_path, read_only=True) as con:
        plan = plan_for_week(con, DEFAULT_TRAINER_ID, "c1", week_of)

    strength_slot = next(p for p in plan if p.type.value == "strength")
    cardio_slot = next(p for p in plan if p.type.value == "cardio")
    assert strength_slot.executed_session_id == "s_strength"
    assert cardio_slot.executed_session_id == "s_cardio"


def test_matcher_is_idempotent(tmp_path):
    """Running the matcher twice doesn't relink or break anything —
    already-matched sessions are skipped on the second pass."""
    from fit_ontology.db import connect, match_planned_sessions
    db_path, _ = _seed_db(tmp_path)
    with connect(db_path, read_only=False) as con:
        first = match_planned_sessions(con, DEFAULT_TRAINER_ID, "c1")
        second = match_planned_sessions(con, DEFAULT_TRAINER_ID, "c1")
    assert first == 2
    assert second == 0  # nothing new to link the second time


def test_matcher_falls_back_to_any_unmatched_slot(tmp_path):
    """If no same-type slot exists, the matcher should still bind the
    session to the lowest unmatched slot rather than dropping it on the
    floor."""
    from fit_ontology.db import connect, ensure_client, insert_plan, insert_sessions, match_planned_sessions, plan_for_week
    db_path = tmp_path / "fallback.duckdb"
    today = date.today()
    week_of = today - timedelta(days=today.weekday())

    con = connect(db_path)
    ensure_client(con, DEFAULT_TRAINER_ID, "c1", name="Test")
    sessions_seed = _sessions_df(today, per_week=2)
    plan = generate_plan("c1", week_of, "STANDARD", sessions_seed, today=today)
    insert_plan(con, DEFAULT_TRAINER_ID, plan)

    # Log a "mixed" session — no matching slot type in the standard plan
    insert_sessions(con, DEFAULT_TRAINER_ID, pd.DataFrame([
        {"id": "s_mixed", "client_id": "c1", "date": week_of + timedelta(days=2),
         "type": "mixed", "duration_min": 45, "rpe": 6, "notes": ""},
    ]))

    linked = match_planned_sessions(con, DEFAULT_TRAINER_ID, "c1")
    assert linked == 1

    plan_after = plan_for_week(con, DEFAULT_TRAINER_ID, "c1", week_of)
    bound = [p for p in plan_after if p.executed_session_id == "s_mixed"]
    assert len(bound) == 1
    # Should have bound to slot 1 (lowest available)
    assert bound[0].slot == 1
    con.close()


def test_matcher_ignores_sessions_outside_planned_weeks(tmp_path):
    """A session from a week with no plan should NOT silently bind to a
    plan in a different week. The matcher computes week_of from the
    session date and only looks at that week's slots."""
    from fit_ontology.db import connect, ensure_client, insert_plan, insert_sessions, match_planned_sessions
    db_path = tmp_path / "isolated.duckdb"
    today = date.today()
    this_week = today - timedelta(days=today.weekday())
    last_week = this_week - timedelta(days=7)

    con = connect(db_path)
    ensure_client(con, DEFAULT_TRAINER_ID, "c1", name="Test")
    sessions_seed = _sessions_df(today, per_week=2)
    # Plan exists ONLY for this week.
    insert_plan(con, DEFAULT_TRAINER_ID, generate_plan("c1", this_week, "STANDARD", sessions_seed, today=today))

    # Logged session for last week — no plan, shouldn't match anything.
    insert_sessions(con, DEFAULT_TRAINER_ID, pd.DataFrame([
        {"id": "s_lastweek", "client_id": "c1", "date": last_week + timedelta(days=1),
         "type": "strength", "duration_min": 60, "rpe": 7, "notes": ""},
    ]))
    linked = match_planned_sessions(con, DEFAULT_TRAINER_ID, "c1")
    assert linked == 0
    con.close()
