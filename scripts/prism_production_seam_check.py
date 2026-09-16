"""Stage 2 verification: real Operon reasoning path under PRISM interruption.

Drives the real FastAPI app in-process (same routes and websocket the portal uses) through the
PRODUCTION PRISM Slow Path (``core.prism.operon.OperonSlowPathAdapter``): a real incident, the
real claim (``PromotionService.start_run``), the real fence/apply (``_complete_run`` + settlement
inside the PRISM commit transaction) and the real recovery.

Default (no cloud, no network): the reasoning backend is injected at the production seam
(``ReasoningBackend.supervise``, the exact seam ``run_supervisor`` uses) and HELD, so:
revision 1 claims an Operon run and starts reasoning -> correction accepted as revision 2 ->
revision 1 superseded -> revision 2 claims its own Operon run -> both results released ->
revision 1's valid diagnosis candidate arrives late and is recorded STALE (incident untouched) ->
revision 2 is applied exactly once -> restart -> state unchanged. Provenance: INJECTED.

``--live``: the configured provider (role ``slow``; Gemini first) reasons for real through the
supervisor/specialists. ``--hold`` keeps the genuine candidate at the fence for a few seconds and
the worker is deliberately non-cooperative so a late real result is fenced. Nothing is claimed as
live unless an actual provider call happened (the run's provenance must be LIVE).

Usage:  uv run python scripts/prism_production_seam_check.py [--live] [--hold SECONDS] [--db PATH]
Exit code 0 only when every invariant check passed. Prints measured latencies.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INVESTIGATE = "Investigate the compressor temperature anomaly."
CORRECTION = "Correction: prioritize the vibration spike and ignore the temperature hypothesis for now."


def _ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="use the configured live provider (role slow) instead of the injected seam")
    parser.add_argument("--hold", type=float, default=None, help="seconds to hold the real candidate before the fence (live: default 6)")
    parser.add_argument("--db", default=None, help="database path (default: throwaway temp file)")
    parser.add_argument("--timeout", type=float, default=None, help="max seconds to wait for reasoning (live: default 1800)")
    args = parser.parse_args()
    tmp = Path(args.db) if args.db else Path(tempfile.mkdtemp(prefix="prism-stage2-")) / "poc.db"
    os.environ["POC_DB_PATH"] = str(tmp)
    os.environ.setdefault("POC_MODEL_PATH", str(ROOT / "data" / "health_model.joblib"))
    os.environ["POC_TICK_SECONDS"] = "0.2"
    os.environ["OPERON_PRISM_SLOW_PATH"] = "operon"
    if not args.live:
        # No model anywhere: the provider registry is forced to ``none`` and the seam is injected.
        os.environ["POC_FORCE_DETERMINISTIC"] = "1"
        for key in ("OPERON_AI_PROVIDER", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(key, None)
        os.environ["OPERON_REASONING_BACKEND"] = "none"
    else:
        # The configured provider (Gemini first) must be visible; the engine's own autonomous
        # diagnosis is disabled so the only reasoning on the incident is the PRISM revision's.
        os.environ.pop("POC_FORCE_DETERMINISTIC", None)
        os.environ.setdefault("OPERON_REASONING_BACKEND", "local")
    hold = args.hold if args.hold is not None else (6.0 if args.live else 0.0)
    wait_limit = args.timeout if args.timeout is not None else (1800.0 if args.live else 30.0)

    from fastapi.testclient import TestClient
    from core.db import init_schema
    from core.seed_data import seed
    from core.engine import DemoEngine
    from core.prism.operon import OperonSlowPathAdapter
    from core.prism.testing import FakeReasoningBackend
    from core.reliability import models as m
    from server import main as server_main

    init_schema()
    seed(reset=True)
    checks: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
        print(f"  [{'ok' if ok else 'FAIL'}] {name}{(' · ' + detail) if detail else ''}")

    backend = None if args.live else FakeReasoningBackend(block=True, ignore_cancellation=True)

    def make_engine():
        server_main.app.router.on_startup.clear()
        engine = DemoEngine()
        if args.live:
            engine.runtime = engine._base_runtime = None   # PRISM drives the (live) reasoning, not the tick loop
        services = engine._prism_services()
        if backend is not None:
            services["backend_factory"] = lambda: backend
        engine.prism.coordinator.adapter = engine.prism.adapter = OperonSlowPathAdapter(
            **services, cooperative=False, hold_seconds=hold)
        server_main.engine = engine
        return engine

    mode = "LIVE provider" if args.live else "INJECTED backend at the production seam"
    print(f"PRISM Stage 2 production-seam check · {mode} · hold {hold}s · worker NON-cooperative (late result must be fenced)")
    engine = make_engine()
    identity = engine.prism.adapter.identity()
    print(f"  slow path identity: {json.dumps({k: identity.get(k) for k in ('adapter', 'role', 'backend', 'provider', 'model', 'live_model', 'provenance', 'unavailable_reason')})}")
    if args.live and (not identity.get("live_model") or identity.get("unavailable_reason")):
        print("RESULT: NOT RUN · no live provider is configured for role slow "
              f"({identity.get('unavailable_reason') or 'provider none'}). Live verification was NOT performed.")
        return 2

    def events_of(client, sid):
        return client.get(f"/api/prism/sessions/{sid}/events").json()["events"]

    def wait_until(predicate, limit, step=0.05):
        deadline = time.time() + limit
        while time.time() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(step)
        return None

    with TestClient(server_main.app) as client, client.websocket_connect("/ws") as ws:
        snapshot = json.loads(ws.receive_text())
        check("1. Operon started; /ws snapshot carries prism", snapshot.get("type") == "snapshot" and "prism" in snapshot)
        incident_id = None
        for _ in range(80):
            client.post("/api/start")
            state = client.get("/api/state").json()
            alerts = state.get("alerts") or []
            if alerts and alerts[0].get("incident_id"):
                incident_id = alerts[0]["incident_id"]
                break
            time.sleep(0.25)
        client.post("/api/stop")
        repo = engine.coordinator.repository
        incident = repo.fetch_incident(incident_id) if incident_id else None
        check("1. a real incident with evidence exists and is INVESTIGATING",
              incident is not None and incident.phase == m.IncidentPhase.INVESTIGATING,
              f"incident {incident_id} phase {incident.phase.value if incident else None} revision {incident.revision if incident else None}")
        evidence_count = sum(isinstance(a, m.Evidence) for a in repo.list_artifacts(incident_id))
        r = client.post("/api/prism/sessions", json={"incident_id": incident_id})
        sid = r.json()["session"]["session_id"]
        check("1. PRISM session linked to the incident", r.status_code == 201, f"session {sid[:8]} · {evidence_count} evidence records")
        url = f"/api/prism/sessions/{sid}/messages"

        t0 = time.perf_counter()
        one = client.post(url, json={"content": INVESTIGATE, "request_id": "stage2-1"}).json()
        http1 = (time.perf_counter() - t0) * 1000
        check("2. revision 1 accepted; Fast Path acknowledged immediately; production Slow Path queued",
              one["fast_path"]["status"] == "accepted" and one["slow_path"]["status"] == "QUEUED" and one["slow_path"]["role"] == "slow",
              f"fast path {one['fast_path']['latency_ms']} ms · HTTP {http1:.1f} ms · run {one['slow_path']['run_id'][:8]}")
        started = wait_until(lambda: next((e for e in events_of(client, sid)
                                           if e["event_type"] == "slow_path_progress" and e["revision"] == 1
                                           and e["payload"].get("stage") == "supervisor_started"), None), wait_limit)
        claim = next((e for e in events_of(client, sid) if e["event_type"] == "slow_path_progress" and e["revision"] == 1
                      and e["payload"].get("stage") == "run_claimed"), None)
        incident = repo.fetch_incident(incident_id)
        check("3. revision 1 claimed a real Operon run (snapshot + active_run_id) and the supervisor started",
              started is not None and claim is not None and incident.active_run_id == claim["payload"]["operon_run_id"],
              f"operon run {claim['payload']['operon_run_id'][:8] if claim else None} · evidence {claim['payload'].get('evidence_count') if claim else None}")
        run1_operon = claim["payload"]["operon_run_id"] if claim else None
        if not args.live:
            check("3. injected seam holds the revision-1 result (provider blocked)", len(backend.contexts) == 1
                  and INVESTIGATE in backend.contexts[0].question)

        t0 = time.perf_counter()
        two = client.post(url, json={"content": CORRECTION, "request_id": "stage2-2"}).json()
        http2 = (time.perf_counter() - t0) * 1000
        check("4. correction accepted as revision 2 immediately (revision 1 still reasoning)",
              two["revision"] == 2 and two["fast_path"]["status"] == "accepted_superseding"
              and two["superseded"]["run_ids"] == [one["slow_path"]["run_id"]],
              f"fast path {two['fast_path']['latency_ms']} ms · HTTP {http2:.1f} ms · acceptance {two['acceptance_ms']} ms")
        evs = events_of(client, sid)
        accepted2 = next(e for e in evs if e["event_type"] == "turn_accepted" and e["revision"] == 2)
        cancel_req = next((e for e in evs if e["event_type"] == "cancellation_requested" and e["run_id"] == one["slow_path"]["run_id"]), None)
        queued2 = next((e for e in evs if e["event_type"] == "slow_path_queued" and e["revision"] == 2), None)
        supersede_ms = (_ts(cancel_req["created_at"]) - _ts(accepted2["created_at"])) * 1000 if cancel_req else None
        sched_ms = (_ts(queued2["created_at"]) - _ts(accepted2["created_at"])) * 1000 if queued2 else None
        view = client.get(f"/api/prism/sessions/{sid}").json()["session"]
        r1 = next(r for r in view["runs"] if r["revision"] == 1)
        check("5. revision 1 superseded/cancelling; cancellation and revision-2 scheduling recorded in the acceptance transaction",
              r1["status"] in ("CANCELLING", "CANCELLED", "STALE") and r1["stale"] and cancel_req is not None and queued2 is not None,
              f"run1 {r1['status']} · acceptance→cancellation_requested {supersede_ms:.1f} ms · acceptance→slow_path_queued {sched_ms:.1f} ms")
        started2 = wait_until(lambda: next((e for e in events_of(client, sid) if e["event_type"] == "slow_path_started"
                                            and e["revision"] == 2), None), wait_limit)
        start2_ms = (_ts(started2["created_at"]) - _ts(accepted2["created_at"])) * 1000 if started2 else None
        claim2 = wait_until(lambda: next((e for e in events_of(client, sid) if e["event_type"] == "slow_path_progress"
                                          and e["revision"] == 2 and e["payload"].get("stage") == "run_claimed"), None), wait_limit)
        check("6. revision 2 started its own real Operon run with the correction as the authoritative instruction",
              started2 is not None and claim2 is not None and claim2["payload"]["operon_run_id"] != run1_operon,
              f"acceptance→revision-2 slow_path_started {start2_ms:.1f} ms · operon run {claim2['payload']['operon_run_id'][:8] if claim2 else None}")
        run2_operon = claim2["payload"]["operon_run_id"] if claim2 else None
        if not args.live:
            ok = wait_until(lambda: len(backend.contexts) == 2, wait_limit)
            check("6. injected seam shows revision 2's request carries the correction, not the superseded instruction",
                  ok and CORRECTION in backend.contexts[1].question
                  and backend.contexts[1].question.count("Operator instruction (PRISM revision") == 1
                  and INVESTIGATE not in backend.contexts[1].question)
            backend.release.set()   # both real runs return now; revision 1's is late and must be fenced

        def settled():
            v = client.get(f"/api/prism/sessions/{sid}").json()["session"]
            s = {r["revision"]: r["status"] for r in v["runs"]}
            return v if s.get(2) in ("COMPLETED", "FAILED") and s.get(1) in ("STALE", "CANCELLED", "FAILED") else None
        view = wait_until(settled, wait_limit, step=0.2) or client.get(f"/api/prism/sessions/{sid}").json()["session"]
        statuses = {r["revision"]: r["status"] for r in view["runs"]}
        r1 = next(r for r in view["runs"] if r["revision"] == 1)
        r2 = next(r for r in view["runs"] if r["revision"] == 2)
        late = r1["status"] == "STALE" and r1["result"] is not None
        check("7. revision 1's late real candidate arrived after supersession and was recorded STALE (historical only)",
              late or r1["status"] == "CANCELLED",
              f"run1 {r1['status']} · candidate {r1['result']['details']['candidate']['disposition'] if late else 'none (cancelled before a result existed)'}")
        reports = [a for a in repo.list_artifacts(incident_id) if isinstance(a, m.SupervisorReport)]
        incident = repo.fetch_incident(incident_id)
        check("8. the stale candidate did not touch the incident: no report for revision 1's Operon run, active run is revision 2's",
              all(r.run_id != run1_operon for r in reports) and incident.active_run_id == run2_operon,
              f"reports {[(r.run_id[:8], r.completion, list(r.stale_reasons)) for r in reports]} · phase {incident.phase.value}")
        check("9. revision 2 completed and was applied exactly once (one report, one apply effect, canonical revision 2)",
              statuses.get(2) == "COMPLETED" and view["canonical_revision"] == 2 and view["canonical"]["run_id"] == r2["run_id"]
              and sum(r.run_id == run2_operon for r in reports) == 1
              and sum(e["kind"] == "canonical_apply" and e["status"] == "COMPLETED" for e in view["effects"]) == 1,
              f"run2 {statuses.get(2)} · settlement {(view['reasoning'].get('applied') or {}).get('settlement', {}).get('disposition')} · incident phase {incident.phase.value}")
        provenance = view["canonical"]["result"]["provenance"] if view.get("canonical") else None
        expected = "LIVE" if args.live else "INJECTED"
        check(f"    provenance labelled {expected}", provenance == expected,
              f"{provenance} · backend {view['provenance'].get('backend')} · provider {view['provenance'].get('provider')} · model {view['provenance'].get('model')}")
        stages = [e["payload"].get("stage") for e in events_of(client, sid) if e["event_type"] == "slow_path_progress" and e["revision"] == 2]
        check("    revision 2 progress: context prepared → claimed → supervisor → candidate → fenced → applied",
              stages[:2] == ["reasoning_context_prepared", "run_claimed"] and "supervisor_started" in stages
              and stages[-3:] == ["candidate_ready", "candidate_fenced", "candidate_applied"],
              " → ".join(dict.fromkeys(s for s in stages if s)))
        if args.live:
            specialists = [e["payload"] for e in events_of(client, sid) if e["event_type"] == "slow_path_progress"
                           and e["payload"].get("stage") in ("specialist_started", "specialist_completed")]
            check("    live: real supervisor and specialist calls occurred", any(s.get("stage") == "specialist_completed" for s in specialists),
                  ", ".join(f"{s.get('role')}:{s.get('status', 'started')}" for s in specialists))
        prism_frames = 0
        for _ in range(600):
            frame = json.loads(ws.receive_text())
            if frame.get("type") == "prism":
                prism_frames += 1
                if frame["event"]["event_type"] == "canonical_state_updated" and frame["event"]["revision"] == 2:
                    break
        check("    websocket carried prism envelopes through revision 2's canonical_state_updated", prism_frames >= 10, f"{prism_frames} frames")
        latencies = client.get("/api/prism/metrics").json()["fast_path_acknowledgement"]
        phase_before_restart = incident.phase.value
    make_engine()
    with TestClient(server_main.app) as client:
        client.post("/api/start"); client.post("/api/stop")
        view = client.get(f"/api/prism/sessions/{sid}").json()["session"]
        incident = engine.coordinator.repository.fetch_incident(incident_id)
        check("10. after restart revision 2 remains canonical, nothing revived, incident unchanged",
              view["current_revision"] == 2 and view["canonical_revision"] == 2 and view["recovery"] is None
              and {r["revision"]: r["status"] for r in view["runs"]}.get(1) in ("STALE", "CANCELLED")
              and incident.phase.value == phase_before_restart and incident.active_run_id == run2_operon,
              f"runs {[(r['revision'], r['status']) for r in view['runs']]} · phase {incident.phase.value}")
        reconnect = client.get(f"/api/prism/sessions/{sid}/events?after=0").json()
        check("    reconnect state reconstructs the timeline", reconnect["type"] == "prism_reconnect" and len(reconnect["events"]) >= 12)
    print(f"Fast Path acknowledgement latency (in-transaction, ms): {latencies}")
    print(f"HTTP round trips (ms): revision 1 {http1:.1f}, revision 2 {http2:.1f}")
    print(f"Correction acceptance → supersession/cancellation event: {supersede_ms:.1f} ms; → revision-2 slow_path_queued: {sched_ms:.1f} ms; "
          f"→ revision-2 slow_path_started: {start2_ms:.1f} ms")
    failed = [c for c in checks if not c[1]]
    print("RESULT:", "PASS" if not failed else f"FAIL ({len(failed)} check(s))",
          "· provenance", "LIVE (actual provider calls)" if args.live else "INJECTED (no model; production seam exercised)")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
