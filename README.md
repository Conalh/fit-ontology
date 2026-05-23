# FitOntology

**A client intelligence layer for personal trainers.** Three messy data sources — wearables, trainer intake, and exercise-science guidelines — unified into one queryable ontology, with an explainable rules-based reasoning layer that produces a weekly training recommendation and the full data trail behind it.

```
wearables (Garmin / Apple Health / Strava / Whoop)  ─┐
trainer intake (CSV)                                  ├─► ontology (DuckDB) ─► reasoning ─► dashboard
ACSM reference guidelines                            ─┘                                  └─► PDF
```

Ships as a Next.js + Tailwind dashboard backed by a FastAPI service over a single DuckDB file. One command boots both: `fit-ontology-serve`.

## Why this exists

A working personal trainer has three sources of information about a client and no good way to look at them together: the client's wearable spits out HRV and sleep, the trainer keeps session notes in a spreadsheet, and the ACSM guidelines live in a textbook. The decisions a trainer makes every week — *do we push this week or pull back?* — depend on integrating all three.

FitOntology models the integration explicitly. Every recommendation traces back to the exact metric rows that produced it. No black boxes.

## Run it

### With synthetic data (no account needed)

```bash
pip install -e .
python scripts/generate_synthetic.py    # writes data/synthetic/
python scripts/build_db.py              # builds data/fit_ontology.duckdb

# Build the frontend bundle (one-time; rebuild after frontend edits)
npm install --prefix web
npm run build --prefix web              # writes web/out/

fit-ontology-serve                      # serves UI + API on :8000
```

Open http://localhost:8000. Three synthetic clients are seeded:
- **Alice** — clean recovery → standard progression
- **Ben** — HRV dropping + low sleep → deload
- **Carla** — rising RPE only → conservative progression

### With your real Garmin Connect data

```bash
pip install -e .
cp .env.example .env
# Edit .env with your GARMIN_EMAIL and GARMIN_PASSWORD
python scripts/sync_garmin.py
fit-ontology-serve
```

Pulls 14 days of HRV Status, sleep, resting HR, Body Battery, stress, and
Training Readiness from Garmin Connect into the ontology. The script
handles 2FA via a one-time prompt and caches the session token in
`~/.garminconnect/`. Uses the unofficial `python-garminconnect` library
— personal-use only, not for a hosted product.

### Ask FitOntology (conversational layer)

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
fit-ontology-serve
# Open http://localhost:8000/ask
```

Natural-language questions answered by Claude with structured tool use
against the same ontology the dashboard reads from. Ask things like
*"what should I do with Ben this week?"* or *"who needs a deload?"* —
the assistant calls `list_clients`, `get_recent_metrics`,
`compute_recommendation`, `get_recent_overrides`, etc., and every tool
invocation is shown inline so the trainer can see what data drove the
answer.

Defaults to `claude-haiku-4-5-20251001` for speed and cost; override
via `FITONTOLOGY_MODEL=claude-opus-4-7` for harder questions. The
system prompt is cached via `cache_control: ephemeral`, so repeat
questions in a session hit the prompt cache.

### Development mode (two-process hot reload)

```bash
fit-ontology-serve --reload                   # FastAPI on :8000
npm run dev --prefix web                      # Next.js dev on :3000
```

Open http://localhost:3000. The Next.js dev server proxies API calls to
the FastAPI on :8000 via `NEXT_PUBLIC_API_URL` (set in
[`web/.env.local`](web/.env.local.example)) with CORS enabled.

## The ontology

Four entities, in [`src/fit_ontology/ontology.py`](src/fit_ontology/ontology.py):

| Entity | What it is | Cadence |
| --- | --- | --- |
| `Client` | Slow-changing intake facts: goals, injuries, anthropometrics | Per-intake |
| `Session` | The trainer's first-party record: what the client actually did | Per-session |
| `Metric` | Long-format wearable signals: HRV, HR, sleep, body composition | Daily |
| `Recommendation` | Reasoning output with full source-data trail | Per-week |
| `RecommendationOverride` | Trainer's accept / edit / reject of a recommendation | Per-decision |

**Modeling choices worth flagging:**

- `Metric` is long-format keyed by `(client_id, date, kind, source)`. Sources differ in coverage and cadence; long format makes adding a new wearable a single adapter function, not a schema migration.
- Metric IDs are SHA-1 hashes of the natural key, so re-syncs upsert instead of duplicating.
- `Recommendation` carries `source_metric_ids` — every output is auditable back to the exact rows that drove it. This is the single most important property of the system. A trainer who can't see *why* a recommendation was made cannot override it intelligently.
- `RecommendationOverride` snapshots the system's recommendation text at the moment of override (rather than FK-ing the recommendation id), so the audit trail survives recomputed recommendations as new wearable data lands.
- Pydantic for validation at ingestion boundaries; DuckDB for storage. Single-file, fast, SQL-compatible, deploys anywhere.

## The reasoning layer

Rules-based, not ML. For a one-person practice, **explainable beats clever**. Six literature-backed signals graded mild / moderate / severe, then weighted into a single recommendation.

```
HRV vs 28d baseline    ── ≥1 SD below baseline ────────► autonomic stress
                           (Plews & Laursen 2017)
ACWR (acute:chronic)   ── >1.3 / >1.5 / >1.8 from sRPE ─► high training load
                           (Gabbett 2016, "training-injury paradox")
Resting HR drift       ── 5+ bpm above 28d baseline ───► autonomic stress
                           (Buchheit 2014)
Sleep deficit          ── <7h mean / <6h floor / score <70 → recovery deficit
                           (ACSM 11e general adult guideline)
Session RPE drift      ── rising mean RPE at constant load → undertrained
Training Readiness     ── Garmin composite <60/45/30 over 7d
                           (corroborator — overlaps HRV/sleep/stress)

1 severe   OR  2+ moderate    → deload (-20% load)
1 moderate OR  2+ mild        → conservative progression (~5%)
0 signals                     → standard progression (5–10% per ACSM 11e)
```

Every signal includes its summary, severity, and the source IDs that fed it (metric IDs for the wearable-based signals, session IDs for ACWR and RPE drift). Every recommendation traces back to those IDs.

Thresholds and references live in [`src/fit_ontology/reasoning.py`](src/fit_ontology/reasoning.py):
- ACSM Guidelines for Exercise Testing and Prescription, 11th ed. (progression magnitudes; sleep floor)
- Plews & Laursen (2017), *International Journal of Sports Physiology and Performance* — HRV vs rolling baseline in SD units
- Gabbett (2016), *British Journal of Sports Medicine* — ACWR sweet spot and danger zones from session-RPE × duration
- Buchheit (2014), *Frontiers in Physiology* — HR-based training-status monitoring
- Foster et al. (2001) — session-RPE method for internal training load quantification

## The dashboard

Four screens, all sharing the same chrome:

- **`/`** — Roster: every client ranked by recommendation urgency. Click through to detail.
- **`/clients/?id=…`** — Client detail: the recommendation card, confidence + agreement donuts, six-cell trends grid with 28d baseline ribbons, ACWR + load bars, recent sessions, decision history, the override drawer, and a "Send to client" card that exports a one-page PDF with an optional coach's note.
- **`/clients/upload?id=…`** — Drop a wearable export (Apple Health zip/xml, Strava CSV, Whoop JSON); format detected server-side.
- **`/calibration`** — System-vs-trainer agreement matrix across every override, plus the qualitative trail.
- **`/ask`** — Conversational layer powered by Claude with structured tool use against the ontology.

Per-client accent: each client has an accent color (12-swatch palette, trainer-editable via the avatar in the client header) that persists in `localStorage` and threads through the recommendation card, ribbons, and surface accents.

## Adding a new data source

Write one function. Add a row to `MetricSource`. That's the whole change.

The Apple Health Export adapter is the worked example: 80 lines in
[`src/fit_ontology/ingest.py`](src/fit_ontology/ingest.py)
parse iOS's `export.zip` into the canonical long-format schema, and a
single one-line fall-through in
[`src/fit_ontology/reasoning.py`](src/fit_ontology/reasoning.py)
lets the HRV detector use Apple's SDNN when Garmin's RMSSD isn't
available. No schema migration, no dashboard changes, no test churn
outside the adapter's own suite.

```bash
# On the iPhone: Health → profile → Export All Health Data → export.zip
python scripts/import_apple_health.py path/to/export.zip --client-id c_me
# Or: open the dashboard, navigate to a client, click "Upload"
```

## Tests

```bash
pip install -e .[dev]
pytest -q
```

51 tests across the reasoning branches against synthetic fixtures, the
override log roundtrip, the assistant tool routing, the Apple Health
parser, the deterministic metric-ID dedup, and every FastAPI route. CI
runs the same suite on Python 3.11 and 3.12 for every push and PR
([`.github/workflows/tests.yml`](.github/workflows/tests.yml)).

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Next.js (App Router, Tailwind v4, TanStack Query)                  │
│  Static export served from FastAPI for prod;                        │
│  npm run dev on :3000 for hot reload during development             │
│                                                                     │
│  /  /clients  /calibration  /ask  /clients/upload                   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ /api/*  (CORS in dev, same-origin in prod)
┌──────────────────────────────▼──────────────────────────────────────┐
│  FastAPI  (src/fit_ontology/api.py)                                 │
│  - /api/clients/*  metrics, sessions, recommendation, overrides     │
│  - /api/roster  /api/calibration  /api/ask  /api/clients/:id/pdf    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  fit_ontology  (pure Python, importable from notebooks / scripts)   │
│  ontology · ingest · reasoning · report · garmin · assistant · db   │
│                       └─── DuckDB (single file) ────┘                │
└─────────────────────────────────────────────────────────────────────┘
```

## Status

v0.4. The reasoning rules are deliberately conservative and few — the value proposition is the modeling, not the cleverness of the heuristics. The full dashboard now ships as Next.js + Tailwind backed by a typed FastAPI surface, served from a single process. Live: per-client roster triage, detail page with baseline-ribbon charts and the override drawer, client-facing PDF export with a coach's note, calibration matrix, conversational layer, and in-browser wearable ingestion. Live adapters: Garmin Connect (real sync), Apple Health Export, Strava bulk export, Whoop daily-record JSON. Future work: stage-level Apple sleep aggregation, per-client reasoning thresholds, more ACSM guidance in the rules table.

## License

MIT.
