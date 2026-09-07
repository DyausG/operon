@echo off
REM ---- First-time setup: create the uv-managed environment ----
cd /d "%~dp0"
echo Setting up the Sentinel POC environment with uv...
echo (downloads Python 3.12 on first run if you don't have it, then installs deps)
echo.
uv sync
if errorlevel 1 (
  echo.
  echo uv not found or sync failed.
  echo Install uv first:  https://docs.astral.sh/uv/getting-started/installation/
  echo   PowerShell:  irm https://astral.sh/uv/install.ps1 ^| iex
  pause >nul
  exit /b 1
)
echo.
echo Done. You can now run the demo with run.bat
pause >nul
