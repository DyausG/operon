"""
One-command launcher for Operon reliability operations.

    uv run python run.py        # (or double-click run.bat on Windows)

Preserves the existing SQLite database on normal startup, pre-trains/loads the
health model on the AI4I dataset, then serves the dashboard at
http://127.0.0.1:8000/ and opens your browser. Pass ``--reset-demo`` to perform
an explicit full reset before launch.
"""
from __future__ import annotations
import os
import sys
import time
import pathlib
import threading
import webbrowser
import argparse

ROOT = pathlib.Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

HOST = os.getenv("POC_HOST", "127.0.0.1")
PORT = int(os.getenv("POC_PORT", "8000"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the Operon demo")
    parser.add_argument(
        "--reset-demo",
        action="store_true",
        help="explicitly reset the demo database before starting",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open a browser tab (also OPERON_OPEN_BROWSER=0)",
    )
    return parser.parse_args()


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
    args = _parse_args()
    if args.reset_demo:
        from core.seed_data import seed
        seed(reset=True)
        print("  Demo database reset explicitly; master data re-seeded.")
    _warm_model()
    open_browser = not args.no_browser and os.getenv("OPERON_OPEN_BROWSER", "1").strip().lower() not in ("0", "false", "no")
    if open_browser:
        threading.Thread(target=_open_browser, daemon=True).start()
    import uvicorn
    from core.providers.status import render
    registry = config.provider_registry()
    mode = config.agent_mode().upper()
    print("\n" + "=" * 60)
    print(f"  {config.APP_NAME} · {config.APP_TAGLINE}")
    print(f"  Agent mode ->  {mode}  (provider {registry.resolve_kind()}; see docs/DEMO.md to configure one)")
    for line in render(registry.overview())[1:]:
        print("  " + line)
    print(f"  Dashboard  ->  http://{HOST}:{PORT}/")
    print(f"  Press CTRL+C to stop.")
    print("=" * 60 + "\n")
    uvicorn.run("server.main:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
