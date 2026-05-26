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

The script drives a headless Chromium at 1440×900, loads four
pages (`/`, `/clients?id=c_ben`, `/calibration`, and a freshly
minted `/intake?t=<token>`), waits for content + a render frame,
and writes:

- `roster.png` — Monday-morning triage view
- `client-detail.png` — Ben's recovery + plan + override drawer
- `calibration.png` — system-vs-trainer agreement + adherence
- `intake.png` — public intake form (Phase 3b)

The intake shot needs a small extra step: it POSTs to
`/api/auth/login` + `/api/clients/intake/mint` to obtain a fresh
one-shot token before navigating to `/intake?t=<token>`. The
credentials default to the `preview_serve.py` bootstrap (override
via `FITONTOLOGY_SCREENSHOT_EMAIL` / `_PASSWORD`). The API URL
defaults to `http://127.0.0.1:8000` when the web URL is localhost;
override via `FITONTOLOGY_SCREENSHOT_API_URL` if running against a
non-standard deploy layout. If login or mint refuses (demo-mode
deploy, missing credentials), the script logs a skipped-line and
leaves the previous `intake.png` in place rather than erroring.

If a screenshot doesn't refresh: confirm the dev server is
serving the synthetic demo data (`FIT_ONTOLOGY_DEMO_MODE=1` in the
preview-serve env). Empty-state screenshots are still useful — the
capture script falls through on a missing selector rather than
erroring.
