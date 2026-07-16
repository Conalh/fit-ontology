"""Regenerate the README screenshots.

Drives a real browser through the live dev loop and saves four
PNGs into ``docs/screenshots/``. Reviewers run this once after
any UI change so the README's screenshot table doesn't drift.

Requirements:
    pip install playwright
    playwright install chromium

Setup:
    Start the dev loop in two other terminals before running:
        $ python scripts/preview_serve.py
        $ npm run dev --prefix web

    The preview_serve script auto-seeds the synthetic dataset
    under FIT_ONTOLOGY_DEMO_MODE=1 — no manual login needed.

Run:
    python docs/screenshots/capture.py

Output:
    docs/screenshots/roster.png
    docs/screenshots/client-detail.png
    docs/screenshots/calibration.png
    docs/screenshots/intake.png

The viewport is 1440x900 (laptop default). PNGs are non-retina;
this is the README target where size matters more than fidelity.

The intake shot needs an extra setup step — the public form lives
behind a one-shot token, so we log in as the default trainer +
mint a token before navigating. Falls back gracefully if the
deploy target is demo-mode (mint route is forbid_demo_trainer, so
the capture skips and the previous intake.png is preserved).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright

# Override via FITONTOLOGY_SCREENSHOT_URL — useful for capturing
# against the deployed Fly instance when the local dev port is
# occupied by another project.
WEB = os.environ.get("FITONTOLOGY_SCREENSHOT_URL", "http://127.0.0.1:3000").rstrip("/")
# Where the JSON API actually lives. In dev the Next server is on
# :3000 and FastAPI is on :8000; in production deploys both share
# origin so this collapses to WEB. Override via the env var when
# pointing at a non-standard layout (e.g. a remote test instance).
API = os.environ.get(
    "FITONTOLOGY_SCREENSHOT_API_URL",
    "http://127.0.0.1:8000" if WEB.startswith("http://127.0.0.1") or WEB.startswith("http://localhost") else WEB,
).rstrip("/")
# Default-trainer credentials used by the preview_serve.py launcher.
# Match scripts/preview_serve.py:FIT_ONTOLOGY_DEFAULT_TRAINER_PASSWORD.
PREVIEW_EMAIL = os.environ.get("FITONTOLOGY_SCREENSHOT_EMAIL", "conal.hg@gmail.com")
PREVIEW_PASSWORD = os.environ.get("FITONTOLOGY_SCREENSHOT_PASSWORD", "preview-pass-1234")
BROWSER_PATH = os.environ.get("FITONTOLOGY_SCREENSHOT_BROWSER_PATH")
HERE = Path(__file__).resolve().parent

SHOTS = [
    # (path, output filename, optional pre-shot wait selector)
    ("/", "roster.png", ".fit-sidebar"),
    ("/clients?id=c_ben", "client-detail.png", "[data-recommendation-card]"),
    ("/calibration", "calibration.png", "h1"),
]


async def _mint_intake_token(page) -> str | None:
    """Log in as the default trainer and mint a one-shot intake
    token. Returns the token, or None if the deploy refuses (demo
    mode, missing credentials, etc.) — in which case the caller
    skips the intake shot and leaves the previous PNG in place."""
    login = await page.request.post(
        f"{API}/api/auth/login",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD}),
    )
    if login.status != 200:
        print(f"  login skipped ({login.status}); intake.png not refreshed")
        return None
    mint = await page.request.post(
        f"{API}/api/clients/intake/mint",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"trainer_message": "Fill this in before our first session"}),
    )
    if mint.status != 200:
        print(f"  intake mint skipped ({mint.status}); intake.png not refreshed")
        return None
    return (await mint.json())["token"]


async def main() -> int:
    HERE.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        launch_options = {"executable_path": BROWSER_PATH} if BROWSER_PATH else {}
        browser = await p.chromium.launch(**launch_options)
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1,
        )
        page = await ctx.new_page()
        for path, name, wait_for in SHOTS:
            url = f"{WEB}{path}"
            print(f"capturing {url} -> {name}")
            await page.goto(url, wait_until="networkidle")
            # The wait_for selector is the "actual content has
            # rendered" signal — networkidle alone fires before
            # TanStack Query's first data fetch resolves.
            # A missing selector intentionally documents the empty state.
            with contextlib.suppress(Exception):
                await page.wait_for_selector(wait_for, timeout=8000)
            # One extra frame so any draw-in animations settle.
            await page.wait_for_timeout(400)
            await page.screenshot(path=str(HERE / name), full_page=False)

        # Intake form — needs a fresh token. Logged in via the
        # request context above; the cookie flows into page.goto.
        token = await _mint_intake_token(page)
        if token:
            url = f"{WEB}/intake?t={token}"
            name = "intake.png"
            print(f"capturing {url} -> {name}")
            await page.goto(url, wait_until="networkidle")
            with contextlib.suppress(Exception):
                await page.wait_for_selector("form", timeout=8000)
            await page.wait_for_timeout(400)
            await page.screenshot(path=str(HERE / name), full_page=False)

        await browser.close()
    print(f"wrote screenshots to {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
