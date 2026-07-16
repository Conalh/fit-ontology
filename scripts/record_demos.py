"""Record short demo videos of FitOntology flows.

Sister script to ``docs/screenshots/capture.py``. That one writes
single-frame PNGs for the README; this one writes ~10-30 second
.webm clips for richer demos (portfolio, social, walkthrough).

Requirements:
    pip install playwright
    playwright install chromium

Setup:
    Two terminals already running the dev loop:
        $ python scripts/preview_serve.py   # FastAPI on :8000
        $ npm run dev --prefix web          # Next.js on :3000

    Login credentials default to the preview_serve.py bootstrap
    (conal.hg@gmail.com / preview-pass-1234); override via env.

Run:
    python scripts/record_demos.py
    # or one flow:
    python scripts/record_demos.py intake

Output:
    docs/videos/intake-flow.webm        end-to-end mint+submit loop
    docs/videos/<future flows...>

The viewport is 1280x800 (compact laptop) so the video file is
small enough to attach to a PR / Slack thread. Each flow opens
its own Playwright context with ``record_video_dir`` so each clip
gets its own file; closing the context finalizes the .webm.

slow_mo: 60ms between actions makes the clip watchable without
feeling slow. The form-fill step gets explicit waits between
fields so the viewer can see what was typed.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path

from playwright.async_api import BrowserContext, async_playwright

WEB = os.environ.get("FITONTOLOGY_DEMO_URL", "http://127.0.0.1:3000").rstrip("/")
API = os.environ.get(
    "FITONTOLOGY_DEMO_API_URL",
    "http://127.0.0.1:8000"
    if WEB.startswith("http://127.0.0.1") or WEB.startswith("http://localhost")
    else WEB,
).rstrip("/")
EMAIL = os.environ.get("FITONTOLOGY_DEMO_EMAIL", "conal.hg@gmail.com")
PASSWORD = os.environ.get("FITONTOLOGY_DEMO_PASSWORD", "preview-pass-1234")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "videos"
VIEWPORT = {"width": 1280, "height": 800}


async def _new_context(browser, *, name: str, raw_dir: Path) -> BrowserContext:
    """Fresh context per flow so each clip writes its own .webm and
    cookies don't bleed between flows."""
    ctx = await browser.new_context(
        viewport=VIEWPORT,
        device_scale_factor=1,
        record_video_dir=str(raw_dir / name),
        record_video_size=VIEWPORT,
    )
    return ctx


async def _finalize_video(ctx: BrowserContext, page, target: Path) -> None:
    """Save a flow's recording to a human-readable filename.

    Playwright only writes the video file when the context closes —
    calling ``video.save_as()`` BEFORE close deadlocks (save_as
    blocks waiting for a file that close() would produce). So we
    close first, then move via save_as which is valid post-close
    (playwright keeps the path reference around)."""
    video = page.video
    await ctx.close()
    if video is not None:
        await video.save_as(str(target))


# ─── Flow: intake end-to-end ─────────────────────────────────────────

async def record_intake_flow(browser, raw_dir: Path) -> Path | None:
    """Trainer logs in → opens roster → clicks Send intake link →
    mints a token → copies the URL. A second context (no cookie)
    opens the URL, fills the form, submits, sees the confirmation.
    Then the first context's roster is refreshed showing the new
    client landed.

    Two contexts so the prospective-client side is genuinely cookie-
    less, the way a real client opening a shared link would be."""
    name = "intake-flow"
    target = OUT_DIR / f"{name}.webm"

    trainer_ctx = await _new_context(browser, name=name, raw_dir=raw_dir)
    trainer = await trainer_ctx.new_page()

    # Login out-of-band via the API context so the session cookie is
    # set before any page navigation — sidesteps SPA form-submit
    # timing entirely (which was flaky in earlier captures). The
    # trainer page then opens straight to the roster, with the
    # cookie already in place.
    login = await trainer_ctx.request.post(
        f"{API}/api/auth/login",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"email": EMAIL, "password": PASSWORD}),
    )
    assert login.status == 200, f"login failed: {login.status} {await login.text()}"
    await trainer.goto(f"{WEB}/", wait_until="domcontentloaded")
    await trainer.wait_for_selector("button:has-text(\"Send intake link\")", timeout=10000)
    await trainer.wait_for_timeout(1200)

    # Open the intake modal
    await trainer.get_by_role("button", name="Send intake link").click()
    await trainer.wait_for_selector("[role=dialog] textarea", timeout=4000)
    await trainer.wait_for_timeout(800)

    # Type a welcome note slowly so the viewer can read it as it lands
    msg = "Fill this in before our first session — Coach"
    await trainer.locator("[role=dialog] textarea").press_sequentially(msg, delay=22)
    await trainer.wait_for_timeout(700)

    # Mint
    await trainer.get_by_role("button", name="Mint link").click()
    await trainer.wait_for_selector("[role=dialog] input[readonly]", timeout=4000)
    await trainer.wait_for_timeout(1400)

    # Grab the URL value
    url = await trainer.locator("[role=dialog] input[readonly]").input_value()
    print(f"  minted: {url[:70]}…")

    # Highlight Copy briefly (visual cue)
    await trainer.get_by_role("button", name="Copy link").click()
    await trainer.wait_for_timeout(900)

    # Now switch to the prospective-client side — fresh context, no cookies
    client_ctx = await _new_context(browser, name=f"{name}-client", raw_dir=raw_dir)
    client = await client_ctx.new_page()
    await client.goto(url, wait_until="domcontentloaded")
    await client.wait_for_selector("form", timeout=8000)
    await client.wait_for_timeout(1100)

    # Fill the form
    await client.locator("input[placeholder='e.g. Ben Okafor']").press_sequentially(
        "Sam Patel", delay=35
    )
    await client.select_option("select", "M")
    await client.wait_for_timeout(280)
    await client.locator("input[type=number]:not([placeholder])").fill("29")
    await client.wait_for_timeout(180)
    await client.locator("input[placeholder=ft]").fill("5")
    await client.wait_for_timeout(140)
    await client.locator("input[placeholder=in]").fill("9")
    await client.wait_for_timeout(180)
    await client.locator("input[placeholder=lb]").fill("162")
    await client.wait_for_timeout(280)
    await client.locator("input[placeholder='e.g. Sub-3:15 Chicago, Oct 11']").press_sequentially(
        "Build base for a 10k in April", delay=22
    )
    await client.wait_for_timeout(180)
    await client.locator("textarea").press_sequentially(
        "Nothing recent", delay=22
    )
    await client.wait_for_timeout(800)

    # Submit
    await client.get_by_role("button", name="Submit").click()
    await client.wait_for_selector("h1:has-text(\"Thanks\")", timeout=6000)
    await client.wait_for_timeout(2200)  # let the success state sit on screen

    # Back to the trainer — close the modal (if still open) then
    # refresh the roster to show the new client landing.
    await trainer.bring_to_front()
    try:
        await trainer.get_by_role("button", name="Done").click(timeout=1500)
        await trainer.wait_for_timeout(700)
    except Exception:
        pass
    await trainer.reload(wait_until="domcontentloaded")
    await trainer.wait_for_selector("h1", timeout=6000)
    await trainer.wait_for_selector("text=Sam Patel", timeout=6000)
    await trainer.wait_for_timeout(2500)  # let the viewer see "the row landed"

    # Finalize — close the context (which writes the .webm) then
    # rename. Order matters; see _finalize_video.
    companion = OUT_DIR / "intake-flow-client.webm"
    await _finalize_video(client_ctx, client, companion)
    await _finalize_video(trainer_ctx, trainer, target)
    return target


async def _login(ctx: BrowserContext) -> None:
    """Set the session cookie via API so subsequent page loads land
    already authenticated."""
    login = await ctx.request.post(
        f"{API}/api/auth/login",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"email": EMAIL, "password": PASSWORD}),
    )
    assert login.status == 200, f"login failed: {login.status} {await login.text()}"


# ─── Flow: roster overview ───────────────────────────────────────────

async def record_roster_overview(browser, raw_dir: Path) -> Path | None:
    """Monday-morning triage view. Trainer opens the roster; the three
    verdicts (Deload / Conservative / Standard) are visible with their
    coloured left-edge stripes and confidence percentages. Cursor
    hovers a row to show the row-hover affordance, then clicks the
    sort header to show the sort UI."""
    name = "roster-overview"
    target = OUT_DIR / f"{name}.webm"

    ctx = await _new_context(browser, name=name, raw_dir=raw_dir)
    page = await ctx.new_page()
    await _login(ctx)

    await page.goto(f"{WEB}/", wait_until="domcontentloaded")
    await page.wait_for_selector(".fit-roster-row", timeout=10000)
    await page.wait_for_timeout(1800)

    # Hover the top-urgency row (Marcus Hill — Deload) so its
    # row-hover affordance fires for the camera.
    first_row = page.locator(".fit-roster-row").first
    await first_row.hover()
    await page.wait_for_timeout(1200)

    # Click the Confidence column to demo sort behaviour
    await page.get_by_role("button", name="CONF").click()
    await page.wait_for_timeout(1600)
    await page.get_by_role("button", name="CONF").click()  # toggle direction
    await page.wait_for_timeout(1600)

    # Return to urgency sort + sit for a beat so the final frame is
    # the recognisable Monday view.
    await page.get_by_role("button", name="RECOMMENDATION").click()
    await page.wait_for_timeout(2000)

    await _finalize_video(ctx, page, target)
    return target


# ─── Flow: client detail with citation popover ───────────────────────

async def record_client_detail(browser, raw_dir: Path) -> Path | None:
    """Open Marcus Hill's detail page — the Deload client. Pause on
    the recommendation card, then hover one of the literature
    citation chips to show the popover with the source + DOI link.
    THE differentiator: every verdict traces back to peer-reviewed
    sport-science methodology."""
    name = "client-detail"
    target = OUT_DIR / f"{name}.webm"

    ctx = await _new_context(browser, name=name, raw_dir=raw_dir)
    page = await ctx.new_page()
    await _login(ctx)

    await page.goto(f"{WEB}/clients/?id=c_ben", wait_until="domcontentloaded")
    # Wait for the recommendation card's stable class anchor
    await page.wait_for_selector(".fit-rec-card", timeout=15000)
    await page.wait_for_timeout(2400)

    # Find a citation chip (the small literature pills on the rec card)
    # — the InfoPopover triggers carry aria-label="About citation: …".
    chip = page.locator("button[aria-label^='About citation']").first
    try:
        await chip.wait_for(timeout=4000)
        await chip.scroll_into_view_if_needed(timeout=2000)
        await page.wait_for_timeout(700)
        await chip.hover()
        await page.wait_for_timeout(2400)  # let the popover fully open + sit
        # Click for the persistent popover state
        await chip.click()
        await page.wait_for_timeout(2400)
    except Exception as e:
        print(f"  citation-chip interaction skipped: {e}")
        await page.wait_for_timeout(1500)

    await _finalize_video(ctx, page, target)
    return target


# ─── Flow: calibration page ──────────────────────────────────────────

async def record_calibration(browser, raw_dir: Path) -> Path | None:
    """The /calibration page — system-vs-trainer agreement matrix,
    weekly trend, per-client breakdown, adherence telemetry. The
    'explainable AI' story made visible: nine override pairs across
    three clients render as a real matrix with both axis bands
    populated."""
    name = "calibration"
    target = OUT_DIR / f"{name}.webm"

    ctx = await _new_context(browser, name=name, raw_dir=raw_dir)
    page = await ctx.new_page()
    await _login(ctx)

    await page.goto(f"{WEB}/calibration/", wait_until="domcontentloaded")
    await page.wait_for_selector("h1", timeout=10000)
    await page.wait_for_timeout(2500)

    # Scroll slowly down the page so the camera sees the matrix → the
    # weekly trend → the per-client breakdown → the adherence panel
    # in one continuous tour.
    for y in (300, 600, 900, 1200, 0):
        await page.evaluate(f"window.scrollTo({{top: {y}, behavior: 'smooth'}})")
        await page.wait_for_timeout(1400)

    await _finalize_video(ctx, page, target)
    return target


# ─── Flow: full product tour ─────────────────────────────────────────

async def record_full_tour(browser, raw_dir: Path) -> Path | None:
    """End-to-end walkthrough in one continuous take. Roster → add a
    new client through the UI → land on the empty detail (no-data
    banner) → back to roster → open a rich existing client (Captain
    Ahab, Deload) → scroll the whole detail page (recovery gauge,
    recommendation, citations, trends, sessions, decision history,
    thresholds) → peek at the override drawer → end on the roster.

    Single context so it's one .webm. Pacing is deliberately slow
    (slow_mo + explicit waits) — this is the "show somebody what
    FitOntology is" clip, not a flow test."""
    name = "full-tour"
    target = OUT_DIR / f"{name}.webm"

    ctx = await _new_context(browser, name=name, raw_dir=raw_dir)
    page = await ctx.new_page()
    await _login(ctx)

    # ── 1. Land on the roster ──
    await page.goto(f"{WEB}/", wait_until="domcontentloaded")
    await page.wait_for_selector(".fit-roster-row", timeout=10000)
    await page.wait_for_timeout(2400)  # let viewer take in Monday-morning view

    # Hover top-urgency row (Deload) so the row-hover affordance fires
    rows = page.locator(".fit-roster-row")
    await rows.first.hover()
    await page.wait_for_timeout(1200)
    # Drift the cursor down the list so the viewer's eye follows
    for i in range(1, min(await rows.count(), 4)):
        await rows.nth(i).hover()
        await page.wait_for_timeout(700)

    # Toggle Confidence sort, then back to urgency — quick "this is interactive" beat
    await page.get_by_role("button", name="CONF").click()
    await page.wait_for_timeout(1400)
    await page.get_by_role("button", name="RECOMMENDATION").click()
    await page.wait_for_timeout(1400)

    # ── 2. Add a new client through the UI ──
    await page.get_by_role("link", name="+ Add client").click()
    await page.wait_for_selector("input[placeholder='e.g. Ben Okafor']", timeout=6000)
    await page.wait_for_timeout(1100)

    # Fill the form slowly enough that each field is readable
    await page.locator("input[placeholder='e.g. Ben Okafor']").press_sequentially(
        "Jane Eyre", delay=55
    )
    await page.wait_for_timeout(380)
    await page.select_option("select", "F")
    await page.wait_for_timeout(320)
    await page.locator("input[type=number]:not([placeholder])").fill("28")
    await page.wait_for_timeout(260)
    await page.locator("input[placeholder=ft]").fill("5")
    await page.wait_for_timeout(220)
    await page.locator("input[placeholder=in]").fill("5")
    await page.wait_for_timeout(260)
    await page.locator("input[placeholder=lb]").fill("128")
    await page.wait_for_timeout(360)
    await page.locator("input[placeholder='e.g. Sub-3:15 Chicago, Oct 11']").press_sequentially(
        "Walk the moors 5mi — build sustainable base for spring", delay=28
    )
    await page.wait_for_timeout(280)
    await page.locator("textarea").press_sequentially(
        "Mild lower-back stiffness on long walks; nothing acute", delay=22
    )
    await page.wait_for_timeout(900)

    # Submit
    await page.get_by_role("button", name="Create client").click()

    # Lands on the new client's detail. No data yet — viewer sees the
    # NoDataBanner and the gauge in its empty state.
    with contextlib.suppress(Exception):
        await page.wait_for_selector("h1", timeout=8000)
    await page.wait_for_timeout(2200)
    # A small scroll so the no-data state is clearly framed
    await page.evaluate("window.scrollTo({top: 280, behavior: 'smooth'})")
    await page.wait_for_timeout(1800)
    await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    await page.wait_for_timeout(1100)

    # ── 3. Open a rich existing client (Marcus Hill — Deload) ──
    await page.goto(f"{WEB}/clients/?id=c_ben", wait_until="domcontentloaded")
    await page.wait_for_selector(".fit-rec-card", timeout=15000)
    await page.wait_for_timeout(2200)

    # Slow scroll down the page so the camera sweeps every section:
    # gauge → recommendation → contraindications → plan → trends →
    # sessions/history → thresholds.
    for y in (220, 480, 760, 1080, 1440, 1820, 2200, 2600):
        await page.evaluate(f"window.scrollTo({{top: {y}, behavior: 'smooth'}})")
        await page.wait_for_timeout(1500)

    # Scroll back up to the recommendation card and hover a citation chip
    await page.evaluate("window.scrollTo({top: 340, behavior: 'smooth'})")
    await page.wait_for_timeout(1400)
    chip = page.locator("button[aria-label^='About citation']").first
    try:
        await chip.wait_for(timeout=3000)
        await chip.scroll_into_view_if_needed(timeout=2000)
        await page.wait_for_timeout(500)
        await chip.hover()
        await page.wait_for_timeout(1800)
        await chip.click()
        await page.wait_for_timeout(2200)
        # Dismiss popover by clicking elsewhere
        await page.mouse.click(20, 20)
        await page.wait_for_timeout(700)
    except Exception as e:
        print(f"  citation-chip interaction skipped: {e}")
        await page.wait_for_timeout(800)

    # Peek at the Override drawer (open + close)
    try:
        await page.get_by_role("button", name="Override").click()
        await page.wait_for_timeout(2000)
        # Close via the Escape key or a Cancel button — try both
        try:
            await page.get_by_role("button", name="Cancel").click(timeout=1500)
        except Exception:
            await page.keyboard.press("Escape")
        await page.wait_for_timeout(900)
    except Exception as e:
        print(f"  override drawer skipped: {e}")

    # ── 4. Pivot to a Conservative client (different verdict band) ──
    await page.goto(f"{WEB}/clients/?id=c_carla", wait_until="domcontentloaded")
    await page.wait_for_selector(".fit-rec-card", timeout=15000)
    await page.wait_for_timeout(2000)
    await page.evaluate("window.scrollTo({top: 380, behavior: 'smooth'})")
    await page.wait_for_timeout(1800)
    await page.evaluate("window.scrollTo({top: 900, behavior: 'smooth'})")
    await page.wait_for_timeout(1800)

    # ── 5. End back on the roster so the new client row is visible ──
    await page.goto(f"{WEB}/", wait_until="domcontentloaded")
    await page.wait_for_selector(".fit-roster-row", timeout=8000)
    await page.wait_for_timeout(2800)  # final settle

    await _finalize_video(ctx, page, target)
    return target


# ─── Registry ────────────────────────────────────────────────────────

FLOWS = {
    "intake": record_intake_flow,
    "roster": record_roster_overview,
    "client": record_client_detail,
    "calibration": record_calibration,
    "tour": record_full_tour,
}


async def main() -> int:
    requested = sys.argv[1:] or list(FLOWS.keys())
    unknown = [r for r in requested if r not in FLOWS]
    if unknown:
        print(f"unknown flows: {unknown}; available: {list(FLOWS.keys())}")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="fitontology-demo-raw-") as raw_tmp:
        raw_dir = Path(raw_tmp)
        async with async_playwright() as p:
            browser = await p.chromium.launch(slow_mo=60)
            try:
                for name in requested:
                    print(f"recording {name}…")
                    out = await FLOWS[name](browser, raw_dir)
                    if out:
                        print(f"  wrote {out.relative_to(ROOT)}")
            finally:
                await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
