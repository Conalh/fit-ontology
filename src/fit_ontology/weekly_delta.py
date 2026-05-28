"""Current-week plan-vs-reality summary."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .db import plan_for_week_with_matches
from .weekly_state import ClientNotFoundError, week_start


@dataclass(frozen=True)
class WeeklyDelta:
    week_of: date
    status: str
    headline: str
    bullets: list[str]
    planned_sessions: int
    completed_sessions: int
    completion_rate: float | None
    target_load_au: int
    completed_target_load_au: int
    actual_load_au: int
    matched_load_delta_pct: float | None
    current_week_load_au: int
    previous_week_load_au: int
    week_load_change_pct: float | None


def _round_pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 1)


def _pct_phrase(value: float) -> str:
    direction = "above" if value >= 0 else "below"
    return f"{abs(value):.0f}% {direction}"


def _week_load(con, trainer_id: str, client_id: str, start: date) -> int:
    end = start + timedelta(days=7)
    row = con.execute(
        """
        SELECT COALESCE(SUM(duration_min * rpe), 0)
        FROM sessions
        WHERE trainer_id = ?
          AND client_id = ?
          AND date >= ?
          AND date < ?
        """,
        [trainer_id, client_id, start, end],
    ).fetchone()
    return int(row[0] or 0)


def _actual_load_for_sessions(con, trainer_id: str, client_id: str, session_ids: list[str]) -> int:
    if not session_ids:
        return 0
    placeholders = ", ".join("?" for _ in session_ids)
    row = con.execute(
        f"""
        SELECT COALESCE(SUM(duration_min * rpe), 0)
        FROM sessions
        WHERE trainer_id = ?
          AND client_id = ?
          AND id IN ({placeholders})
        """,
        [trainer_id, client_id, *session_ids],
    ).fetchone()
    return int(row[0] or 0)


def _status(
    *,
    planned_sessions: int,
    completion_rate: float | None,
    matched_load_delta_pct: float | None,
    week_load_change_pct: float | None,
    weekday: int,
) -> str:
    if planned_sessions == 0:
        return "no_plan"
    if matched_load_delta_pct is not None and abs(matched_load_delta_pct) >= 25:
        return "off_track"
    if week_load_change_pct is not None and week_load_change_pct >= 50:
        return "off_track"
    if matched_load_delta_pct is not None and abs(matched_load_delta_pct) >= 10:
        return "watch"
    if weekday >= 4 and completion_rate is not None and completion_rate < 0.5:
        return "watch"
    return "on_track"


def _headline(status: str) -> str:
    if status == "no_plan":
        return "No plan to compare yet."
    if status == "off_track":
        return "Plan and reality are drifting."
    if status == "watch":
        return "Worth a quick check-in."
    return "Plan is tracking."


def build_weekly_delta(
    con,
    trainer_id: str,
    client_id: str,
    *,
    today: date | None = None,
) -> WeeklyDelta:
    today = today or date.today()
    week_of = week_start(today)

    row = con.execute(
        "SELECT 1 FROM clients WHERE id = ? AND trainer_id = ?",
        [client_id, trainer_id],
    ).fetchone()
    if row is None:
        raise ClientNotFoundError(client_id)

    plan = plan_for_week_with_matches(con, trainer_id, client_id, week_of)
    planned_sessions = len(plan)
    completed = [p for p in plan if p.executed_session_id]
    completed_sessions = len(completed)
    completion_rate = round(completed_sessions / planned_sessions, 2) if planned_sessions else None

    target_load_au = int(sum(p.target_load_au or 0 for p in plan))
    completed_target_load_au = int(sum(p.target_load_au or 0 for p in completed))
    actual_load_au = _actual_load_for_sessions(
        con,
        trainer_id,
        client_id,
        [p.executed_session_id for p in completed if p.executed_session_id],
    )
    matched_load_delta_pct = (
        _round_pct(((actual_load_au - completed_target_load_au) / completed_target_load_au) * 100)
        if completed_target_load_au > 0
        else None
    )

    current_week_load_au = _week_load(con, trainer_id, client_id, week_of)
    previous_week_load_au = _week_load(con, trainer_id, client_id, week_of - timedelta(days=7))
    week_load_change_pct = (
        _round_pct(((current_week_load_au - previous_week_load_au) / previous_week_load_au) * 100)
        if previous_week_load_au > 0
        else None
    )

    status = _status(
        planned_sessions=planned_sessions,
        completion_rate=completion_rate,
        matched_load_delta_pct=matched_load_delta_pct,
        week_load_change_pct=week_load_change_pct,
        weekday=today.weekday(),
    )

    bullets: list[str] = []
    if planned_sessions == 0:
        bullets.append("No planned sessions exist for this week.")
    else:
        pct = round((completion_rate or 0) * 100)
        bullets.append(f"{completed_sessions} of {planned_sessions} planned sessions completed ({pct}%).")
        if matched_load_delta_pct is not None:
            bullets.append(
                "Matched-session load is "
                f"{_pct_phrase(matched_load_delta_pct)} target "
                f"({actual_load_au} vs {completed_target_load_au} AU)."
            )
    if week_load_change_pct is not None:
        bullets.append(
            "Current-week load is "
            f"{_pct_phrase(week_load_change_pct)} last week "
            f"({current_week_load_au} vs {previous_week_load_au} AU)."
        )
    elif previous_week_load_au == 0 and current_week_load_au > 0:
        bullets.append(f"Current-week load is {current_week_load_au} AU; no comparable load last week.")

    return WeeklyDelta(
        week_of=week_of,
        status=status,
        headline=_headline(status),
        bullets=bullets,
        planned_sessions=planned_sessions,
        completed_sessions=completed_sessions,
        completion_rate=completion_rate,
        target_load_au=target_load_au,
        completed_target_load_au=completed_target_load_au,
        actual_load_au=actual_load_au,
        matched_load_delta_pct=matched_load_delta_pct,
        current_week_load_au=current_week_load_au,
        previous_week_load_au=previous_week_load_au,
        week_load_change_pct=week_load_change_pct,
    )
