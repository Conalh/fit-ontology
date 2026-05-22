"""
Desktop launcher for FitOntology.

Two paths through this file:

  - From source (`python launcher.py`): spawns Streamlit as a subprocess,
    same as `streamlit run app.py` but with auto-port-pick + browser-open.

  - From a PyInstaller bundle (`FitOntology.exe`): runs Streamlit
    IN-PROCESS via streamlit.web.bootstrap. We must NOT use
    subprocess(sys.executable, ...) here — in a frozen bundle,
    sys.executable IS the launcher, so each subprocess call would spawn
    another FitOntology.exe, recursively. (Yes, this is a fork bomb.
    Learned that the hard way once.)

multiprocessing.freeze_support() is called before anything else as a
belt-and-suspenders guard against the same class of issue on Windows.
"""
from __future__ import annotations

import multiprocessing
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _bundle_root() -> Path:
    """Locate app.py whether running from source or from a PyInstaller bundle."""
    if getattr(sys, "frozen", False):
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


def _set_streamlit_env(port: int) -> None:
    """Streamlit reads server.port / server.address / server.headless from
    its config layer; setting them via environment is equivalent to passing
    CLI flags and works whether we go through bootstrap or subprocess."""
    os.environ["STREAMLIT_SERVER_PORT"] = str(port)
    os.environ["STREAMLIT_SERVER_ADDRESS"] = "127.0.0.1"
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ.setdefault("STREAMLIT_BROWSER_GATHERUSAGESTATS", "false")


def _run_frozen(app_path: Path, port: int) -> int:
    """Run Streamlit in-process. No subprocess, no sys.executable re-entry."""
    from streamlit.web import bootstrap
    _set_streamlit_env(port)
    # bootstrap.run signature: (main_script_path, is_hello, args, flag_options)
    bootstrap.run(str(app_path), False, [], {})
    return 0


def _run_dev(app_path: Path, port: int) -> int:
    """Run Streamlit as a subprocess from source. Subprocess is fine here
    because sys.executable is a real python.exe, not the launcher itself."""
    import subprocess
    env = os.environ.copy()
    env.setdefault("STREAMLIT_BROWSER_GATHERUSAGESTATS", "false")
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.port", str(port),
        "--server.address", "127.0.0.1",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    try:
        return subprocess.call(cmd, env=env)
    except KeyboardInterrupt:
        return 0


def main() -> int:
    root = _bundle_root()
    app_path = root / "app.py"
    if not app_path.exists():
        print(f"Could not find app.py at {app_path}.", file=sys.stderr)
        return 1

    port = _find_free_port()
    threading.Thread(target=_open_browser_when_ready, args=(port,), daemon=True).start()

    if getattr(sys, "frozen", False):
        return _run_frozen(app_path, port)
    return _run_dev(app_path, port)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
