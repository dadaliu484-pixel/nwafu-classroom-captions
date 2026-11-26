@echo off
setlocal
cd /d "%~dp0" || exit /b 1
set "PYTHONUTF8=1"
set "PLAYWRIGHT_BROWSERS_PATH=0"
set "VENV_PYTHON=.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
    if errorlevel 1 (
        py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
        if errorlevel 1 goto missing_python
        py -3 -m venv .venv || goto failed
    ) else (
        python -m venv .venv || goto failed
    )
)

"%VENV_PYTHON%" -c "from importlib.metadata import version; from pathlib import Path; from playwright.sync_api import sync_playwright; p = sync_playwright().start(); ok = 'playwright==' + version('playwright') == Path('requirements.txt').read_text().strip() and Path(p.chromium.executable_path).is_file(); p.stop(); raise SystemExit(not ok)" >nul 2>&1
if errorlevel 1 (
    "%VENV_PYTHON%" -m pip install -r requirements.txt || goto failed
    "%VENV_PYTHON%" -m playwright install --no-shell chromium || goto failed
)

"%VENV_PYTHON%" capture_subtitles.py %* || goto failed
exit /b 0

:missing_python
echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
echo Select "Add python.exe to PATH" in the installer, then open start.cmd again.
pause
exit /b 1

:failed
echo Setup or startup failed. See the message above.
pause
exit /b 1
