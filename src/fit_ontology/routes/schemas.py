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

# ─── Coach Assistant (Phase 7a) ─────────────────────────────────────

class CoachDraftResponse(BaseModel):
    """Result of a coach-message draft. Plain text + which model
    produced it (so the UI can render a small "drafted by X"
    attribution if it wants)."""
    draft: str
    model: str


# ─── Share tokens (Phase 3a) ────────────────────────────────────────

class ShareCreateRequest(BaseModel):
    """Trainer POST body. trainer_message is the optional inline note
    the client sees alongside the verdict — kept short on purpose so
    it nudges trainers toward "training observation," not "wall of
    text the client won't read on their phone."""
    trainer_message: str | None = Field(default=None, max_length=500)


class ShareCreateResponse(BaseModel):
    """Returns just the token (the front-end builds the full URL —
    the server doesn't know what hostname the trainer is using) plus
    the expiry so the UI can show "expires in N days"."""
    token: str
    expires_at: datetime


class SharePlannedSession(BaseModel):
    """Per-slot fields the client portal renders. Mirrors the
    trainer-side PlannedSessionResponse but strips fields the client
    has no reason to see (id, generated_at, contraindications,
    executed_session_id) and adds a boolean ``done`` so the UI can
    check off completed slots without needing the FK."""
    slot: int
    type: str
    title: str
    description: str
    target_duration_min: int | None
    target_rpe: float | None
    done: bool


class ShareViewResponse(BaseModel):
    """Public client-portal payload. Deliberately omits intake PII
    (sex, age, height, weight, injury history), other clients'
    anything, raw wearable rows, override history, and per-client
    thresholds. Only what the client needs to read this week."""
    client_first_name: str
    week_of: date
    recommendation: str
    rationale: str
    confidence: float
    recovery_score: dict
    plan: list[SharePlannedSession]
    trainer_message: str | None
    expires_at: datetime


# ─── Intake tokens (Phase 3b) ───────────────────────────────────────

class IntakeMintRequest(BaseModel):
    """Trainer POST body. trainer_message is the optional welcome blurb
    the prospective client sees above the form — kept short by the
    same length cap as the share-link note so trainers don't paste a
    wall of text the client won't read."""
    trainer_message: str | None = Field(default=None, max_length=500)


class IntakeMintResponse(BaseModel):
    """Returns just the token + expiry. The front-end builds the full
    URL (``${origin}/intake?t=<token>``) since the server doesn't
    know which hostname the trainer is using — same posture as
    ShareCreateResponse."""
    token: str
    expires_at: datetime


class IntakeViewResponse(BaseModel):
    """Public payload for the intake form page. Carries trainer name
    (for personalization) and optional welcome message, plus the
    ``consumed`` flag so the page can render an "already submitted"
    state with the trainer's name still visible — more useful UX
    than a generic 410, which we reserve for expired-and-unusable.

    Deliberately omits trainer_id and any other internal identifier
    — those are server-side only. The token in the URL is the
    bearer credential; the response just carries display data."""
    trainer_name: str
    trainer_message: str | None
    expires_at: datetime
    consumed: bool


# ─── Auth (Phase 2b-α) ──────────────────────────────────────────────

class LoginRequest(BaseModel):
    """POST /api/auth/login body. Email is normalized to lowercase by
    the verifier; password is whatever the user typed (the helper
    handles trim + bcrypt's 72-byte cap)."""
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class AuthMeResponse(BaseModel):
    """Trainer profile returned by /login and /me. Deliberately omits
    hashed_password and created_at — the front-end only needs to render
    a name and route between login/dashboard."""
    id: str
    email: str
    name: str


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


class RecoveryScoreResponse(BaseModel):
    """Composite 0–100 recovery state + its four sub-components.

    Computed fresh on every recommendation fetch (unlike the verdict
    itself, which is lazy-persisted weekly). The verdict answers "what
    decision did the system make on Monday?"; the gauge answers "what
    does the current data look like right now?". The two read together.
    """
    composite: int | None
    hrv: int | None
    sleep: int | None
    rhr: int | None
    acwr: int | None


class TrendDetailResponse(BaseModel):
    """E5: per-kind acute (7d OLS) + chronic (28d EWMA) detector
    outputs surfaced to the rec card's trend chips. Lets the chip
    render an acute/chronic/both badge AND expose the numbers in its
    info popover without the frontend doing a second round-trip.

    All slope/SD values are absolute magnitudes — sign is implicit in
    the signal kind. ``acute_fired`` / ``chronic_fired`` mean "this
    window's severity grade was non-None before the combiner ran" —
    i.e. it crossed the relevant threshold. The chip badge reads
    these to pick its visual: acute-only / chronic-only / both."""
    kind: str  # e.g. "hrv_trend_down"
    acute_window_days: int
    acute_slope_per_day: float | None
    acute_sd_per_day: float | None
    acute_fired: bool
    chronic_window_days: int
    chronic_slope_per_day: float | None
    chronic_sd_per_day: float | None
    chronic_fired: bool
    chronic_confidence_weight: float


class RecommendationPreviewResponse(BaseModel):
    recommendation: str
    rationale: str
    source_metric_ids: list[str]
    confidence: float
    generated_at: datetime


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
    # Live recovery gauge (None on history rows — see RecoveryScoreResponse).
    recovery_score: RecoveryScoreResponse | None = None
    # Map of flag kind -> source authority for that signal (e.g.
    # ``hrv_below_baseline`` -> "Plews & Laursen 2017"). The front-end
    # surfaces these on flag chip tooltips + a methodology footer
    # rather than embedding the citations in the rationale text itself.
    flag_citations: dict[str, str] = {}
    # E5: per-trend-kind detector diagnostics. Keyed by signal kind
    # ("hrv_trend_down" etc.) — frontend looks up by chip's flag name
    # to render the acute/chronic badge + popover. Empty on history
    # rows where we don't recompute the engine; populated on the
    # current week's recommendation.
    trend_details: dict[str, TrendDetailResponse] = {}
    # True when this is the persisted weekly snapshot instead of an
    # ephemeral in-memory compute.
    is_locked: bool = False
    # Current engine output when it would differ from the locked weekly
    # snapshot. Kept separate so trainers see drift without silent churn.
    live_preview: RecommendationPreviewResponse | None = None
    preview_differs: bool = False


# ─── Overrides ──────────────────────────────────────────────────────

class OverrideResponse(BaseModel):
    id: str
    client_id: str
    week_of: date
    system_recommendation: str
    system_confidence: float
    trainer_action: str
    trainer_recommendation: str | None = None
    applied_load_change_pct: float | None
    trainer_note: str | None
    created_at: datetime


class OverrideCreate(BaseModel):
    week_of: date
    system_recommendation: str
    system_confidence: float = Field(ge=0.0, le=1.0)
    trainer_action: OverrideAction
    trainer_recommendation: str | None = Field(default=None, max_length=500)
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


class ActionQueueItem(BaseModel):
    """One trainer-facing next action on the dashboard.

    The queue is workflow-shaped rather than raw-signal-shaped: each
    item names the client, why they need attention, and where the
    trainer should go next.
    """
    id: str
    client_id: str
    client_name: str
    client_goal: str
    priority: str  # "high" | "medium" | "low"
    kind: str
    title: str
    detail: str
    cta_label: str
    href: str


class WeeklyDeltaResponse(BaseModel):
    """Current-week plan-vs-reality summary for one client."""
    week_of: date
    status: str  # "on_track" | "watch" | "off_track" | "no_plan"
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


class PlanAdherenceRow(BaseModel):
    """Per-client plan-vs-execution telemetry.

    Computed from the (planned_sessions ⋈ sessions) join the matcher
    populates. ``match_rate`` tells the trainer how often the client
    actually shows up for the prescribed work; ``load_delta_pct`` and
    ``rpe_delta`` tell them whether the client systematically trains
    harder or softer than the plan called for. Null delta values mean
    too few matched sessions to compute a stable deviation.
    """
    client_id: str
    name: str
    total_slots: int          # planned slots across all weeks for this client
    matched_slots: int        # of which, how many have an executed session
    match_rate: float         # matched_slots / total_slots (0 if no slots)
    load_delta_pct: float | None  # (actual - planned) / planned, mean across matched slots
    rpe_delta: float | None       # mean(actual_rpe - planned_rpe) across matched slots


class CalibrationSuggestion(BaseModel):
    """Actionable tuning prompt derived from the override history.
    The frontend renders these as a single "consider tuning" card so the
    trainer sees concrete next steps rather than a wall of numbers."""
    kind: str  # 'threshold_tune' | 'per_client_drift'
    severity: str  # 'info' | 'warn'
    message: str
    target: str | None = None  # client_id or threshold name when relevant


class PlannedSessionResponse(BaseModel):
    """One slot of the weekly plan. ``contraindications`` is a list of
    short warning phrases the engine attached (e.g. "avoid deep
    bilateral squats"); the frontend renders them as small chips below
    the session description. ``source`` is "engine" on initial
    generation and flips to "trainer" once any field is PATCH'd."""
    id: str
    client_id: str
    week_of: date
    slot: int = Field(ge=1)
    type: str
    title: str
    description: str
    target_duration_min: int | None = None
    target_load_au: int | None = None
    target_rpe: float | None = None
    contraindications: list[str] = []
    source: str
    generated_at: datetime
    executed_session_id: str | None = None


class PlanResponse(BaseModel):
    """The whole week's plan in a single payload — slot-ordered."""
    week_of: date
    verdict: str  # 'DELOAD' | 'CONSERVATIVE' | 'STANDARD' — what drove this plan
    sessions: list[PlannedSessionResponse]


class PlannedSessionPatch(BaseModel):
    """Partial-update payload. Every field optional — the SQL UPDATE only
    touches what the trainer changed. Patching anything flips the row's
    ``source`` to "trainer" so future engine regeneration knows not to
    overwrite it."""
    type: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    target_duration_min: int | None = Field(default=None, ge=5, le=300)
    target_load_au: int | None = Field(default=None, ge=0)
    target_rpe: float | None = Field(default=None, ge=1, le=10)


class ConfidenceBucket(BaseModel):
    """One row of the engine-confidence-vs-trainer-acceptance audit.

    The engine claims a confidence on every recommendation. This bucket
    aggregates persisted recs into 0.5-wide bands and reports the rate
    at which the trainer accepted them. If 0.8-confidence recs and
    0.6-confidence recs get accepted at the same rate, the engine's
    confidence is theater — that's worth knowing.
    """
    low: float   # band low end, inclusive
    high: float  # band high end, exclusive (the top bucket includes 1.0)
    total: int
    accepts: int
    accept_rate: float


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
    confidence_audit: list[ConfidenceBucket] = []
    plan_adherence: list[PlanAdherenceRow] = []


# ─── Thresholds ─────────────────────────────────────────────────────

class BaselineWindowSuggestionResponse(BaseModel):
    """Auto-fit's pick for this client's baseline window length. The
    trainer can apply with one click on the thresholds panel.
    ``stable=False`` means the fit fell back to the literature default
    because no candidate window settled — worth telling the trainer."""
    days: int
    stable: bool
    reason: str


class ThresholdsResponse(BaseModel):
    """Defaults + overrides shape so the front-end can show each
    threshold with both its baseline and the trainer's per-client tweak
    (when one exists)."""
    defaults: dict[str, float]
    overrides: dict[str, float]
    baseline_window_suggestion: BaselineWindowSuggestionResponse | None = None


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
