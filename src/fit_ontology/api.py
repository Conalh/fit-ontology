"""FastAPI surface over the fit_ontology modules.

Pragmatic, not RESTful-purist. Route handlers live in ``fit_ontology.routes.*``
and are mounted here; this file is the app factory + cross-cutting concerns
(CORS, the bundled static frontend mount).

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

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import load_env
from .routes import (
    ask,
    auth,
    calibration,
    clients,
    metrics,
    overrides,
    pdf,
    planning,
    recommendation,
    roster,
    share,
    thresholds,
)
from .routes.deps import read_only_conn

# Re-export the connection dependency so existing test code that does
# ``api_mod.app.dependency_overrides[api_mod._read_only_conn] = ...``
# keeps working without modification.
_read_only_conn = read_only_conn

load_env()


app = FastAPI(title="FitOntology API", version="0.5.1")
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


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


# Order doesn't matter for routing — FastAPI matches paths from the
# union of all routers' route tables. Grouped roughly by ontology
# surface (clients → metrics → rec → overrides → calibration → tuning
# → exports → assistant → roster).
app.include_router(auth.router)
app.include_router(share.router)
app.include_router(clients.router)
app.include_router(metrics.router)
app.include_router(recommendation.router)
app.include_router(overrides.router)
app.include_router(calibration.router)
app.include_router(thresholds.router)
app.include_router(planning.router)
app.include_router(pdf.router)
app.include_router(ask.router)
app.include_router(roster.router)


# ─── Static frontend mount ───────────────────────────────────────────
#
# When the Next.js export exists at ``web/out/``, serve it at ``/``
# under this same FastAPI process. Local-first deployment, one URL,
# no CORS round-trip. In dev (no static export) the Next.js dev server
# runs on its own port and hits ``/api`` here via CORS.

_STATIC_ROOT = Path(__file__).resolve().parents[2] / "web" / "out"
if _STATIC_ROOT.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_ROOT), html=True), name="web")
