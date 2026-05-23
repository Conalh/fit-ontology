# FitOntology

**A client intelligence layer for personal trainers.** Three messy data sources — wearables, trainer intake, and exercise-science guidelines — unified into one queryable ontology, with an explainable rules-based reasoning layer that produces a weekly training recommendation and the full data trail behind it.

```
wearables (Garmin, Strava, Whoop)  ─┐
trainer intake (CSV)                 ├──► ontology (DuckDB) ──► reasoning ──► dashboard
ACSM reference guidelines           ─┘
```

Ships as a Streamlit dashboard.

## Why this exists

A working personal trainer has three sources of information about a client and no good way to look at them together: the client's wearable spits out HRV and sleep, the trainer keeps session notes in a spreadsheet, and the ACSM guidelines live in a textbook. The decisions a trainer makes every week — *do we push this week or pull back?* — depend on integrating all three.

FitOntology models the integration explicitly. Every recommendation traces back to the exact metric rows that produced it. No black boxes.

## Run it

### With synthetic data (no account needed)

```bash
pip install -r requirements.txt
python scripts/generate_synthetic.py    # writes data/synthetic/
python scripts/build_db.py              # builds data/fit_ontology.duckdb
streamlit run app.py
```

Three synthetic clients are seeded to exercise different reasoning branches:
- **Alice** — clean recovery → standard progression
- **Ben** — HRV dropping + low sleep → deload
- **Carla** — rising RPE only → conservative progression

### With your real Garmin Connect data

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your GARMIN_EMAIL and GARMIN_PASSWORD
python scripts/sync_garmin.py
streamlit run app.py
```

Pulls 14 days of HRV Status, sleep, resting HR, Body Battery, stress, and
Training Readiness from Garmin Connect into the ontology. The script
handles 2FA via a one-time prompt and caches the session token in
`~/.garminconnect/`. Uses the unofficial `python-garminconnect` library
— personal-use only, not for a hosted product.

### Ask FitOntology (conversational layer)

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
streamlit run app.py
# Open the "Ask FitOntology" page in the sidebar.
```

Natural-language questions answered by Claude with structured tool use
against the same ontology the dashboard reads from. Ask things like
*"what should I do with Ben this week?"* or *"who needs a deload?"* —
the assistant calls `list_clients`, `get_recent_metrics`,
`compute_recommendation`, etc., and every tool invocation is shown
inline so the trainer can see what data drove the answer.

Defaults to `claude-haiku-4-5-20251001` for speed and cost; the
sidebar lets you swap to `claude-opus-4-7` for harder questions. The
system prompt is cached via `cache_control: ephemeral`, so repeat
questions in a session hit the prompt cache.

## The ontology

Four entities, in [`src/fit_ontology/ontology.py`](src/fit_ontology/ontology.py):

| Entity | What it is | Cadence |
| --- | --- | --- |
| `Client` | Slow-changing intake facts: goals, injuries, anthropometrics | Per-intake |
| `Session` | The trainer's first-party record: what the client actually did | Per-session |
| `Metric` | Long-format wearable signals: HRV, HR, sleep, body composition | Daily |
| `Recommendation` | Reasoning output with full source-data trail | Per-week |

**Modeling choices worth flagging:**

- `Metric` is long-format keyed by `(client_id, date, kind, source)`. Sources differ in coverage and cadence; long format makes adding a new wearable a single adapter function, not a schema migration.
- `Recommendation` carries `source_metric_ids` — every output is auditable back to the exact rows that drove it. This is the single most important property of the system. A trainer who can't see *why* a recommendation was made cannot override it intelligently.
- Pydantic for validation at ingestion boundaries; DuckDB for storage. Single-file, fast, SQL-compatible, deploys anywhere.

## The reasoning layer

Rules-based, not ML. For a one-person practice, **explainable beats clever**. Five literature-backed signals graded mild / moderate / severe, then weighted into a single recommendation.

```
HRV vs 28d baseline   ── ≥1 SD below baseline ───────► autonomic stress
                          (Plews & Laursen 2017)
ACWR (acute:chronic)  ── >1.3 / >1.5 / >1.8 from sRPE → high training load
                          (Gabbett 2016, "training-injury paradox")
Resting HR drift      ── 5+ bpm above 28d baseline ──► autonomic stress
                          (Buchheit 2014)
Sleep deficit         ── <7h mean / <6h floor / score <70 → recovery deficit
                          (ACSM 11e general adult guideline)
Session RPE drift     ── rising mean RPE at constant load → undertrained

1 severe   OR  2+ moderate    → deload (-20% load)
1 moderate OR  2+ mild        → conservative progression (~5%)
0 signals                     → standard progression (5–10% per ACSM 11e)
```

Every signal includes its summary, severity, and the source-metric IDs that fed it; every recommendation traces back to those IDs so a trainer can audit and override.

Thresholds and references live in [`src/fit_ontology/reasoning.py`](src/fit_ontology/reasoning.py):
- ACSM Guidelines for Exercise Testing and Prescription, 11th ed. (progression magnitudes; sleep floor)
- Plews & Laursen (2017), *International Journal of Sports Physiology and Performance* — HRV vs rolling baseline in SD units
- Gabbett (2016), *British Journal of Sports Medicine* — ACWR sweet spot and danger zones from session-RPE × duration
- Buchheit (2014), *Frontiers in Physiology* — HR-based training-status monitoring
- Foster et al. (2001) — session-RPE method for internal training load quantification

## Adding a new data source

Write one function. Add a row to `MetricSource`. That's the whole change.

```python
def from_garmin_export(path, client_id):
    # parse vendor format, yield rows in the long-format schema
    return df  # columns: id, client_id, date, source, kind, value, unit
```

No downstream code changes. No schema migration. That's the point of the ontology.

## Tests

```bash
pytest tests/
```

Smoke tests cover the three reasoning branches against synthetic fixtures.

## Status

v0.2. The reasoning rules are deliberately conservative and few — the value proposition is the modeling, not the cleverness of the heuristics. The roster, override log, calibration view, and weekly client-facing PDF export are live: every recommendation can be marked accepted / edited / rejected with a note, the calibration page rolls those decisions into a system-vs-trainer agreement matrix, and the PDF export produces a jargon-free one-pager the trainer can send to the client. Future work: bring more ACSM guidance into the rules table, add a second wearable adapter, and ship a CLI version of the dashboard for headless deployment.

## License

MIT.
