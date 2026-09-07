"""A2A round-trip (integration): drive the Governance + Monitoring peer server
in-process over the A2A protocol using httpx's ASGITransport (no port, no
subprocess) — resolves each agent card and exchanges a real A2A message.

Deselect with `-m 'not integration'`.
"""
from __future__ import annotations
import json
import uuid

import httpx
import pytest
from a2a.client import A2AClient, A2ACardResolver
from a2a.types import (Message, Part, TextPart, Role, SendMessageRequest,
                       MessageSendParams)

pytestmark = pytest.mark.integration

_BASE = "http://testserver"


async def _ask(app, agent: str, payload: dict) -> dict:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=_BASE,
                                 follow_redirects=True) as http:
        card = await A2ACardResolver(http, base_url=f"{_BASE}/{agent}").get_agent_card()
        client = A2AClient(http, agent_card=card)
        msg = Message(role=Role.user, message_id=uuid.uuid4().hex, kind="message",
                      parts=[Part(root=TextPart(text=json.dumps(payload)))])
        resp = await client.send_message(
            SendMessageRequest(id=uuid.uuid4().hex, params=MessageSendParams(message=msg)))
        result = resp.root.result
        parts = getattr(result, "parts", None)
        if parts is None and hasattr(result, "status"):
            parts = getattr(result.status.message, "parts", [])
        text = "".join(getattr(p.root, "text", "") for p in (parts or []))
        return json.loads(text)


async def test_a2a_governance_vetoes_without_technician(seeded_db):
    from a2a_app.server import build_app
    app = build_app(base_url=_BASE)
    verdict = await _ask(app, "governance", {
        "actions": {"technician": None, "parts": {"critical_available": True}},
        "prediction": {"failure_prob": 0.9}, "business": {"unplanned_loss": 50_000}})
    assert verdict["decision"] == "VETO"
    assert verdict["policy_version"] == "gov-policy-1"


async def test_a2a_monitoring_escalates_same_class(seeded_db):
    from a2a_app.server import build_app
    app = build_app(base_url=_BASE)
    assessment = await _ask(app, "monitoring", {"alerts": [
        {"equipment_id": "HYD-PUMP-03", "equipment_class": "PUMP", "predicted_mode": "HDF"},
        {"equipment_id": "COOL-PMP-09", "equipment_class": "PUMP", "predicted_mode": "PWF"}]})
    assert assessment["escalate"] is True
    assert any(c["pattern"] == "same-equipment-class" for c in assessment["correlations"])
