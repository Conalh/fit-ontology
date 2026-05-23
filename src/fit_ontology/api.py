"""FastAPI surface over the fit_ontology modules.

Pragmatic, not RESTful-purist. Routes are shaped around what the
trainer-facing dashboard actually needs:

  GET  /api/clients
  GET  /api/clients/{client_id}
  GET  /api/clients/{client_id}/metrics?days=35
  GET  /api/clients/{client_id}/sessions?days=35
  GET  /api/clients/{client_id}/recommendation
  GET  /api/clients/{client_id}/overrides?limit=20
  POST /api/clients/{client_id}/overrides
  POST /api/clients/{client_id}/upload
  POST /api/clients/{client_id}/pdf       -> application/pdf
  GET  /api/roster                        -> per-client triage rows
  GET  /api/calibration                   -> overrides + agreement matrix

Connection lifecycle: every request opens a fresh DuckDB connection
(read-only for reads, write for writes) and closes it on response. We
don't pool — DuckDB is single-writer and the cached-singleton dance
the Streamlit dashboard uses doesn't translate to multi-process ASGI.
The overhead is ~milliseconds, which is fine for this scale.

CORS: open to localhost:3000 in dev so `next dev` can hit the API
running on the FastAPI port. In bundled mode (Next.js static export
served from this same FastAPI process) CORS isn't engaged at all.
"""
from __future__ import annotations

import contextlib
import tempfile
import uuid
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import load_env
from .contraindications import match_contraindications
from .db import (
    DEFAULT_DB_PATH,
    all_overrides,
    connect,
    delete_threshold,
    insert_metrics,
    insert_override,
    list_clients,
    metrics_for_client,
    overrides_for_client,
    sessions_for_client,
    thresholds_for_client,
    upsert_threshold,
)
from .ingest import (
    from_apple_health_export,
    from_strava_export,
    from_whoop_json,
)
from .ontology import OverrideAction, RecommendationOverride, Sex
from .reasoning import DEFAULT_THRESHOLDS, generate_recommendation
from .report import build_weekly_pdf

load_env()


# ─── Connection dependency ───────────────────────────────────────────

def _read_only_conn() -> Iterator[duckdb.DuckDBPyConnection]:
    """Per-request read-only connection. Closed in the dependency's
    teardown so we don't leak handles across requests."""
    con = connect(DEFAULT_DB_PATH, read_only=True)
    try:
        yield con
    finally:
        con.close()


# ─── Response schemas (light, derived from ontology models) ──────────

class ClientSummary(BaseModel):
    id: str
    name: str
    goal: str


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


class CalibrationResponse(BaseModel):
    total: int
    accept_rate: float
    edits: int
    rejects: int
    # matrix[system_type][action] -> count
    matrix: dict[str, dict[str, int]]
    recent: list[OverrideResponse]


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


# ─── App + CORS ──────────────────────────────────────────────────────

app = FastAPI(title="FitOntology API", version="0.5.0")
# NOTE: bumped in lockstep with pyproject.toml; the version string also
# appears in the OpenAPI doc so SDK consumers can pin against it.

app.add_middleware(
    CORSMiddleware,
    # `next dev` runs on 3000 by default. The bundled deploy serves the
    # static export from this same FastAPI process, so the same-origin
    # rule already covers it — we only need CORS for the dev loop.
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Routes ──────────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/clients", response_model=list[ClientSummary])
def get_clients(con=Depends(_read_only_conn)) -> list[ClientSummary]:
    df = list_clients(con)
    return [ClientSummary(**row) for row in df.to_dict(orient="records")]


@app.get("/api/clients/{client_id}")
def get_client(client_id: str, con=Depends(_read_only_conn)) -> dict:
    row = con.execute(
        "SELECT id, name, sex, age, height_cm, weight_kg, goal, injury_history FROM clients WHERE id = ?",
        [client_id],
    ).df()
    if row.empty:
        raise HTTPException(status_code=404, detail=f"No client with id {client_id}")
    return row.iloc[0].to_dict()


@app.post("/api/clients")
def post_client(payload: ClientCreate) -> dict:
    """Create a new client. Returns the generated id so the front-end
    can navigate straight to the detail page."""
    client_id = f"c_{uuid.uuid4().hex[:12]}"
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            con.execute(
                """
                INSERT INTO clients
                  (id, name, sex, age, height_cm, weight_kg, goal, injury_history, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    client_id,
                    payload.name,
                    payload.sex.value,
                    payload.age,
                    payload.height_cm,
                    payload.weight_kg,
                    payload.goal,
                    payload.injury_history,
                ],
            )
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e
    return {"id": client_id}


@app.patch("/api/clients/{client_id}")
def patch_client(client_id: str, payload: ClientUpdate) -> dict:
    """Partial update. Builds the SET clause from only the fields the
    trainer touched so we don't overwrite values they left alone."""
    updates = payload.model_dump(exclude_none=True)
    if "sex" in updates and isinstance(updates["sex"], Sex):
        updates["sex"] = updates["sex"].value
    if not updates:
        return {"ok": True, "updated": []}

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = [*updates.values(), client_id]
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            existing = con.execute(
                "SELECT 1 FROM clients WHERE id = ?", [client_id]
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail=f"No client with id {client_id}")
            con.execute(f"UPDATE clients SET {set_clause} WHERE id = ?", values)
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e
    return {"ok": True, "updated": list(updates.keys())}


@app.get("/api/clients/{client_id}/metrics", response_model=list[MetricRow])
def get_metrics(client_id: str, days: int = 35, con=Depends(_read_only_conn)) -> list[MetricRow]:
    df = metrics_for_client(con, client_id, days=days)
    if df.empty:
        return []
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return [MetricRow(**row) for row in df.to_dict(orient="records")]


@app.get("/api/clients/{client_id}/sessions", response_model=list[SessionRow])
def get_sessions(client_id: str, days: int = 35, con=Depends(_read_only_conn)) -> list[SessionRow]:
    df = sessions_for_client(con, client_id, days=days)
    if df.empty:
        return []
    df["date"] = pd.to_datetime(df["date"]).dt.date
    # SessionRow doesn't carry client_id (already in the route); drop it
    # if the SQL ever adds it.
    return [
        SessionRow(
            id=row["id"], date=row["date"], type=row["type"],
            duration_min=int(row["duration_min"]), rpe=int(row["rpe"]),
            notes=row["notes"] if pd.notna(row["notes"]) else None,
        )
        for row in df.to_dict(orient="records")
    ]


@app.get("/api/clients/{client_id}/recommendation", response_model=RecommendationResponse)
def get_recommendation(client_id: str, con=Depends(_read_only_conn)) -> RecommendationResponse:
    metrics = metrics_for_client(con, client_id, days=35)
    sessions = sessions_for_client(con, client_id, days=35)
    overrides = thresholds_for_client(con, client_id)
    rec = generate_recommendation(client_id, metrics, sessions, thresholds=overrides)

    # Contraindications come from the trainer's free-text intake — pull
    # it here rather than threading another arg through the reasoning
    # module. The recovery-verdict and the structural-constraint layers
    # stay decoupled.
    injury_row = con.execute(
        "SELECT injury_history FROM clients WHERE id = ?", [client_id]
    ).fetchone()
    injury = injury_row[0] if injury_row else None
    contras = [
        ContraindicationItem(kind=c.kind, title=c.title, advice=c.advice, source_phrase=c.source_phrase)
        for c in match_contraindications(injury)
    ]

    return RecommendationResponse(
        id=rec.id, client_id=rec.client_id, week_of=rec.week_of,
        recommendation=rec.recommendation, rationale=rec.rationale,
        source_metric_ids=rec.source_metric_ids, confidence=rec.confidence,
        generated_at=rec.generated_at,
        contraindications=contras,
    )


@app.get("/api/clients/{client_id}/overrides", response_model=list[OverrideResponse])
def get_overrides(client_id: str, limit: int = 20, con=Depends(_read_only_conn)) -> list[OverrideResponse]:
    df = overrides_for_client(con, client_id, limit=limit)
    if df.empty:
        return []
    return [_override_response(row) for row in df.to_dict(orient="records")]


@app.post("/api/clients/{client_id}/overrides", response_model=OverrideResponse)
def post_override(client_id: str, payload: OverrideCreate) -> OverrideResponse:
    ov = RecommendationOverride(
        id=f"o_{uuid.uuid4().hex[:12]}",
        client_id=client_id,
        week_of=payload.week_of,
        system_recommendation=payload.system_recommendation,
        system_confidence=payload.system_confidence,
        trainer_action=payload.trainer_action,
        applied_load_change_pct=payload.applied_load_change_pct,
        trainer_note=payload.trainer_note,
        created_at=datetime.now(),
    )
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            insert_override(con, ov)
    except duckdb.IOException as e:
        # Cross-process write conflict (Garmin sync holds the writer lock).
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e

    return _override_response_from_model(ov)


@app.get("/api/clients/{client_id}/thresholds", response_model=ThresholdsResponse)
def get_thresholds(client_id: str, con=Depends(_read_only_conn)) -> ThresholdsResponse:
    """Returns the global defaults + this client's sparse overrides.
    Front-end renders each threshold with the override styled distinctly
    when present."""
    return ThresholdsResponse(
        defaults=DEFAULT_THRESHOLDS,
        overrides=thresholds_for_client(con, client_id),
    )


@app.patch("/api/clients/{client_id}/thresholds", response_model=ThresholdsResponse)
def patch_thresholds(client_id: str, payload: ThresholdsPatch) -> ThresholdsResponse:
    """Sparse upsert/delete. Keys with a float value are upserted;
    keys with null are deleted (reverting to the global default).
    Unknown threshold names are rejected so we don't accumulate
    junk rows the reasoning layer never reads."""
    unknown = set(payload.overrides) - set(DEFAULT_THRESHOLDS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown threshold name(s): {sorted(unknown)}",
        )
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            for name, value in payload.overrides.items():
                if value is None:
                    delete_threshold(con, client_id, name)
                else:
                    upsert_threshold(con, client_id, name, value)
            new_overrides = thresholds_for_client(con, client_id)
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e
    return ThresholdsResponse(defaults=DEFAULT_THRESHOLDS, overrides=new_overrides)


@app.post("/api/clients/{client_id}/upload", response_model=dict)
async def post_upload(client_id: str, file: UploadFile = File(...)) -> dict:
    """Accept a wearable export and ingest it for the given client.

    Sniffs the format from the upload's filename + the first few KB of
    content (matching the Streamlit dashboard's behavior). Returns the
    number of rows inserted and the distinct metric kinds.
    """
    raw = await file.read()
    suffix = Path(file.filename or "").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        tmp_file.write(raw)
        tmp_path = Path(tmp_file.name)
    try:
        if suffix == ".zip" or (suffix == ".xml" and b"HealthData" in raw[:4096]):
            df = from_apple_health_export(tmp_path, client_id)
        elif suffix == ".csv":
            df = from_strava_export(tmp_path, client_id)
        elif suffix == ".json":
            df = from_whoop_json(tmp_path, client_id)
        else:
            raise HTTPException(status_code=415, detail=f"Unsupported file type: {file.filename}")
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()

    if df.empty:
        return {"inserted": 0, "kinds": []}

    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as con:
            insert_metrics(con, df)
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e

    return {"inserted": int(len(df)), "kinds": sorted(df["kind"].unique().tolist())}


class PdfRequest(BaseModel):
    coach_message: str | None = None


@app.post("/api/clients/{client_id}/pdf")
def post_pdf(client_id: str, payload: PdfRequest, con=Depends(_read_only_conn)) -> Response:
    row = con.execute(
        "SELECT name, goal FROM clients WHERE id = ?", [client_id]
    ).df()
    if row.empty:
        raise HTTPException(status_code=404, detail=f"No client with id {client_id}")

    metrics = metrics_for_client(con, client_id, days=35)
    sessions = sessions_for_client(con, client_id, days=35)
    rec = generate_recommendation(client_id, metrics, sessions)

    pdf_bytes = build_weekly_pdf(
        client_name=row.iloc[0]["name"],
        client_goal=row.iloc[0]["goal"],
        rec=rec,
        metrics=metrics,
        coach_message=payload.coach_message,
    )
    filename = f"{row.iloc[0]['name'].replace(' ', '_')}_week_{rec.week_of:%Y%m%d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/ask", response_model=AskResponse)
def post_ask(payload: AskRequest) -> AskResponse:
    """Run one turn of the Ask FitOntology tool-use loop.

    Wraps fit_ontology.assistant.ask(); the client passes back the
    prior turn's ``messages`` as ``history`` to keep multi-turn context
    (tool_use + tool_result blocks intact). Same model + system prompt
    + tool set as the Streamlit page used.
    """
    from .assistant import DEFAULT_MODEL, ask  # local import keeps anthropic SDK optional at import time

    try:
        turn = ask(
            payload.question,
            history=payload.history or None,
            model=payload.model or DEFAULT_MODEL,
        )
    except RuntimeError as e:
        # ANTHROPIC_API_KEY missing — surface as 412 so the front-end
        # can show a meaningful "set your API key" message instead of
        # a generic 500.
        raise HTTPException(status_code=412, detail=str(e)) from e

    return AskResponse(
        answer=turn.answer,
        traces=[
            AskTrace(name=t.name, arguments=dict(t.arguments), result_summary=t.result_summary)
            for t in turn.traces
        ],
        turns_used=turn.turns_used,
        messages=turn.messages,
    )


@app.get("/api/roster", response_model=list[RosterRow])
def get_roster(con=Depends(_read_only_conn)) -> list[RosterRow]:
    """Computed roster: one row per client with the recommendation
    label, flag kinds, and freshness. The frontend handles sorting and
    presentation — we just hand over structured data."""
    clients = list_clients(con)
    if clients.empty:
        return []

    today = pd.Timestamp(date.today())
    out: list[RosterRow] = []

    for _, client in clients.iterrows():
        cid = client["id"]
        metrics = metrics_for_client(con, cid, days=28)
        sessions = sessions_for_client(con, cid, days=28)

        last_days: int | None = None
        if not metrics.empty:
            last_days = int((today - pd.to_datetime(metrics["date"]).max()).days)

        if last_days is None or last_days > 7:
            out.append(RosterRow(
                client_id=cid, name=client["name"], goal=client["goal"],
                label="No recent data", flags=[],
                confidence=None, sources=0,
                last_data_days=last_days, stale=True,
            ))
            continue

        rec = generate_recommendation(cid, metrics, sessions)
        label = _classify_rec(rec.recommendation)
        flags: list[str] = []
        if "Flags:" in rec.rationale:
            flags = [f.strip() for f in rec.rationale.split("Flags:", 1)[1].strip().rstrip(".").split(",") if f.strip()]

        out.append(RosterRow(
            client_id=cid, name=client["name"], goal=client["goal"],
            label=label, flags=flags,
            confidence=rec.confidence, sources=len(rec.source_metric_ids),
            last_data_days=last_days, stale=False,
        ))

    return out


@app.get("/api/calibration", response_model=CalibrationResponse)
def get_calibration(con=Depends(_read_only_conn)) -> CalibrationResponse:
    df = all_overrides(con, limit=1000)
    if df.empty:
        return CalibrationResponse(
            total=0, accept_rate=0.0, edits=0, rejects=0, matrix={}, recent=[],
        )

    # Add the classification we use in the matrix index.
    df = df.copy()
    df["system_type"] = df["system_recommendation"].apply(_classify_rec)

    total = len(df)
    accept_n = int((df["trainer_action"] == "accept").sum())
    edit_n = int((df["trainer_action"] == "edit").sum())
    reject_n = int((df["trainer_action"] == "reject").sum())

    matrix: dict[str, dict[str, int]] = {}
    for system_type, group in df.groupby("system_type"):
        action_counts = group["trainer_action"].value_counts().to_dict()
        matrix[str(system_type)] = {str(k): int(v) for k, v in action_counts.items()}

    recent = [_override_response(row) for row in df.head(25).to_dict(orient="records")]

    return CalibrationResponse(
        total=total,
        accept_rate=accept_n / total if total else 0.0,
        edits=edit_n,
        rejects=reject_n,
        matrix=matrix,
        recent=recent,
    )


# ─── Helpers ─────────────────────────────────────────────────────────

def _classify_rec(rec_text: str) -> str:
    low = rec_text.lower()
    if low.startswith("deload"):
        return "Deload"
    if low.startswith("conservative"):
        return "Conservative"
    if low.startswith("standard"):
        return "Standard"
    return "Other"


def _override_response(row: dict) -> OverrideResponse:
    """Coerce a DataFrame row dict into an OverrideResponse. Pandas
    returns NaN for null DOUBLEs and NaT for nulls in datetime columns;
    we normalize to None for JSON serialization."""
    pct = row.get("applied_load_change_pct")
    if pct is not None and pd.isna(pct):
        pct = None
    note = row.get("trainer_note")
    if note is not None and pd.isna(note):
        note = None
    return OverrideResponse(
        id=row["id"], client_id=row["client_id"], week_of=row["week_of"],
        system_recommendation=row["system_recommendation"],
        system_confidence=float(row["system_confidence"]),
        trainer_action=str(row["trainer_action"]),
        applied_load_change_pct=pct,
        trainer_note=note,
        created_at=row["created_at"],
    )


def _override_response_from_model(ov: RecommendationOverride) -> OverrideResponse:
    return OverrideResponse(
        id=ov.id, client_id=ov.client_id, week_of=ov.week_of,
        system_recommendation=ov.system_recommendation,
        system_confidence=ov.system_confidence,
        trainer_action=ov.trainer_action.value,
        applied_load_change_pct=ov.applied_load_change_pct,
        trainer_note=ov.trainer_note,
        created_at=ov.created_at,
    )


# ─── Static frontend mount ───────────────────────────────────────────
#
# When the Next.js export exists at ``web/out/``, serve it at ``/``
# under this same FastAPI process. Local-first deployment, one URL,
# no CORS round-trip. In dev (no static export) the Next.js dev server
# runs on its own port and hits ``/api`` here via CORS.

_STATIC_ROOT = Path(__file__).resolve().parents[2] / "web" / "out"
if _STATIC_ROOT.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_ROOT), html=True), name="web")
