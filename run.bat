@echo off
REM ---- Sentinel Agentic Predictive-Maintenance POC : one-click launcher ----
cd /d "%~dp0"
echo Starting Sentinel - Agentic Predictive-Maintenance POC...
echo.
REM uv run auto-creates/updates the environment, so this works even without
REM running install.bat first (it just takes a little longer the first time).
uv run python run.py
if errorlevel 1 (
  echo.
  echo Failed to start. Make sure uv is installed:
  echo   https://docs.astral.sh/uv/getting-started/installation/
)
echo.
echo Server stopped. Press any key to close.
pause >nul
