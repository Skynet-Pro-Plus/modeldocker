@echo off
rem ----------------------------------------------------------------------
rem  Launches ModelDocker without showing a console window.
rem  Uses pythonw.exe (the windowed Python interpreter) so the app starts
rem  silently. Double-click this file or pin a shortcut to your taskbar.
rem ----------------------------------------------------------------------
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

rem Prefer a local virtual environment when present so the user does not
rem need pythonw on PATH if they ran `python -m venv .venv`.
if exist "%ROOT%.venv\Scripts\pythonw.exe" (
    start "" "%ROOT%.venv\Scripts\pythonw.exe" "%ROOT%launch.pyw"
    exit /b
)
if exist "%ROOT%venv\Scripts\pythonw.exe" (
    start "" "%ROOT%venv\Scripts\pythonw.exe" "%ROOT%launch.pyw"
    exit /b
)

rem Fall back to the Python launcher (`py -w`) and then PATH-resolved pythonw.
where pyw.exe >nul 2>&1
if %errorlevel%==0 (
    start "" pyw.exe "%ROOT%launch.pyw"
    exit /b
)
where pythonw.exe >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw.exe "%ROOT%launch.pyw"
    exit /b
)

rem Last-ditch fallback: run with python.exe (this WILL show a console, but
rem at least the app still launches if pythonw is missing for some reason).
start "" python.exe "%ROOT%main.py"
endlocal
