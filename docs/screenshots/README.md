# Screenshots

This directory holds the dashboard screenshots referenced in the
top-level [README](../../README.md).

To (re)generate them after a UI change:

```bash
pip install playwright
playwright install chromium

# Start the dev loop in two other terminals:
python scripts/preview_serve.py        # FastAPI on :8000
npm run dev --prefix web               # Next.js on :3000

# Then capture:
python docs/screenshots/capture.py
```

The script drives a headless Chromium at 1440×900, loads three
pages (`/`, `/clients?id=c_ben`, `/calibration`), waits for content
+ a render frame, and writes:

- `roster.png` — Monday-morning triage view
- `client-detail.png` — Ben's recovery + plan + override drawer
- `calibration.png` — system-vs-trainer agreement + adherence

If a screenshot doesn't refresh: confirm the dev server is
serving the synthetic demo data (`FIT_ONTOLOGY_DEMO_MODE=1` in the
preview-serve env). Empty-state screenshots are still useful — the
capture script falls through on a missing selector rather than
erroring.
