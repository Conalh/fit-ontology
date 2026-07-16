# Contributing

FitOntology welcomes focused fixes, evidence improvements, import adapters, and workflow refinements.

## Set up

Use Python 3.12+ and Node.js 24+.

```bash
python -m pip install -e ".[dev]"
npm ci --prefix web
```

## Verify a change

```bash
ruff check src scripts tests
mypy --python-version 3.12
pytest

npm run lint --prefix web
npm run test:run --prefix web
npm run build --prefix web
```

Keep health and training language conservative. A change must not imply diagnosis, treatment, injury prediction, or automatic clearance. New reasoning signals need a citation, an explicit threshold, source-row traceability, and tests for both firing and non-firing cases.

Please use GitHub issues for ordinary bugs and feature proposals. Use private vulnerability reporting for security findings.
