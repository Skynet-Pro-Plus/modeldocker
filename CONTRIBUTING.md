# Contributing to ModelDocker

Thanks for your interest in improving ModelDocker.

## Setup

1. Windows + Python 3.10+ recommended (PySide6 targets Windows here).
2. From the repo root:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

## Run

- **GUI (no console):** `ModelDocker.bat` or `launch.pyw`
- **GUI (console for logs):** `python main.py`

## Tests

Headless smoke checks:

```powershell
python smoke_test.py
```

## Building the Windows `.exe`

1. Place `ICON.ico` at the repository root (required by `ModelDocker.spec`).
2. Optional: install Pillow if icon normalization needs it (`pip install pillow`).
3. Run:

   ```powershell
   .\build_onefile.ps1
   ```

Output: `dist\ModelDocker.exe`. Intermediate PyInstaller output goes to `build/` — do not commit it (see `.gitignore`).

## Assets

- **`Modeldocker.jpg`** — Hero image for the README; keep it in the repo root if you update branding.
- **`ICON.ico`** — Embedded Windows icon for the executable (not always present in every checkout; add before release builds).

## Pull requests

- Keep changes focused; note user-visible behavior in the PR description.
- Run `python smoke_test.py` before submitting when possible.
