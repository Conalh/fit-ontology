"""Console-script entry point: launch the FastAPI app via Uvicorn.

Wired up as ``fit-ontology-serve`` in pyproject.toml's [project.scripts]
so a fresh editable install exposes ``fit-ontology-serve --port 8000``
as a binary the trainer can run.
"""
from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FitOntology FastAPI app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on source changes — useful while building the front-end.",
    )
    args = parser.parse_args()

    import uvicorn
    uvicorn.run("fit_ontology.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
