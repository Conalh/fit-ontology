"""
The ontology.

Five entities, modeled to integrate three otherwise-incompatible data sources:
  - Trainer (the account that owns clients — added in roadmap Phase 2a as
    the multi-tenant foundation; every client-data row carries a
    ``trainer_id`` so two trainers' rosters stay fully isolated)
  - Client intake (slow-changing facts: goals, injuries, anthropometrics)
  - Sessions (the trainer's first-party record of what happened)
  - Metrics (third-party wearables: heart rate, HRV, sleep, body comp)
  - Recommendations (the reasoning layer's output, with full source-data trail)

Modeling choices worth flagging:
  - Metric is a long-format table keyed by (client_id, date, kind, source).
    Sources differ in coverage and cadence; long format makes it trivial to
    join across them without column proliferation as we add wearables.
  - Recommendation carries a `source_metric_ids` reference so every output
    can be traced back to the exact rows that produced it. No black boxes.
  - We use Pydantic for validation at the ingestion boundary; storage is
    DuckDB (single-file, fast, SQL-compatible).
"""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class Trainer(BaseModel):
    """The account that owns a roster of clients.

    Added in roadmap Phase 2a as the multi-tenant foundation. ``email``
    is the natural identity (eventual SSO subject in Phase 2b);
    ``hashed_password`` is nullable so an SSO-only trainer has no
    password row, and a future email/password trainer can fill it.

    No FK to clients here — the parent-side relation is on
    ``clients.trainer_id``, which is the column that does the actual
    scoping work on every query.
    """
    id: str
    email: str
    name: str
    hashed_password: str | None = None
    created_at: datetime


class Sex(str, Enum):
    M = "M"
    F = "F"
    OTHER = "other"


class SessionType(str, Enum):
    STRENGTH = "strength"
    CARDIO = "cardio"
    MOBILITY = "mobility"
    MIXED = "mixed"


class MetricKind(str, Enum):
    HR_AVG = "hr_avg"
    HR_MAX = "hr_max"
    HRV_RMSSD = "hrv_rmssd"
    # Apple Health reports HRV as SDNN, not RMSSD. The two are highly
    # correlated in resting conditions but measure different things; we
    # keep them as separate kinds so reasoning stays within-source.
    HRV_SDNN = "hrv_sdnn"
    SLEEP_HOURS = "sleep_hours"
    SLEEP_QUALITY = "sleep_quality"
    SLEEP_SCORE = "sleep_score"
    BODY_WEIGHT_KG = "body_weight_kg"
    BODY_FAT_PCT = "body_fat_pct"
    RESTING_HR = "resting_hr"
    # Garmin-derived composite signals. We persist them in the same long
    # table because they're real per-day measurements the reasoning layer
    # can join against — even if no other wearable surfaces them today.
    BODY_BATTERY_HIGH = "body_battery_high"   # peak Body Battery in the day (0-100)
    BODY_BATTERY_LOW = "body_battery_low"     # trough Body Battery in the day (0-100)
    STRESS_AVG = "stress_avg"                 # mean Garmin stress score (0-100)
    TRAINING_READINESS = "training_readiness" # Garmin daily readiness (0-100)


class MetricSource(str, Enum):
    STRAVA = "strava"
    WHOOP = "whoop"
    GARMIN = "garmin"
    APPLE_HEALTH = "apple_health"
    MANUAL = "manual"


class Client(BaseModel):
    id: str
    # trainer_id is required for new clients (roadmap Phase 2a), but
    # left nullable on the Pydantic model so legacy fixtures that
    # predate the column don't need to be touched. The DB-helper layer
    # is the enforcement point: every write fills it from the calling
    # trainer's context.
    trainer_id: str | None = None
    name: str
    sex: Sex
    age: int = Field(ge=10, le=100)
    height_cm: float = Field(gt=100, lt=230)
    weight_kg: float = Field(gt=30, lt=250)
    goal: str
    injury_history: str | None = None
    created_at: datetime


class Session(BaseModel):
    id: str
    client_id: str
    date: date
    type: SessionType
    duration_min: int = Field(ge=5, le=300)
    rpe: int = Field(ge=1, le=10, description="Borg RPE (1-10) — client-reported exertion")
    notes: str | None = None


class Metric(BaseModel):
    id: str
    client_id: str
    date: date
    source: MetricSource
    kind: MetricKind
    value: float
    unit: str


class Recommendation(BaseModel):
    id: str
    client_id: str
    generated_at: datetime
    week_of: date
    recommendation: str
    rationale: str
    source_metric_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class PlanSource(str, Enum):
    """Provenance of a planned-session row.

    - ENGINE: emitted by reasoning.generate_plan() based on the week's
              verdict + recent training pattern + contraindications.
    - TRAINER: the trainer either edited an engine-generated row or
               added a brand-new slot. Once a slot is trainer-touched it
               does NOT get overwritten on the next regeneration — the
               trainer's adjustments are the canonical plan.
    """
    ENGINE = "engine"
    TRAINER = "trainer"


class PlannedSession(BaseModel):
    """One slot in a client's weekly plan.

    The plan is *prescriptive* — what the system thinks the client
    should do. ``Session`` (no prefix) is *descriptive* — what actually
    happened. They link via ``executed_session_id``: when the client
    logs a real session that maps onto a planned slot, the FK closes
    the plan-vs-execution loop. That telemetry powers future
    calibration work ("did the deload week actually get followed?").
    """
    id: str
    client_id: str
    week_of: date                                  # Monday of the planned week
    slot: int = Field(ge=1)                        # 1..N ordering across the week
    type: SessionType
    title: str                                     # "Lower strength" / "Z2 aerobic"
    description: str                               # trainer-editable detail
    target_duration_min: int | None = Field(default=None, ge=5, le=300)
    target_load_au: int | None = None              # planned RPE × duration (Foster sRPE)
    target_rpe: float | None = Field(default=None, ge=1, le=10)
    contraindications: list[str] = Field(default_factory=list)
    source: PlanSource
    generated_at: datetime
    # FK to sessions(id) once the client actually trains. Null until
    # the executed-session match runs (a separate concern from
    # generation/persistence).
    executed_session_id: str | None = None


class OverrideAction(str, Enum):
    """What the trainer did with the system's recommendation.

    - ACCEPT: followed the recommendation as-is.
    - EDIT:   followed the direction but applied a different magnitude.
              ``applied_load_change_pct`` captures what they actually did.
    - REJECT: ignored the recommendation and did something materially
              different (free-text in ``trainer_note`` explains).
    """
    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"


class RecommendationOverride(BaseModel):
    """A trainer's decision on a system recommendation.

    We snapshot the system's recommendation text and confidence at the
    moment of override rather than just FK'ing to recommendations.id,
    because the recommendation can change as more wearable data lands.
    The trainer's decision was made at a point in time with the data
    they had; preserving that is the audit value of this table.

    Keyed by (client_id, week_of) at the application level — multiple
    overrides for the same week are allowed (the trainer's view can
    change), and the most recent row is the operative decision.
    """
    id: str
    client_id: str
    week_of: date
    system_recommendation: str
    system_confidence: float = Field(ge=0.0, le=1.0)
    trainer_action: OverrideAction
    applied_load_change_pct: float | None = Field(default=None, ge=-100.0, le=100.0)
    trainer_note: str | None = None
    created_at: datetime


# DDL for DuckDB — kept in code so the schema lives with the model.
#
# Multi-tenant scoping (roadmap Phase 2a): every client-data table
# carries a ``trainer_id``. The column is added via ALTER TABLE rather
# than baked into the CREATE so an existing DuckDB file from the
# pre-Phase-2a era picks it up automatically on the next connect()
# (DuckDB's CREATE TABLE IF NOT EXISTS does NOT reconcile column
# differences — that's what the ADD COLUMN IF NOT EXISTS block at the
# bottom is for). The column is intentionally nullable at the DB level
# because (a) DuckDB can't ALTER a column to NOT NULL while existing
# data is present, and (b) the db.py helpers enforce trainer_id on
# every write, which is the chokepoint that actually matters. A later
# cleanup can do a table-rebuild to add the constraint once we're
# confident no pre-migration DBs are out there.
SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS trainers (
    id              VARCHAR PRIMARY KEY,
    email           VARCHAR NOT NULL UNIQUE,
    name            VARCHAR NOT NULL,
    hashed_password VARCHAR,
    created_at      TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
    id            VARCHAR PRIMARY KEY,
    name          VARCHAR NOT NULL,
    sex           VARCHAR NOT NULL,
    age           INTEGER NOT NULL,
    height_cm     DOUBLE NOT NULL,
    weight_kg     DOUBLE NOT NULL,
    goal          VARCHAR NOT NULL,
    injury_history VARCHAR,
    created_at    TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id            VARCHAR PRIMARY KEY,
    client_id     VARCHAR NOT NULL REFERENCES clients(id),
    date          DATE NOT NULL,
    type          VARCHAR NOT NULL,
    duration_min  INTEGER NOT NULL,
    rpe           INTEGER NOT NULL,
    notes         VARCHAR
);

CREATE TABLE IF NOT EXISTS metrics (
    id            VARCHAR PRIMARY KEY,
    client_id     VARCHAR NOT NULL REFERENCES clients(id),
    date          DATE NOT NULL,
    source        VARCHAR NOT NULL,
    kind          VARCHAR NOT NULL,
    value         DOUBLE NOT NULL,
    unit          VARCHAR NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_client_date ON metrics(client_id, date);
CREATE INDEX IF NOT EXISTS idx_sessions_client_date ON sessions(client_id, date);

CREATE TABLE IF NOT EXISTS recommendations (
    id                 VARCHAR PRIMARY KEY,
    client_id          VARCHAR NOT NULL REFERENCES clients(id),
    generated_at       TIMESTAMP NOT NULL,
    week_of            DATE NOT NULL,
    recommendation     VARCHAR NOT NULL,
    rationale          VARCHAR NOT NULL,
    source_metric_ids  VARCHAR,  -- JSON array of metric ids
    confidence         DOUBLE NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendation_overrides (
    id                       VARCHAR PRIMARY KEY,
    client_id                VARCHAR NOT NULL REFERENCES clients(id),
    week_of                  DATE NOT NULL,
    system_recommendation    VARCHAR NOT NULL,
    system_confidence        DOUBLE NOT NULL,
    trainer_action           VARCHAR NOT NULL,
    applied_load_change_pct  DOUBLE,
    trainer_note             VARCHAR,
    created_at               TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_overrides_client_week
    ON recommendation_overrides(client_id, week_of);

CREATE TABLE IF NOT EXISTS planned_sessions (
    -- The prescriptive plan for a client's training week, generated by
    -- reasoning.generate_plan() from the verdict + recent load + intake
    -- contraindications. Slot is a 1..N ordering rather than a day of
    -- the week (trainers want to drag-and-drop reorder; slot makes that
    -- trivial). executed_session_id closes the plan-vs-execution loop
    -- when the client actually logs a session.
    id                  VARCHAR PRIMARY KEY,
    client_id           VARCHAR NOT NULL REFERENCES clients(id),
    week_of             DATE NOT NULL,
    slot                INTEGER NOT NULL,
    type                VARCHAR NOT NULL,
    title               VARCHAR NOT NULL,
    description         VARCHAR NOT NULL,
    target_duration_min INTEGER,
    target_load_au      INTEGER,
    target_rpe          DOUBLE,
    contraindications   VARCHAR,  -- JSON array of strings
    source              VARCHAR NOT NULL,  -- 'engine' | 'trainer'
    generated_at        TIMESTAMP NOT NULL,
    executed_session_id VARCHAR
    -- No FK on executed_session_id: the column is set after the fact
    -- by a separate matcher and we don't want a stale plan to block a
    -- sessions row from being deleted.
);

CREATE INDEX IF NOT EXISTS idx_planned_sessions_client_week
    ON planned_sessions(client_id, week_of);

CREATE TABLE IF NOT EXISTS client_thresholds (
    -- Sparse per-client overrides on the reasoning module's severity
    -- thresholds. Only stored rows exist; everything else falls back to
    -- DEFAULT_THRESHOLDS in reasoning.py. Adding a row = the trainer
    -- saying "this client's HRV is more reactive than the population
    -- default" or similar.
    client_id   VARCHAR NOT NULL REFERENCES clients(id),
    name        VARCHAR NOT NULL,
    value       DOUBLE NOT NULL,
    PRIMARY KEY (client_id, name)
);

CREATE TABLE IF NOT EXISTS audit_log (
    -- Phase 5a append-only audit trail. Every sensitive write goes
    -- through record_audit() which inserts a row here; nobody DELETEs
    -- from this table during normal operation. The trainer_id makes
    -- the query "what has trainer X done in the last 7 days" cheap;
    -- ip + details JSON capture context we'd otherwise have to
    -- reconstruct from server logs (which on a hosted deploy may
    -- have ~3 day retention).
    --
    -- Schema intentionally narrow: action is a short opaque string
    -- (e.g. "auth.login", "client.created", "override.saved") with
    -- no FK to an enum table so adding a new audited action is just
    -- "call record_audit with a new action name" — no migration.
    id           VARCHAR PRIMARY KEY,
    trainer_id   VARCHAR NOT NULL,
    action       VARCHAR NOT NULL,
    target_type  VARCHAR,
    target_id    VARCHAR,
    details      VARCHAR,  -- JSON for action-specific context
    ip           VARCHAR,
    created_at   TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_log_trainer_created
    ON audit_log(trainer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_action
    ON audit_log(action);

CREATE TABLE IF NOT EXISTS client_share_tokens (
    -- Phase 3a: opaque token → read-only client view, no login. The
    -- trainer mints one of these per "send link" action; the client
    -- opens /share?t=<token> on their phone and sees this week's
    -- verdict + plan + an optional note from the trainer. Tokens
    -- expire (default 14 days) so a leaked link goes stale on its own
    -- without admin action. Multiple live tokens per client are fine
    -- — the trainer can re-issue without revoking the old one.
    id              VARCHAR PRIMARY KEY,
    token           VARCHAR NOT NULL UNIQUE,
    client_id       VARCHAR NOT NULL REFERENCES clients(id),
    trainer_id      VARCHAR NOT NULL,
    trainer_message VARCHAR,
    created_at      TIMESTAMP NOT NULL,
    expires_at      TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_share_tokens_token ON client_share_tokens(token);
CREATE INDEX IF NOT EXISTS idx_share_tokens_trainer_client
    ON client_share_tokens(trainer_id, client_id);

-- ─── Phase 2a multi-tenant scoping ──────────────────────────────────
-- Add trainer_id to every client-data table. ADD COLUMN IF NOT EXISTS
-- so a fresh DB and an existing DB both end up with the column. The
-- backfill (assigning existing rows to a default trainer) lives in
-- db._run_migrations() — DDL can't carry that data, only the column.
ALTER TABLE clients                  ADD COLUMN IF NOT EXISTS trainer_id VARCHAR;
ALTER TABLE sessions                 ADD COLUMN IF NOT EXISTS trainer_id VARCHAR;
ALTER TABLE metrics                  ADD COLUMN IF NOT EXISTS trainer_id VARCHAR;
ALTER TABLE recommendations          ADD COLUMN IF NOT EXISTS trainer_id VARCHAR;
ALTER TABLE recommendation_overrides ADD COLUMN IF NOT EXISTS trainer_id VARCHAR;
ALTER TABLE planned_sessions         ADD COLUMN IF NOT EXISTS trainer_id VARCHAR;
ALTER TABLE client_thresholds        ADD COLUMN IF NOT EXISTS trainer_id VARCHAR;

-- Indexes on (trainer_id, ...) for the hot lookup patterns. The
-- existing (client_id, date) indexes still serve client-detail views;
-- these new ones cover the trainer-roster / cross-client roll-ups.
CREATE INDEX IF NOT EXISTS idx_clients_trainer                  ON clients(trainer_id);
CREATE INDEX IF NOT EXISTS idx_sessions_trainer                 ON sessions(trainer_id);
CREATE INDEX IF NOT EXISTS idx_metrics_trainer                  ON metrics(trainer_id);
CREATE INDEX IF NOT EXISTS idx_recommendations_trainer          ON recommendations(trainer_id);
CREATE INDEX IF NOT EXISTS idx_recommendation_overrides_trainer ON recommendation_overrides(trainer_id);
CREATE INDEX IF NOT EXISTS idx_planned_sessions_trainer         ON planned_sessions(trainer_id);
CREATE INDEX IF NOT EXISTS idx_client_thresholds_trainer        ON client_thresholds(trainer_id);
"""
