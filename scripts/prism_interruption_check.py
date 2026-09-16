"""Deterministic PRISM interruption verification (Stage 1). No cloud model, no network.

Drives the real FastAPI app in-process (same routes and websocket the portal uses) through:
revision 1 accepted -> Slow Path runs with a delay -> correction accepted as revision 2 ->
revision 1 superseded -> its late/non-cooperative result arrives -> recorded stale/discarded ->
revision 2 completes -> "restart" (new engine over the same database) -> revision 2 still canonical.

Usage:  uv run python scripts/prism_interruption_check.py [--cooperative] [--delay SECONDS]
Exit code 0 only when every invariant check passed. Prints measured Fast Path latencies.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=1.5, help="Slow Path delay (seconds) for the deterministic adapter")
    parser.add_argument("--cooperative", action="store_true", help="worker honours cancellation (default: ignores it)")
    parser.add_argument("--db", default=None, help="database path (default: throwaway temp file)")
    args = parser.parse_args()
    tmp = Path(args.db) if args.db else Path(tempfile.mkdtemp(prefix="prism-verify-")) / "poc.db"
    os.environ["POC_DB_PATH"] = str(tmp)
    os.environ.setdefault("POC_MODEL_PATH", str(ROOT / "data" / "health_model.joblib"))
    os.environ["POC_FORCE_DETERMINISTIC"] = "1"
    os.environ["POC_TICK_SECONDS"] = "0.2"
    os.environ["OPERON_PRISM_SLOW_PATH"] = "deterministic"
    os.environ["OPERON_PRISM_SLOW_DELAY_SECONDS"] = str(args.delay)
    os.environ["OPERON_PRISM_SLOW_COOPERATIVE"] = "1" if args.cooperative else "0"
    for key in ("OPERON_AI_PROVIDER", "OPERON_REASONING_BACKEND", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        os.environ.pop(key, None)

    from fastapi.testclient import TestClient
    from core.db import init_schema
    from core.seed_data import seed
    from core.engine import DemoEngine
    from server import main as server_main

    init_schema()
    seed(reset=True)
    checks: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
        print(f"  [{'ok' if ok else 'FAIL'}] {name}{(' · ' + detail) if detail else ''}")

    def make_engine():
        server_main.app.router.on_startup.clear()
        engine = DemoEngine()
        server_main.engine = engine
        return engine

    print(f"PRISM interruption check · delay {args.delay}s · worker {'cooperative' if args.cooperative else 'NON-cooperative (ignores cancellation)'}")
    make_engine()
    with TestClient(server_main.app) as client, client.websocket_connect("/ws") as ws:
        snapshot = json.loads(ws.receive_text())
        check("1. Operon started; /ws snapshot carries prism", snapshot.get("type") == "snapshot" and "prism" in snapshot)
        # Drive the simulator until an incident exists so the session can be linked to it.
        incident_id = None
        for _ in range(60):
            client.post("/api/start")
            state = client.get("/api/state").json()
            alerts = state.get("alerts") or []
            if alerts and alerts[0].get("incident_id"):
                incident_id = alerts[0]["incident_id"]
                break
            time.sleep(0.25)
        client.post("/api/stop")
        r = client.post("/api/prism/sessions", json={"incident_id": incident_id} if incident_id else {})
        session = r.json()["session"]
        sid = session["session_id"]
        check("2. PRISM session created" + (" (linked to demo incident)" if incident_id else " (no incident yet)"),
              r.status_code == 201, f"session {sid[:8]} incident {incident_id}")
        url = f"/api/prism/sessions/{sid}/messages"
        t0 = time.perf_counter()
        one = client.post(url, json={"content": "Investigate the compressor temperature anomaly.", "request_id": "verify-1"}).json()
        http1 = (time.perf_counter() - t0) * 1000
        check("3/4. Fast Path acknowledged revision 1 immediately; Slow Path scheduled",
              one["fast_path"]["status"] == "accepted" and one["slow_path"]["status"] == "QUEUED",
              f"fast path {one['fast_path']['latency_ms']} ms · HTTP round trip {http1:.1f} ms · run {one['slow_path']['run_id'][:8]}")
        time.sleep(0.15)
        view = client.get(f"/api/prism/sessions/{sid}").json()["session"]
        check("4. revision 1 Slow Path is RUNNING with the intentional delay", view["slow_path"]["status"] == "RUNNING",
              view["slow_path"]["status"])
        t0 = time.perf_counter()
        two = client.post(url, json={"content": "Correction: prioritize the vibration spike and ignore the temperature hypothesis for now.",
                                     "request_id": "verify-2"}).json()
        http2 = (time.perf_counter() - t0) * 1000
        check("5/6. correction accepted as revision 2 before revision 1 completed",
              two["revision"] == 2 and two["fast_path"]["status"] == "accepted_superseding",
              f"fast path {two['fast_path']['latency_ms']} ms · HTTP round trip {http2:.1f} ms")
        view = client.get(f"/api/prism/sessions/{sid}").json()["session"]
        r1 = next(r for r in view["runs"] if r["revision"] == 1)
        check("7. revision 1 marked superseded/cancelling", r1["status"] in ("CANCELLING", "CANCELLED", "SUPERSEDED") and r1["stale"],
              f"run1 {r1['status']} · interruption {view['interruption']['superseded_revision']}→{view['interruption']['superseded_by']}")
        # 8-11: wait for both workers.
        deadline = time.time() + args.delay * 3 + 5
        while time.time() < deadline:
            view = client.get(f"/api/prism/sessions/{sid}").json()["session"]
            statuses = {r["revision"]: r["status"] for r in view["runs"]}
            if statuses.get(2) == "COMPLETED" and statuses.get(1) in ("STALE", "CANCELLED"):
                break
            time.sleep(0.1)
        statuses = {r["revision"]: r["status"] for r in view["runs"]}
        r1 = next(r for r in view["runs"] if r["revision"] == 1)
        if args.cooperative:
            check("8/9. revision 1 worker cancelled cooperatively (no late result)", statuses.get(1) == "CANCELLED", statuses.get(1))
        else:
            check("8/9. revision 1's late result arrived and was recorded stale/discarded",
                  statuses.get(1) == "STALE" and r1["result"] is not None and "revision 1" in r1["result"]["summary"].lower(), statuses.get(1))
        check("10. stale result did not alter revision 2 canonical state",
              view["canonical_revision"] == 2 and view["canonical"]["run_id"] == two["slow_path"]["run_id"]
              and "Revision 2" in view["canonical"]["result"]["summary"], f"canonical revision {view['canonical_revision']}")
        check("11. revision 2 completed", statuses.get(2) == "COMPLETED", statuses.get(2))
        events = [e["event_type"] for e in client.get(f"/api/prism/sessions/{sid}/events").json()["events"]]
        check("    events expose interruption", {"interruption_received", "revision_superseded", "cancellation_requested"} <= set(events)
              and (("stale_result_discarded" in events) != args.cooperative), ", ".join(events))
        prism_frames = 0
        for _ in range(400):   # the socket also carries tick/alert frames from the simulator
            frame = json.loads(ws.receive_text())
            if frame.get("type") == "prism":
                prism_frames += 1
                if frame["event"]["event_type"] == "canonical_state_updated":
                    break
        check("    websocket carried prism envelopes (through canonical_state_updated)", prism_frames >= 10, f"{prism_frames} prism frames")
        check("    result provenance labelled DETERMINISTIC", view["canonical"]["result"]["provenance"] == "DETERMINISTIC")
        latencies = client.get("/api/prism/metrics").json()["fast_path_acknowledgement"]
    # 12. Restart: brand-new engine over the same database.
    make_engine()
    with TestClient(server_main.app) as client:
        client.post("/api/start"); client.post("/api/stop")   # start() runs PRISM recovery once
        view = client.get(f"/api/prism/sessions/{sid}").json()["session"]
        check("12. after restart revision 2 remains canonical; nothing revived",
              view["current_revision"] == 2 and view["canonical_revision"] == 2
              and {r["revision"]: r["status"] for r in view["runs"]}.get(1) in ("STALE", "CANCELLED")
              and view["recovery"] is None, f"runs {[(r['revision'], r['status']) for r in view['runs']]}")
        reconnect = client.get(f"/api/prism/sessions/{sid}/events?after=0").json()
        check("    reconnect state reconstructs the timeline", reconnect["type"] == "prism_reconnect" and len(reconnect["events"]) >= 10)
    print(f"Fast Path acknowledgement latency (in-transaction, ms): {latencies}")
    print(f"HTTP round trips (ms): revision 1 {http1:.1f}, revision 2 {http2:.1f}")
    failed = [c for c in checks if not c[1]]
    print("RESULT:", "PASS" if not failed else f"FAIL ({len(failed)} check(s))")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
