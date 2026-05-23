"""Pydantic request/response models shared across the route modules.

Kept in one file because they form a single coherent surface — the
front-end's ``lib/api.ts`` type definitions are derived from these
shapes, and splitting them per-router would just force a tangle of
cross-router imports.
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from ..ontology import OverrideAction, Sex


# ─── Clients ────────────────────────────────────────────────────────

class ClientSummary(BaseModel):
    id: str
    name: str
    goal: str


class ClientCreate(BaseModel):
    """Trainer intake payload. Same shape as ontology.Client minus the
    server-managed fields (id, created_at) — those get filled in on
    insert. Pydantic ranges mirror the storage model so validation
    errors surface at the API boundary, not deep in the DB."""

    name: str = Field(min_length=1, max_length=80)
    sex: Sex
    age: int = Field(ge=10, le=100)
    height_cm: float = Field(gt=100, lt=230)
    weight_kg: float = Field(gt=30, lt=250)
    goal: str = Field(min_length=1, max_length=200)
    injury_history: str | None = None


class ClientUpdate(BaseModel):
    """Partial update. Every field optional; the SQL UPDATE only touches
    the keys the trainer actually changed so concurrent edits to
    unrelated fields don't clobber each other."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    sex: Sex | None = None
    age: int | None = Field(default=None, ge=10, le=100)
    height_cm: float | None = Field(default=None, gt=100, lt=230)
    weight_kg: float | None = Field(default=None, gt=30, lt=250)
    goal: str | None = Field(default=None, min_length=1, max_length=200)
    injury_history: str | None = None


# ─── Metrics / sessions ─────────────────────────────────────────────

class MetricRow(BaseModel):
    id: str
    date: date
    source: str
    kind: str
    value: float
    unit: str


class SessionRow(BaseModel):
    id: str
    date: date
    type: str
    duration_min: int
    rpe: int
    notes: str | None = None


# ─── Recommendations ────────────────────────────────────────────────

class ContraindicationItem(BaseModel):
    kind: str
    title: str
    advice: str
    source_phrase: str


class RecommendationResponse(BaseModel):
    id: str
    client_id: str
    week_of: date
    recommendation: str
    rationale: str
    source_metric_ids: list[str]
    confidence: float
    generated_at: datetime
    # Static per-client constraints derived from the trainer's intake.
    # Independent of the weekly verdict — a deload still respects
    # "cap plyometrics" on a knee-history client.
    contraindications: list[ContraindicationItem] = []


# ─── Overrides ──────────────────────────────────────────────────────

class OverrideResponse(BaseModel):
    id: str
    client_id: str
    week_of: date
    system_recommendation: str
    system_confidence: float
    trainer_action: str
    applied_load_change_pct: float | None
    trainer_note: str | None
    created_at: datetime


class OverrideCreate(BaseModel):
    week_of: date
    system_recommendation: str
    system_confidence: float = Field(ge=0.0, le=1.0)
    trainer_action: OverrideAction
    applied_load_change_pct: float | None = Field(default=None, ge=-100.0, le=100.0)
    trainer_note: str | None = None


# ─── Roster ─────────────────────────────────────────────────────────

class RosterRow(BaseModel):
    """One row of the Monday-morning triage table.

    Stale clients (no metrics in the last 7 days) carry ``stale=True``
    and a ``label`` of "No recent data" so the front-end can sort or
    bucket them distinctly from a clean "standard progression."
    """
    client_id: str
    name: str
    goal: str
    label: str  # "Deload" | "Conservative" | "Standard" | "No recent data"
    flags: list[str]
    confidence: float | None
    sources: int
    last_data_days: int | None
    stale: bool


# ─── Calibration ────────────────────────────────────────────────────

class WeeklyAgreement(BaseModel):
    """One point on the acceptance-rate-over-time chart. We bucket
    overrides by ``week_of`` so trends line up with the weekly
    recommendation cadence."""
    week_of: date
    total: int
    accepts: int
    accept_rate: float


class PerClientAgreement(BaseModel):
    """Per-client tally so the trainer can spot the clients they're
    chronically out of sync with."""
    client_id: str
    name: str
    total: int
    accepts: int
    edits: int
    rejects: int
    accept_rate: float


class CalibrationSuggestion(BaseModel):
    """Actionable tuning prompt derived from the override history.
    The frontend renders these as a single "consider tuning" card so the
    trainer sees concrete next steps rather than a wall of numbers."""
    kind: str  # 'threshold_tune' | 'per_client_drift'
    severity: str  # 'info' | 'warn'
    message: str
    target: str | None = None  # client_id or threshold name when relevant


class CalibrationResponse(BaseModel):
    total: int
    accept_rate: float
    edits: int
    rejects: int
    # matrix[system_type][action] -> count
    matrix: dict[str, dict[str, int]]
    recent: list[OverrideResponse]
    by_week: list[WeeklyAgreement]
    by_client: list[PerClientAgreement]
    suggestions: list[CalibrationSuggestion]


# ─── Thresholds ─────────────────────────────────────────────────────

class ThresholdsResponse(BaseModel):
    """Defaults + overrides shape so the front-end can show each
    threshold with both its baseline and the trainer's per-client tweak
    (when one exists)."""
    defaults: dict[str, float]
    overrides: dict[str, float]


class ThresholdsPatch(BaseModel):
    """Sparse patch — only the keys the trainer touched. ``None``
    deletes that key (reverts to the global default); a float upserts."""
    overrides: dict[str, float | None]


# ─── PDF ────────────────────────────────────────────────────────────

class PdfRequest(BaseModel):
    coach_message: str | None = None


# ─── Ask FitOntology ────────────────────────────────────────────────

class AskTrace(BaseModel):
    name: str
    arguments: dict[str, object]
    result_summary: str


class AskRequest(BaseModel):
    question: str
    # Anthropic-format message stream from a prior turn — pass back to
    # keep multi-turn context (tool_use + tool_result blocks included,
    # which is what makes the chat actually coherent past turn 1).
    history: list[dict] = []
    model: str | None = None


class AskResponse(BaseModel):
    answer: str
    traces: list[AskTrace]
    turns_used: int
    messages: list[dict]
