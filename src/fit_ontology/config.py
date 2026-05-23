"""Environment loading — one place, three entry points.

Streamlit's main app, the Ask FitOntology page, and the Garmin sync
script all need to read settings (ANTHROPIC_API_KEY, GARMIN_*, etc.)
from the same .env file at the project root. Before this module each
entry point had its own ad-hoc dotenv import + load — the main app
silently missed it, which is exactly the "works on one page but not
another" footgun the reviewer called out.

No-op when python-dotenv isn't installed (CI, minimal containers).
"""
from __future__ import annotations

from pathlib import Path


def load_env(project_root: Path | None = None) -> None:
    """Idempotently load ``<root>/.env`` into the process environment.

    Repeated calls are cheap — dotenv's load_dotenv won't clobber a
    variable that's already set in the environment.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if project_root is None:
        project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")
