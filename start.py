"""Bootstrap script for Hypothex plugin.

Creates an isolated venv at ~/.hypothex/venv/, installs dependencies on first
run (or when pyproject.toml changes), then starts the server.  Requires only a
standard Python 3.11+ installation — no uv, pipx, or global installs needed.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent
HYPOTHEX_DIR = Path.home() / ".hypothex"
VENV_DIR = HYPOTHEX_DIR / "venv"
MARKER = HYPOTHEX_DIR / ".installed_hash"


def _pyproject_hash() -> str:
    return hashlib.sha256(
        (PLUGIN_ROOT / "pyproject.toml").read_bytes()
    ).hexdigest()


def _venv_python() -> str:
    if sys.platform == "win32":
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")


def _needs_install() -> bool:
    if not VENV_DIR.exists():
        return True
    if not MARKER.exists():
        return True
    return MARKER.read_text().strip() != _pyproject_hash()


def _install() -> None:
    if not VENV_DIR.exists():
        print("[hypothex] Creating venv ...", file=sys.stderr)
        subprocess.check_call(
            [sys.executable, "-m", "venv", str(VENV_DIR)],
        )

    print("[hypothex] Installing dependencies ...", file=sys.stderr)
    subprocess.check_call(
        [_venv_python(), "-m", "pip", "install", "-q", "-e", str(PLUGIN_ROOT)],
    )

    HYPOTHEX_DIR.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(_pyproject_hash())
    print("[hypothex] Ready.", file=sys.stderr)


def main() -> None:
    if _needs_install():
        _install()

    sys.exit(
        subprocess.call([_venv_python(), "-m", "hypothex.main"])
    )


if __name__ == "__main__":
    main()
