"""Regenerate the README screenshots.

Drives a real browser through the live dev loop and saves three
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

The viewport is 1440x900 (laptop default). PNGs are non-retina;
this is the README target where size matters more than fidelity.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright


# Override via FITONTOLOGY_SCREENSHOT_URL — useful for capturing
# against the deployed Fly instance when the local dev port is
# occupied by another project.
WEB = os.environ.get("FITONTOLOGY_SCREENSHOT_URL", "http://127.0.0.1:3000").rstrip("/")
HERE = Path(__file__).resolve().parent

SHOTS = [
    # (path, output filename, optional pre-shot wait selector)
    ("/", "roster.png", ".fit-sidebar"),
    ("/clients?id=c_ben", "client-detail.png", "[data-recommendation-card]"),
    ("/calibration", "calibration.png", "h1"),
]


async def main() -> int:
    HERE.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
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
            try:
                await page.wait_for_selector(wait_for, timeout=8000)
            except Exception:
                # Selector not found — render anyway, the screenshot
                # documents the empty state which is also useful.
                pass
            # One extra frame so any draw-in animations settle.
            await page.wait_for_timeout(400)
            await page.screenshot(path=str(HERE / name), full_page=False)
        await browser.close()
    print(f"wrote {len(SHOTS)} screenshots to {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
