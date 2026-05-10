# -*- mode: python ; coding: utf-8 -*-
"""Single-file Windows executable for ModelDocker (PySide6 GUI).

Build from the repo root (prefer a venv with only ``requirements.txt``
installed so PyInstaller does not pull unrelated packages from your global
Python, e.g. IPython / matplotlib)::

    pip install -r requirements.txt pyinstaller
    pyinstaller --clean --noconfirm ModelDocker.spec

Output: ``dist/ModelDocker.exe`` — windowed, no console.

The executable icon is ``ICON.ico`` in the repository root (same folder as this
spec). Replace that file and rebuild to change the embedded Windows icon.

UPX is disabled — compressing Qt DLLs often breaks plugin loading.
"""

import os

_SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
_ICO_PATH = os.path.abspath(os.path.join(_SPEC_DIR, "ICON.ico"))
if not os.path.isfile(_ICO_PATH):
    raise RuntimeError(
        f"Executable icon file missing: {_ICO_PATH}\n"
        "Add ICON.ico next to ModelDocker.spec (repository root) and rebuild."
    )

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "certifi",
        "httpx",
        "keyring",
        "shiboken6",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ModelDocker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ICO_PATH,
)
