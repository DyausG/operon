"""Services layer: registry selection + local adapters + governed write-back."""
from __future__ import annotations
import pytest

from core import services, tools
from core.db import get_conn
from core.services.adapters import local


def test_default_adapters_are_local():
    assert isinstance(services.inventory(), local.LocalInventoryAdapter)
    assert isinstance(services.workforce(), local.LocalWorkforceAdapter)
    assert isinstance(services.cmms(), local.LocalCmmsAdapter)
    assert isinstance(services.notifications(), local.LocalNotificationAdapter)


def test_unknown_adapter_raises(monkeypatch):
    monkeypatch.setenv("SENTINEL_INVENTORY_ADAPTER", "does-not-exist")
    services.reset_cache()
    with pytest.raises(LookupError):
        services.inventory()


def test_check_parts_reports_critical_spare(seeded_db):
    r = tools.check_parts("AC-COMP-01")
    assert r["critical_available"] is True
    assert any(p["is_critical_spare"] for p in r["parts"])
    assert "on hand" in r["summary"]


def test_check_parts_flags_short_critical_spare(seeded_db):
    # drain COOL-PMP-09's critical spare below the per-service requirement
    with get_conn() as c:
        c.execute("UPDATE part SET on_hand_qty=0 WHERE part_id='PRT-PMPK'")
    r = tools.check_parts("COOL-PMP-09")
    assert r["critical_available"] is False
    assert "SHORT" in r["summary"]


def test_assign_technician_matches_class(seeded_db):
    r = tools.assign_technician("COMPRESSOR")
    assert r["technician"] is not None
    assert "COMPRESSOR" in (r["technician"]["skills"] or "").upper()


def test_assign_technician_none_when_no_match(seeded_db):
    # unknown class AND a shift no available tech is on -> no positive score -> None
    r = tools.assign_technician("NONEXISTENT_CLASS", current_shift="Z")
    assert r["technician"] is None
    assert r["candidates_considered"] >= 1


def test_assign_technician_falls_back_to_on_shift(seeded_db):
    # documents current behavior: an on-shift tech is returned even without the
    # class cert (shift match scores +1); real fleet classes always have a cert.
    r = tools.assign_technician("NONEXISTENT_CLASS", current_shift="A")
    assert r["technician"] is not None and r["technician"]["shift"] == "A"


def test_block_schedule_respects_window(seeded_db):
    r = tools.block_schedule("AC-COMP-01", 30)
    assert r["window_min"] == 30
    assert "–" in r["window"]


def test_notify_draft_writes_nothing(seeded_db):
    r = tools.notify_technician("TECH-201", "s", "b", send=False)
    assert r["status"] == "DRAFT" and r["notification_id"] is None
    with get_conn() as c:
        assert c.execute("SELECT COUNT(*) n FROM notification").fetchone()["n"] == 0


def test_generic_work_package_cannot_bypass_governed_executor(seeded_db):
    from tests.conftest import sample_proposal
    with pytest.raises(TypeError):
        tools.commit_actions(sample_proposal(), None)
    with get_conn() as c:
        for t in ("work_order", "maintenance_event", "work_package",
                  "part_reservation", "labor_booking", "notification"):
            assert c.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"] == 0
