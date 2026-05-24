"""
The planning layer.

Turns a weekly recommendation into a structured set of session slots.
Sits between reasoning.py (what should this week look like?) and the
sessions table (what actually happened?). Rules-based on purpose, same
as reasoning — every slot the engine emits should be defensible from
the verdict + the recent load history + the client's contraindications.

Templates per verdict:

  DELOAD       3 sessions: mobility/technique, Z2 aerobic, light strength.
               Target loads 60% of the recent 4-week mean weekly load.
               Aim is to clear accumulated fatigue while preserving
               movement quality. No PR attempts, no max-effort lifts.

  CONSERVATIVE 4 sessions: mobility, light strength, conditioning,
               moderate strength. Loads at 85-95% of recent mean.
               Hold volume, soften intensity. Watch how the client
               responds before pushing back to baseline.

  STANDARD     Match the client's recent session-per-week pattern (3-5
               sessions). ACSM 5-10% progression on load. Bias toward
               continuity rather than novelty.

Contraindications are not used to *generate* exercise lists (we don't
have a per-modality exercise database); they're attached to each
relevant session as a warning the trainer sees and works around. A
client with knee history sees "avoid deep bilateral squats" on every
strength slot; the trainer's content stays the trainer's call.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

import pandas as pd

from .ontology import PlannedSession, PlanSource, SessionType

Verdict = Literal["DELOAD", "CONSERVATIVE", "STANDARD"]


def _plan_id(client_id: str, week_of: date, slot: int) -> str:
    """Deterministic slot ID — same client/week/slot always hashes to
    the same id. Lets the persistence layer treat regeneration as
    INSERT OR REPLACE without churn."""
    digest = hashlib.sha1(f"{client_id}|{week_of.isoformat()}|{slot}".encode()).hexdigest()
    return f"p_{digest[:14]}"


# --- Session templates -----------------------------------------------------
#
# Each template is a (type, title, description_template, fraction_of_avg_load,
# default_rpe, default_duration). description_template is a Python format
# string with named placeholders the renderer fills in from the per-call
# context (load target, intensity guidance, contraindication warnings).

@dataclass(frozen=True)
class _Template:
    type: SessionType
    title: str
    description: str
    load_fraction: float        # of recent weekly mean load
    rpe: float
    duration_min: int


_DELOAD_WEEK: tuple[_Template, ...] = (
    _Template(
        type=SessionType.MOBILITY,
        title="Mobility + technique",
        description=(
            "Movement quality session. Hips, ankles, thoracic mobility plus light "
            "skill work — practice your top three lifts at ~40-50% with full "
            "control. No fatigue, no intensity. Should leave you feeling better, "
            "not tired."
        ),
        load_fraction=0.15,
        rpe=3,
        duration_min=40,
    ),
    _Template(
        type=SessionType.CARDIO,
        title="Z2 aerobic",
        description=(
            "Steady-state aerobic in zone 2. Conversational pace — you should be "
            "able to hold a full sentence without gasping. Bike, easy run, or row. "
            "30-45 minutes continuous."
        ),
        load_fraction=0.20,
        rpe=4,
        duration_min=40,
    ),
    _Template(
        type=SessionType.STRENGTH,
        title="Light strength",
        description=(
            "One main lift at 60% × 5 sets of 5 (no grind, leave 4 reps in the "
            "tank each set), plus two accessory movements at 3 × 10. Cap intensity "
            "even if you feel good — this week is for recovery, not testing."
        ),
        load_fraction=0.25,
        rpe=6,
        duration_min=50,
    ),
)


_CONSERVATIVE_WEEK: tuple[_Template, ...] = (
    _Template(
        type=SessionType.MOBILITY,
        title="Mobility primer",
        description=(
            "Short mobility flow plus 10-15 minutes of skill / tempo work on a "
            "single lift. Keeps movement quality without adding meaningful load."
        ),
        load_fraction=0.10,
        rpe=3,
        duration_min=30,
    ),
    _Template(
        type=SessionType.STRENGTH,
        title="Strength — light",
        description=(
            "Main lift at 70% × 4 × 5, plus two accessories at 3 × 8-10. Keep "
            "bar speed crisp — if it slows, drop a set rather than push through."
        ),
        load_fraction=0.20,
        rpe=7,
        duration_min=55,
    ),
    _Template(
        type=SessionType.CARDIO,
        title="Conditioning",
        description=(
            "Moderate-intensity intervals (Z3-Z4) or a steady tempo. Pick the "
            "modality that the client tolerates well; volume should match what "
            "they did last week within ±10%."
        ),
        load_fraction=0.25,
        rpe=7,
        duration_min=35,
    ),
    _Template(
        type=SessionType.STRENGTH,
        title="Strength — moderate",
        description=(
            "Main lift at 75-80% × 3 × 5 (or RPE 7 if working on percentages "
            "isn't natural for this client), plus 2-3 accessories at 3 × 6-10. "
            "Stop one rep before form breaks."
        ),
        load_fraction=0.30,
        rpe=8,
        duration_min=55,
    ),
)


_STANDARD_WEEK: tuple[_Template, ...] = (
    _Template(
        type=SessionType.MOBILITY,
        title="Mobility primer",
        description=(
            "Pre-week mobility flow. Optional but helps with the first heavy "
            "session of the week."
        ),
        load_fraction=0.08,
        rpe=3,
        duration_min=25,
    ),
    _Template(
        type=SessionType.STRENGTH,
        title="Strength A — main",
        description=(
            "Primary strength session. Main lift at trainer's prescribed scheme "
            "(typically 80-85% × 3-5 reps), 2-3 accessories targeting the same "
            "movement pattern. ACSM 5-10% load progression from last week if "
            "form held."
        ),
        load_fraction=0.30,
        rpe=8,
        duration_min=60,
    ),
    _Template(
        type=SessionType.CARDIO,
        title="Conditioning",
        description=(
            "Conditioning piece — pick the modality and intensity that matches "
            "the client's goal. Sprint intervals for power athletes, longer "
            "tempo for endurance work, mixed-modal for general fitness."
        ),
        load_fraction=0.25,
        rpe=7,
        duration_min=40,
    ),
    _Template(
        type=SessionType.STRENGTH,
        title="Strength B — variation",
        description=(
            "Second strength day with a complementary movement pattern (if "
            "Strength A was squat-dominant, lean hinge here, or vice versa). "
            "Slightly lower intensity, slightly more accessory volume."
        ),
        load_fraction=0.30,
        rpe=7,
        duration_min=55,
    ),
)


_TEMPLATES_BY_VERDICT: dict[Verdict, tuple[_Template, ...]] = {
    "DELOAD": _DELOAD_WEEK,
    "CONSERVATIVE": _CONSERVATIVE_WEEK,
    "STANDARD": _STANDARD_WEEK,
}


# --- Generation ------------------------------------------------------------

def _recent_weekly_load(sessions: pd.DataFrame, today: date, weeks: int = 4) -> float:
    """Mean weekly load (sum of RPE × duration) across the last ``weeks``
    weeks. Returns 0 if no sessions. The 4-week window matches the
    chronic side of the ACWR ratio in reasoning."""
    if sessions.empty:
        return 0.0
    s = sessions.copy()
    if pd.api.types.is_datetime64_any_dtype(s["date"]):
        s["date"] = s["date"].dt.date
    cutoff = today - timedelta(days=weeks * 7)
    s = s[s["date"] > cutoff]
    if s.empty:
        return 0.0
    s["load"] = s["rpe"].astype(float) * s["duration_min"].astype(float)
    total = float(s["load"].sum())
    return total / weeks


def generate_plan(
    client_id: str,
    week_of: date,
    verdict: Verdict,
    sessions: pd.DataFrame,
    contraindications: Sequence[str] = (),
    today: date | None = None,
) -> list[PlannedSession]:
    """Build the structured weekly plan for a client.

    ``contraindications`` should be the ``c.advice`` strings from
    ``match_contraindications(client.injury_history)`` — short
    sentences like "avoid deep bilateral squats" that the engine
    attaches to every relevant strength slot. Mobility/cardio slots
    only see contraindications that mention their modality.
    """
    today = today or date.today()
    templates = _TEMPLATES_BY_VERDICT[verdict]
    weekly_load = _recent_weekly_load(sessions, today)

    plan: list[PlannedSession] = []
    for slot, tmpl in enumerate(templates, start=1):
        # Per-slot load target. When weekly_load is 0 (new client, no
        # session history), we leave target_load_au null so the UI can
        # show "—" rather than a fabricated number.
        target_load: int | None = None
        if weekly_load > 0:
            target_load = int(round(weekly_load * tmpl.load_fraction))

        # Filter contraindications relevant to this slot's type. The
        # database we built only emits generic phrases; we attach them
        # to strength + mobility (where exercise selection matters) but
        # not to pure cardio sessions (where "avoid deep squats" is moot).
        relevant_cis: list[str] = []
        if tmpl.type in (SessionType.STRENGTH, SessionType.MOBILITY):
            relevant_cis = list(contraindications)

        plan.append(PlannedSession(
            id=_plan_id(client_id, week_of, slot),
            client_id=client_id,
            week_of=week_of,
            slot=slot,
            type=tmpl.type,
            title=tmpl.title,
            description=tmpl.description,
            target_duration_min=tmpl.duration_min,
            target_load_au=target_load,
            target_rpe=tmpl.rpe,
            contraindications=relevant_cis,
            source=PlanSource.ENGINE,
            generated_at=datetime.now(),
            executed_session_id=None,
        ))
    return plan


def serialize_contraindications(items: Sequence[str]) -> str:
    """JSON-encode for the planned_sessions.contraindications column."""
    return json.dumps(list(items))


def parse_contraindications(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
        return [str(x) for x in loaded] if isinstance(loaded, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
