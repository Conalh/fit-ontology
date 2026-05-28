# syntax=docker/dockerfile:1.7

# Multi-stage build:
#   1. node-builder: builds the Next.js static export into /web/out
#   2. runtime:      installs Python deps + copies the static export
#                    + runs uvicorn behind a non-root user
#
# Image size target: ~250MB. Python 3.12-slim + the FastAPI/DuckDB/
# pandas/anthropic deps are the bulk. The node stage is throwaway.

# ─── Stage 1: Build the Next.js static export ────────────────────────
FROM node:22-bookworm-slim AS node-builder

WORKDIR /web

# Copy package manifests first so dependency installs cache across
# source-only rebuilds.
COPY web/package.json web/package-lock.json* ./
RUN npm ci --prefer-offline --no-audit --no-fund

# Then the rest of the front-end source.
COPY web/ ./

# next.config.ts already sets output: "export" so this writes the
# bundle to /web/out/.
RUN npm run build

# ─── Stage 2: Runtime image ──────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

# Install runtime OS packages — only what duckdb/pandas/reportlab
# need at import-time. No build toolchain in the final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. Created before WORKDIR so the directory is owned
# by the right user from the start.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 app
WORKDIR /app
RUN chown app:app /app

# Python deps install as root (writable site-packages), runtime
# switches to ``app``. We install the project in editable-equivalent
# mode (``pip install .``) so the entry-point script lands on PATH.
COPY --chown=app:app pyproject.toml README.md ./
COPY --chown=app:app src/ ./src/

# Two-step install: deps first (cached), then the project itself.
# The intermediate pip wheel cache stays warm across source-only
# rebuilds without bloating the final layer.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# Copy the static export from the node stage. The path
# ``/app/web/out`` matches what fit_ontology/api.py expects when it
# computes _STATIC_ROOT — same anchoring as the local dev loop.
COPY --from=node-builder --chown=app:app /web/out ./web/out

# Synthetic data ships with the image so demo mode can seed on
# first boot without an extra build step. ~150KB; negligible.
COPY --chown=app:app data/synthetic ./data/synthetic

# Data directory for the production DuckDB file. Fly mounts the
# persistent volume here; without a mount we still create the dir
# so a non-volume run doesn't crash on first connect().
RUN mkdir -p /data && chown app:app /data

# Switch to the non-root user. Everything below runs as app:10001.
USER app

# DuckDB file lives on the persistent volume; the FastAPI process
# reads this env var to anchor its path.
#
# FIT_ONTOLOGY_STATIC_ROOT overrides api.py's __file__-relative
# calculation, which would otherwise resolve to a site-packages path
# in the non-editable install used here (Docker copies the package
# into site-packages via ``pip install .``, so ``__file__.parents[2]``
# lands at /usr/local/lib/python3.12, not /app).
ENV FIT_ONTOLOGY_DB=/data/fit.duckdb \
    FIT_ONTOLOGY_STATIC_ROOT=/app/web/out \
    FIT_ONTOLOGY_SYNTHETIC_DATA_ROOT=/app/data/synthetic \
    FIT_ONTOLOGY_PRODUCTION=1 \
    FIT_ONTOLOGY_REQUIRE_AUTH=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

# Health check matches /api/health (returns {"ok": true} fast). Fly
# also reads this through fly.toml's [[services.http_checks]] block.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; \
        r = urllib.request.urlopen(f'http://127.0.0.1:{__import__(\"os\").environ.get(\"PORT\", \"8000\")}/api/health', timeout=2); \
        sys.exit(0 if r.status == 200 else 1)"

# uvicorn directly rather than ``fit-ontology-serve`` so we can pass
# --host 0.0.0.0 (the console script defaults to 127.0.0.1, which
# Fly's edge proxy can't reach across the container boundary).
CMD ["sh", "-c", "uvicorn fit_ontology.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
