"""
Desktop launcher for FitOntology.

Starts Streamlit on a free local port and opens the user's default browser
to the dashboard. When packaged with PyInstaller into FitOntology.exe, this
gives non-technical users a double-click experience: the app launches, the
window opens, the terminal stays out of their way.

Run directly with:   python launcher.py
Packaged build:      dist/FitOntology/FitOntology.exe
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _bundle_root() -> Path:
    """Locate app.py whether running from source or from a PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        # PyInstaller sets sys._MEIPASS to the temp extraction directory.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect(("127.0.0.1", port))
                return True
            except OSError:
                time.sleep(0.2)
    return False


def _open_browser_when_ready(port: int) -> None:
    if _wait_for_port(port):
        webbrowser.open(f"http://127.0.0.1:{port}")


def main() -> int:
    root = _bundle_root()
    app_path = root / "app.py"
    if not app_path.exists():
        print(f"Could not find app.py at {app_path}.", file=sys.stderr)
        return 1

    port = _find_free_port()
    threading.Thread(target=_open_browser_when_ready, args=(port,), daemon=True).start()

    # Run Streamlit as a child of *this* interpreter so the PyInstaller
    # bundle's bundled Python is what executes. Passing --server.headless
    # suppresses Streamlit's own browser-open (we handle that ourselves).
    env = os.environ.copy()
    env.setdefault("STREAMLIT_BROWSER_GATHERUSAGESTATS", "false")
    env.setdefault("STREAMLIT_SERVER_HEADLESS", "true")

    cmd = [
        sys.executable,
        "-m", "streamlit", "run", str(app_path),
        "--server.port", str(port),
        "--server.address", "127.0.0.1",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]

    try:
        return subprocess.call(cmd, env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
