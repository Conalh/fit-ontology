"""
The ontology.

Four entities, modeled to integrate three otherwise-incompatible data sources:
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
SCHEMA_DDL = """
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
"""
