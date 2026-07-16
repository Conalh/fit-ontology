"""Validate the cross-language release contract."""
from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tag_version() -> str | None:
    is_tag = os.environ.get("GITHUB_REF_TYPE") == "tag" or os.environ.get(
        "GITHUB_REF", ""
    ).startswith("refs/tags/")
    if not is_tag:
        return None
    return os.environ.get("GITHUB_REF_NAME", "").removeprefix("v") or None


project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
web = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
version = project["version"]
expected = (sys.argv[1].removeprefix("v") if len(sys.argv) > 1 else None) or _tag_version() or version

if version != expected:
    raise SystemExit(f"pyproject.toml version {version} does not match {expected}")
if web["version"] != expected:
    raise SystemExit(f"web/package.json version {web['version']} does not match {expected}")
if project["requires-python"] != ">=3.12":
    raise SystemExit("pyproject.toml must require Python >=3.12")
if web.get("engines", {}).get("node") != ">=24":
    raise SystemExit("web/package.json must require Node.js >=24")

init_source = (ROOT / "src/fit_ontology/__init__.py").read_text(encoding="utf-8")
match = re.search(r'^__version__ = "([^"]+)"$', init_source, re.MULTILINE)
if not match or match.group(1) != expected:
    raise SystemExit("fit_ontology.__version__ does not match the release version")

changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
if f"## [{expected}]" not in changelog:
    raise SystemExit(f"CHANGELOG.md has no {expected} section")

print(f"release contract ok: v{expected}")
