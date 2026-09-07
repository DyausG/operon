"""
One-command launcher for the Sentinel Agentic Predictive-Maintenance POC.

    uv run python run.py        # (or double-click run.bat on Windows)

Starts fresh every time: removes the previous SQLite file (master data is
re-seeded on startup), pre-trains/loads the health model on the AI4I dataset,
then serves the dashboard at http://127.0.0.1:8000/ and opens your browser.
"""
from __future__ import annotations
import os
import sys
import time
import pathlib
import threading
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

HOST = os.getenv("POC_HOST", "127.0.0.1")
PORT = int(os.getenv("POC_PORT", "8000"))


def _fresh_db() -> None:
    for name in ("poc.db", "poc.db-journal", "poc.db-wal", "poc.db-shm"):
        try:
            (ROOT / "data" / name).unlink()
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            print(f"  (could not remove {name}: {e})")


def _warm_model() -> None:
    try:
        from core.model import load_or_train
        print("  Preparing health model (training on AI4I 2020 if needed) …")
        m = load_or_train()
        if m.report:
            print(f"  Model ready — failure AUC {m.report.auc}, mode accuracy {m.report.mode_accuracy}.")
    except Exception as e:  # noqa: BLE001
        print(f"  (model warm-up warning: {e})")


def _open_browser() -> None:
    time.sleep(1.8)
    try:
        webbrowser.open(f"http://{HOST}:{PORT}/")
    except Exception:
        pass


def main() -> None:
    from core import config
    _fresh_db()
    _warm_model()
    threading.Thread(target=_open_browser, daemon=True).start()
    import uvicorn
    mode = config.agent_mode().upper()
    print("\n" + "=" * 60)
    print(f"  {config.APP_NAME} · {config.APP_TAGLINE}")
    print(f"  Agent mode ->  {mode}"
          + ("  (set AWS creds + BEDROCK_MODEL_ID for live Bedrock)" if mode == "DETERMINISTIC" else ""))
    print(f"  Dashboard  ->  http://{HOST}:{PORT}/")
    print(f"  Press CTRL+C to stop.")
    print("=" * 60 + "\n")
    uvicorn.run("server.main:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
