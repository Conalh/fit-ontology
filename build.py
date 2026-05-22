"""
Build FitOntology as a single-folder Windows executable via PyInstaller.

Run: python build.py
Output: dist/FitOntology/FitOntology.exe (plus a folder of runtime files)

Why single-folder (--onedir) and not --onefile:
  Streamlit lazily imports a lot of things at runtime, and PyInstaller's
  --onefile mode unpacks to a temp directory on every launch. That breaks
  Streamlit's relative-path assumptions on Windows. --onedir avoids the
  unpack and starts faster.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPEC = ROOT / "FitOntology.spec"


def _ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pyinstaller"])


def _streamlit_data_dirs() -> list[str]:
    """Streamlit ships JS/CSS assets that PyInstaller doesn't see by default.
    Collect the runtime package directory and pass it as --add-data."""
    import streamlit
    static = Path(streamlit.__file__).parent / "static"
    runtime = Path(streamlit.__file__).parent / "runtime"
    args: list[str] = []
    if static.exists():
        args += ["--add-data", f"{static}{';' if sys.platform == 'win32' else ':'}streamlit/static"]
    if runtime.exists():
        args += ["--add-data", f"{runtime}{';' if sys.platform == 'win32' else ':'}streamlit/runtime"]
    return args


def main() -> int:
    _ensure_pyinstaller()

    # Clean previous artifacts so reruns are deterministic.
    for path in (DIST, BUILD, SPEC):
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    sep = ";" if sys.platform == "win32" else ":"

    # Exclude heavy packages that aren't actually used by FitOntology but
    # may be present in the developer's global Python (carried in by other
    # projects). PyInstaller's import analysis walks transitively and will
    # drag these in by default, ballooning the bundle from ~400MB to >3GB.
    excludes = [
        "torch", "torchvision", "torchaudio",
        "tensorflow", "tensorflow_cpu", "tensorflow_gpu",
        "matplotlib", "matplotlib_inline",
        "IPython", "jupyter", "jupyter_client", "jupyterlab",
        "notebook", "ipykernel", "ipywidgets",
        "sphinx", "pytest", "pylint", "black", "mypy",
        "transformers", "datasets", "huggingface_hub",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter",
        "cv2", "opencv",
    ]
    exclude_flags: list[str] = []
    for mod in excludes:
        exclude_flags += ["--exclude-module", mod]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",                # no console window on launch
        "--name", "FitOntology",
        "--add-data", f"app.py{sep}.",
        "--add-data", f"src{sep}src",
        # Streamlit hidden imports: PyInstaller's analysis misses these
        # because Streamlit uses string-based lazy loading.
        "--collect-all", "streamlit",
        "--collect-submodules", "streamlit",
        "--collect-data", "streamlit",
        "--collect-all", "altair",
        "--collect-data", "pandas",
        "--hidden-import", "fit_ontology",
        "--hidden-import", "fit_ontology.db",
        "--hidden-import", "fit_ontology.ontology",
        "--hidden-import", "fit_ontology.reasoning",
        *exclude_flags,
        "launcher.py",
    ]

    print("Running:", " ".join(cmd))
    result = subprocess.call(cmd)
    if result != 0:
        return result

    exe = DIST / "FitOntology" / ("FitOntology.exe" if sys.platform == "win32" else "FitOntology")
    if exe.exists():
        print(f"\nBuilt: {exe}")
        print("Double-click that file (or run it from a terminal) to launch the dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
