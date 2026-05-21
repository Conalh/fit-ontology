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
from typing import Optional

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
    SLEEP_HOURS = "sleep_hours"
    SLEEP_QUALITY = "sleep_quality"
    BODY_WEIGHT_KG = "body_weight_kg"
    BODY_FAT_PCT = "body_fat_pct"
    RESTING_HR = "resting_hr"


class MetricSource(str, Enum):
    STRAVA = "strava"
    WHOOP = "whoop"
    GARMIN = "garmin"
    MANUAL = "manual"


class Client(BaseModel):
    id: str
    name: str
    sex: Sex
    age: int = Field(ge=10, le=100)
    height_cm: float = Field(gt=100, lt=230)
    weight_kg: float = Field(gt=30, lt=250)
    goal: str
    injury_history: Optional[str] = None
    created_at: datetime


class Session(BaseModel):
    id: str
    client_id: str
    date: date
    type: SessionType
    duration_min: int = Field(ge=5, le=300)
    rpe: int = Field(ge=1, le=10, description="Borg RPE (1-10) — client-reported exertion")
    notes: Optional[str] = None


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
"""
