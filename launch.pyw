"""No-console launcher for ModelDocker.

Double-click this file (or point a shortcut at it) to start the app without a
PowerShell / Command Prompt window. Windows associates ``.pyw`` with
``pythonw.exe``, the windowed Python interpreter that does not open a console.

We also redirect ``stdout`` / ``stderr`` to a rotating log file under
``~/.modeldocker/`` so any third-party print/traceback that fires during
startup is captured instead of silently breaking under ``pythonw`` (where the
standard streams are invalid handles).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _redirect_streams_to_log() -> None:
    """Send stdout/stderr to a log file so pythonw.exe never errors on print()."""
    log_dir = Path.home() / ".modeldocker"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    log_path = log_dir / "modeldocker.log"
    try:
        # Append, line-buffered, replace undecodable bytes so logging never throws.
        log_file = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        return
    sys.stdout = log_file
    sys.stderr = log_file


def _run() -> int:
    _redirect_streams_to_log()
    # Make sure the workspace root is importable when launched from a shortcut
    # whose working directory is not this folder.
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    os.chdir(here)
    from main import main  # imported after sys.path is set so frozen builds work too

    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
