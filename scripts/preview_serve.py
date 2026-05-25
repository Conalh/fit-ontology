"""Preview-only API launcher.

Sets a self-contained env (test DB path, session secret, bootstrap
password) then hands off to uvicorn. Used by .claude/launch.json's
"api" config when verifying UI changes in the browser — keeps the
real ``.env`` and the production DB out of the loop.

Not imported anywhere by the application. Safe to delete; the
preview config in launch.json is the only consumer.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Anchor relative paths to the repo root regardless of cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("FIT_ONTOLOGY_DB", str(REPO_ROOT / "data" / "preview_test.duckdb"))
os.environ.setdefault("FIT_ONTOLOGY_SESSION_SECRET", "preview-only-secret-do-not-use-in-prod")
# Bootstrap the default trainer with this password so the login form
# has a valid credential to try. The migration only writes the hash
# if the row currently has no password — re-running this script
# against the same DB is a no-op for the password.
os.environ.setdefault("FIT_ONTOLOGY_DEFAULT_TRAINER_PASSWORD", "preview-pass-1234")


def main() -> int:
    import uvicorn
    uvicorn.run("fit_ontology.api:app", host="127.0.0.1", port=8000, reload=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
