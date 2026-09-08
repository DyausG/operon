"""Characterization and persistence regression tests for the demo engine."""
from __future__ import annotations

import logging

import pytest

from core import engine as engine_module
from core.db import get_conn
from core.seed_data import SENSOR_FEATURES, seed
from core.simulator import FAIL_PROG, FLEET


class StubModel:
    def __init__(self, failure_prob: float = 0.1):
        self.failure_prob = failure_prob

    def predict(self, _features: dict) -> dict:
        return {"failure_prob": self.failure_prob,
                "health_score": 1.0 - self.failure_prob}

    def predict_mode(self, _features: dict) -> dict:
        return {"mode": "PWF", "mode_label": "Power Failure",
                "mode_probs": {"PWF": 1.0}}

    def attribute(self, _features: dict) -> list[dict]:
        return []


def make_engine(monkeypatch: pytest.MonkeyPatch, failure_prob: float = 0.1):
    monkeypatch.setattr(engine_module, "load_or_train", lambda: StubModel(failure_prob))
    return engine_module.DemoEngine()


def pending_alert(proposal: dict | None = None) -> dict:
    return {
        "equipment_id": "AC-COMP-01",
        "equipment_name": "Instrument Air Compressor 01",
        "equipment_class": "COMPRESSOR",
        "criticality": "HIGH",
        "failure_prob": 0.91,
        "predicted_mode": "PWF",
        "predicted_mode_label": "Power Failure",
        "status": "PENDING_APPROVAL",
        "created_tick": 1,
        "triage_rank": 1,
        "triage_score": 0.91,
        "proposal": proposal or {
            "business": {"recovered_value": 1000.0,
                         "downtime_hours_avoided": 7.25},
        },
        "result": None,
    }


@pytest.mark.asyncio
async def test_eight_machine_tick_persists_telemetry_and_health_scores(
    seeded_db, monkeypatch,
):
    engine = make_engine(monkeypatch)

    await engine._advance()

    assert engine.tick_i == 1
    assert set(engine.assets) == {profile.equipment_id for profile in FLEET}
    assert len(engine.assets) == 8
    assert all(len(points) == 1 for points in engine.histories.values())

    expected_sensor_ids = {
        f"{profile.equipment_id}-{sensor_type}"
        for profile in FLEET
        for _feature_key, sensor_type, _unit in SENSOR_FEATURES
    }
    with get_conn() as conn:
        reading_ids = {
            row["sensor_id"]
            for row in conn.execute("SELECT sensor_id FROM sensor_reading")
        }
        reading_count = conn.execute(
            "SELECT COUNT(*) AS n FROM sensor_reading"
        ).fetchone()["n"]
        score_count = conn.execute(
            "SELECT COUNT(*) AS n FROM health_score"
        ).fetchone()["n"]

    assert reading_ids == expected_sensor_ids
    assert reading_count == 8 * len(SENSOR_FEATURES)
    assert score_count == 8


def test_bad_telemetry_is_logged_without_rolling_back_health_score(
    seeded_db, monkeypatch, caplog,
):
    engine = make_engine(monkeypatch)

    with caplog.at_level(logging.ERROR, logger="core.engine"):
        result = engine._persist(
            [("AC-COMP-01-NOT-A-SENSOR", "2026-09-08T12:00:00", 1.0, "GOOD")],
            [("AC-COMP-01", "2026-09-08T12:00:00", 0.4, 0.6, "PWF")],
        )

    assert result == {"telemetry": False, "health_scores": True}
    assert "Telemetry persistence failed" in caplog.text
    assert "AC-COMP-01-NOT-A-SENSOR" in caplog.text
    with get_conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM sensor_reading"
        ).fetchone()["n"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM health_score"
        ).fetchone()["n"] == 1


@pytest.mark.asyncio
async def test_threshold_crossing_alerts_only_degrading_machines(
    seeded_db, monkeypatch,
):
    engine = make_engine(monkeypatch, failure_prob=0.91)
    monkeypatch.setattr(engine_module.agent, "decide", lambda _ctx: {"business": {}})

    await engine._advance()

    degrading_ids = {
        profile.equipment_id for profile in FLEET if profile.scenario != "healthy"
    }
    assert set(engine.alerts) == degrading_ids
    assert all(alert["status"] == "PENDING_APPROVAL"
               for alert in engine.alerts.values())
    assert all(engine.sim.assets[eid].mode == "arrested" for eid in degrading_ids)
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM alert").fetchone()["n"] == 4


@pytest.mark.asyncio
async def test_pause_and_resume_preserve_engine_state(seeded_db, monkeypatch):
    engine = make_engine(monkeypatch)
    await engine._advance()
    assets_before = engine.assets

    await engine.start()
    assert engine.running is True
    assert engine._task is not None
    await engine.stop()
    assert engine.running is False
    assert engine._task is None
    assert engine.tick_i == 1
    assert engine.assets == assets_before

    await engine.start()
    assert engine.running is True
    assert engine._task is not None
    await engine.stop()


@pytest.mark.asyncio
async def test_explicit_reset_clears_demo_state_but_keeps_master_data(
    seeded_db, monkeypatch,
):
    engine = make_engine(monkeypatch)
    await engine._advance()
    engine.alerts["AC-COMP-01"] = pending_alert()

    try:
        await engine.reset()
        assert engine.running is True
        assert engine.tick_i == 0
        assert engine.assets == {}
        assert engine.histories == {}
        assert engine.alerts == {}
        with get_conn() as conn:
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM equipment"
            ).fetchone()["n"] == 8
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM sensor_reading"
            ).fetchone()["n"] == 0
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM health_score"
            ).fetchone()["n"] == 0
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_approval_starts_simulated_recovery(seeded_db, monkeypatch):
    engine = make_engine(monkeypatch)
    engine.alerts["AC-COMP-01"] = pending_alert()
    engine.sim.assets["AC-COMP-01"].prog = 0.9
    engine.sim.set_mode("AC-COMP-01", "arrested")
    monkeypatch.setattr(
        engine_module,
        "commit_actions",
        lambda _proposal: {"wo_number": "WO-TEST", "package_number": "WP-TEST"},
    )

    response = await engine.approve("AC-COMP-01")

    assert response["ok"] is True
    assert engine.alerts["AC-COMP-01"]["status"] == "APPROVED"
    assert engine.sim.assets["AC-COMP-01"].mode == "recovering"
    assert engine.status_override["AC-COMP-01"] == "SCHEDULED"
    for _ in range(5):
        engine.sim.tick()
    assert engine.sim.assets["AC-COMP-01"].mode == "healthy"
    assert engine.sim.assets["AC-COMP-01"].prog == 0.0


@pytest.mark.asyncio
async def test_rejection_runs_asset_to_unplanned_failure(seeded_db, monkeypatch):
    engine = make_engine(monkeypatch)
    engine.alerts["AC-COMP-01"] = pending_alert()
    engine.sim.assets["AC-COMP-01"].prog = FAIL_PROG - 0.01
    engine.sim.set_mode("AC-COMP-01", "arrested")

    response = await engine.reject("AC-COMP-01")
    assert response == {"ok": True}
    assert engine.sim.assets["AC-COMP-01"].mode == "failing"

    await engine._advance()

    assert engine.alerts["AC-COMP-01"]["status"] == "FAILED"
    assert engine.alerts["AC-COMP-01"]["result"]["outcome"] == "UNPLANNED_FAILURE"
    assert engine.status_override["AC-COMP-01"] == "DOWN"


def test_normal_seed_is_idempotent_and_preserves_existing_state(seeded_db):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO health_score "
            "(equipment_id, scored_at, health_score, failure_prob, predicted_mode) "
            "VALUES (?,?,?,?,?)",
            ("AC-COMP-01", "restart-marker", 0.75, 0.25, "PWF"),
        )

    seed()
    seed()

    with get_conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM equipment"
        ).fetchone()["n"] == 8
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM health_score WHERE scored_at='restart-marker'"
        ).fetchone()["n"] == 1


def test_explicit_full_demo_seed_reset_removes_existing_state(seeded_db):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO health_score "
            "(equipment_id, scored_at, health_score, failure_prob, predicted_mode) "
            "VALUES (?,?,?,?,?)",
            ("AC-COMP-01", "full-reset-marker", 0.75, 0.25, "PWF"),
        )

    seed(reset=True)

    with get_conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM health_score"
        ).fetchone()["n"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM equipment"
        ).fetchone()["n"] == 8


@pytest.mark.asyncio
async def test_application_startup_preserves_persisted_state(seeded_db, monkeypatch):
    from server import main as server_main

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO health_score "
            "(equipment_id, scored_at, health_score, failure_prob, predicted_mode) "
            "VALUES (?,?,?,?,?)",
            ("AC-COMP-01", "startup-marker", 0.8, 0.2, "PWF"),
        )

    class FakeEngine:
        def __init__(self):
            self.started = False

        async def start(self):
            self.started = True

    monkeypatch.setattr(server_main, "DemoEngine", FakeEngine)
    await server_main._startup()

    assert server_main.engine.started is True
    with get_conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM health_score WHERE scored_at='startup-marker'"
        ).fetchone()["n"] == 1
