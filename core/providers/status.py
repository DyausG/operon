"""Print provider status for humans and scripts (used by ``demo.sh``). Never prints a secret.

    uv run python -m core.providers.status            # configuration only, no network
    uv run python -m core.providers.status --probe    # also run Test Connection
    uv run python -m core.providers.status --json
"""
from __future__ import annotations

import argparse
import json
import sys

from . import DISPLAY_NAMES, get_registry

OK, WARN, FAIL = "✓", "⚠", "✗"


def render(overview: dict, probed: dict | None = None) -> list[str]:
    active = overview["active"]
    lines = ["AI provider"]
    if active == "none":
        lines.append(f"{WARN} No external model provider configured (selection: {overview['selection']})")
        lines.append("  Starting in deterministic/demo-safe mode: telemetry, health scoring, incidents")
        lines.append("  and the guided demo run; model-backed reasoning is disabled.")
        return lines
    status = overview["providers"][active]
    mark = OK if status["configured"] else WARN
    lines.append(f"{mark} {DISPLAY_NAMES[active]} selected (selection: {overview['selection']})")
    lines.append(f"  model: {status.get('model') or '-'}")
    if status.get("endpoint"):
        lines.append(f"  endpoint: {status['endpoint']}")
    if status.get("region"):
        lines.append(f"  region: {status['region']}")
    cred = status["credential"]
    lines.append(f"  credential: {cred['detail']}")
    if probed is not None:
        if probed.get("reachable"):
            lines.append(f"{OK} connection test: {probed.get('detail')}")
        else:
            err = probed.get("error") or {}
            lines.append(f"{FAIL} connection test: {err.get('code', 'unknown')} - {err.get('message', probed.get('detail'))}")
    elif not status["configured"]:
        lines.append(f"  {status.get('detail')}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Operon provider status (no secrets are printed)")
    parser.add_argument("--probe", action="store_true", help="run the connection test for the active provider")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)
    reg = get_registry()
    overview = reg.overview()
    probed = None
    if args.probe and overview["active"] != "none":
        probed = reg.test(overview["active"], timeout=args.timeout).model_dump(mode="json")
    if args.json:
        json.dump({"overview": overview, "probe": probed}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write("\n".join(render(overview, probed)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
