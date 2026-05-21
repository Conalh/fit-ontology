# FitOntology

**A client intelligence layer for personal trainers.** Three messy data sources — wearables, trainer intake, and exercise-science guidelines — unified into one queryable ontology, with an explainable rules-based reasoning layer that produces a weekly training recommendation and the full data trail behind it.

```
wearables (Strava, Whoop)  ─┐
trainer intake (CSV)        ├──► ontology (DuckDB) ──► reasoning ──► dashboard
ACSM reference guidelines  ─┘
```

## Why this exists

A working personal trainer has three sources of information about a client and no good way to look at them together: the client's wearable spits out HRV and sleep, the trainer keeps session notes in a spreadsheet, and the ACSM guidelines live in a textbook. The decisions a trainer makes every week — *do we push this week or pull back?* — depend on integrating all three.

FitOntology models the integration explicitly. Every recommendation traces back to the exact metric rows that produced it. No black boxes.

## Run it

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

Rules-based, not ML. For a one-person practice, **explainable beats clever**.

```
HRV last week vs prior week         ── drop >10% ────► flag: autonomic stress
Mean sleep last week                ── below 7h ─────► flag: recovery deficit
Mean RPE last week vs prior week    ── +1 or more ──► flag: undertrained recovery

2+ flags  → deload (-15% load)
1 flag    → conservative progression (~5%)
0 flags   → standard progression (5-10%) per ACSM guidance
```

Thresholds in [`src/fit_ontology/reasoning.py`](src/fit_ontology/reasoning.py). References:
- ACSM Guidelines for Exercise Testing and Prescription, 11th ed.
- Buchheit M. (2014), "Monitoring training status with HR measures."

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

v0.1. The reasoning rules are deliberately conservative and few — the value proposition is the modeling, not the cleverness of the heuristics. Future work: bring more ACSM guidance into the rules table, add an audit log of trainer overrides (so the system can learn from disagreement), and ship a CLI version of the dashboard for headless deployment.

## License

MIT.
