"""
Maintenance Agent — the agentic layer that turns predictions into governed action.

Hybrid design:
  * A deterministic planner ALWAYS produces a complete, grounded proposal by
    orchestrating the four tools over the semantic model. This is the bullet-proof
    path (no cloud creds required) and the safety net.
  * When a cloud provider is configured (Gemini or Amazon Bedrock, resolved by
    ``core.providers``), a real tool-calling loop lets the model reason over the same
    governed tools and author the decision narrative. Any failure falls back to the
    deterministic plan and is recorded in ``llm_error``, so the demo can never break.
    (This legacy proposal path runs only under OPERON_LEGACY_DEMO; Ollama has no
    legacy tool-calling loop and keeps the deterministic baseline.)
  * When several assets alert at once, `rank_alerts()` triages them by criticality ×
    failure-probability × business impact, so the agent works the highest-value risk first.

The agent only ever PROPOSES. Nothing is written until a human approves
(see tools.commit_actions) — the human-in-the-loop control point.
"""
from __future__ import annotations
import json
from . import tools, config, services, gemini

# Re-exported for backwards-compat / tests (the shared limiter now lives in core.gemini).
_RateLimiter = gemini.RateLimiter


# ---------------------------------------------------------------------------
# Triage — rank concurrent alerts
# ---------------------------------------------------------------------------
def triage_score(ctx: dict) -> float:
    crit = config.CRITICALITY_WEIGHT.get(ctx.get("criticality", "MEDIUM"), 0.6)
    prob = float(ctx["prediction"]["failure_prob"])
    # business impact ~ criticality (a HIGH-criticality line-down costs more)
    return round(crit * prob * (0.5 + 0.5 * crit), 4)


def rank_alerts(contexts: list[dict]) -> list[dict]:
    """Attach a triage rank + score to each alert context, highest risk first."""
    scored = sorted(contexts, key=triage_score, reverse=True)
    for i, ctx in enumerate(scored):
        ctx["triage_rank"] = i + 1
        ctx["triage_score"] = triage_score(ctx)
    return scored


def triage_rationale(ranked: list[dict]) -> str:
    if len(ranked) <= 1:
        return "Single active alert — no contention."
    lead = ranked[0]
    others = ", ".join(f"{c['equipment_id']} ({c['criticality'].lower()}, "
                       f"{c['prediction']['failure_prob']:.0%})" for c in ranked[1:])
    return (f"{len(ranked)} assets alerting simultaneously. Prioritising {lead['equipment_id']} "
            f"— {lead['criticality'].lower()} criticality at {lead['prediction']['failure_prob']:.0%} "
            f"failure probability (triage score {lead['triage_score']:.2f}) — ahead of {others}.")


# ---------------------------------------------------------------------------
# Deterministic planner (always runs; guaranteed complete)
# ---------------------------------------------------------------------------
def build_proposal(ctx: dict) -> dict:
    eid = ctx["equipment_id"]
    eq = tools.get_equipment(eid)
    fm = ctx["failure_mode"]
    pred = ctx["prediction"]
    drivers = ctx["drivers"]
    window_min = int(fm.get("est_planned_minutes", 45) or 45)

    parts = tools.check_parts(eid)
    tech = tools.assign_technician(eq.get("equipment_class", ctx.get("equipment_class", "")))
    sched = tools.block_schedule(eid, window_min)
    tech_id = tech["technician"]["technician_id"] if tech["technician"] else None
    tech_name = tech["technician"]["full_name"] if tech["technician"] else "on-call crew"
    # Draft the dispatch page — nothing is actually sent until a human approves.
    notify = tools.notify_technician(
        tech_id, subject=f"Predictive dispatch pending · {eid}",
        body=(f"{fm['mode_code']} ({fm['failure_mode_name']}) predicted on {eid}. "
              f"Proposed window {sched['window']}."),
        channel="sms", send=False)
    detail = (f"PREDICTIVE work order — {fm['mode_code']} ({fm['failure_mode_name']}). "
              f"Model failure_prob={pred['failure_prob']:.0%} (health {pred['health_score']:.0%}). "
              f"{fm['recommended_action']}")
    wo = tools.propose_work_order(
        eid, fm["failure_mode_id"], tech_id, detail, "HIGH")

    top = drivers[0]
    trace = [
        {"actor": "model", "title": "Prediction received",
         "text": (f"Health model flags {eid} at failure_prob = {pred['failure_prob']:.0%} — above "
                  f"the {config.TRIGGER_THRESHOLD:.0%} action threshold. ~24h of lead time.")},
        {"actor": "agent", "title": "Diagnose failure mode",
         "text": (f"Dominant driver is {top['label']} = {top['value']} (+{top['contribution']:.0%} risk). "
                  f"Model attributes this to {fm['mode_code']} — {fm['failure_mode_name']}: "
                  f"{fm['description'].split('.')[0]}.")},
        {"actor": "tool", "title": "check_parts()", "tool": "check_parts",
         "text": parts["summary"], "result": {"critical_available": parts["critical_available"]}},
        {"actor": "tool", "title": "assign_technician()", "tool": "assign_technician",
         "text": tech["reason"],
         "result": {"technician_id": tech["technician"]["technician_id"] if tech["technician"] else None}},
        {"actor": "tool", "title": "block_schedule()", "tool": "block_schedule",
         "text": f"{sched['note']} Proposed window {sched['window']}.",
         "result": {"window": sched["window"]}},
        {"actor": "tool", "title": "notify_technician()", "tool": "notify_technician",
         "text": (f"Drafted an SMS dispatch to {tech_name} for the {sched['window']} window — "
                  f"held until you approve."),
         "result": {"status": notify["status"]}},
        {"actor": "tool", "title": "open_work_order()", "tool": "open_work_order",
         "text": f"Drafted HIGH-priority predictive work order for {eid}. Awaiting human approval.",
         "result": {"status": "DRAFT"}},
        {"actor": "agent", "title": "Recommendation",
         "text": (f"Convert a projected ~{config.UNPLANNED_OUTAGE_HOURS:.0f}h unplanned line-down into a "
                  f"{window_min}-min planned intervention. Est. recovered value "
                  f"${config.recovered_value():,.0f}. Approve to dispatch.")},
    ]

    return {
        "mode": "deterministic",
        "equipment_id": eid,
        "equipment_name": eq.get("equipment_name") or ctx.get("equipment_name"),
        "equipment_class": eq.get("equipment_class") or ctx.get("equipment_class"),
        "criticality": ctx.get("criticality"),
        "failure_mode": fm,
        "prediction": pred,
        "mode_prediction": ctx.get("mode_prediction"),
        "drivers": drivers,
        "trace": trace,
        "actions": {"work_order": wo, "technician": tech["technician"],
                    "technician_reason": tech["reason"], "parts": parts, "schedule": sched},
        "business": _business_block(ctx),
    }


def _business_block(ctx: dict) -> dict:
    return {
        "recovered_value": round(config.recovered_value(), 0),
        "unplanned_loss": round(config.unplanned_loss(), 0),
        "downtime_hours_avoided": round(config.UNPLANNED_OUTAGE_HOURS - config.PLANNED_SWAP_HOURS, 2),
        "downtime_cost_per_hour": config.DOWNTIME_COST_PER_HOUR,
        "scrap_avoided": config.SCRAP_PER_UNPLANNED_EVENT,
        "oee_baseline": config.OEE_BASELINE, "oee_target": config.OEE_TARGET,
        "fleet_lines": config.FLEET_LINES,
    }


# ---------------------------------------------------------------------------
# Bedrock tool-calling layer (Converse API)
# ---------------------------------------------------------------------------
_TOOLS_SPEC = [
    {"toolSpec": {"name": "check_parts",
        "description": "Look up spare-parts availability for an equipment via the equipment_part bridge.",
        "inputSchema": {"json": {"type": "object",
            "properties": {"equipment_id": {"type": "string"}}, "required": ["equipment_id"]}}}},
    {"toolSpec": {"name": "assign_technician",
        "description": "Find the best certified & available technician for an equipment class.",
        "inputSchema": {"json": {"type": "object",
            "properties": {"equipment_class": {"type": "string"}}, "required": ["equipment_class"]}}}},
    {"toolSpec": {"name": "block_schedule",
        "description": "Propose a planned production-schedule hold (minutes) so the repair avoids a line-down.",
        "inputSchema": {"json": {"type": "object",
            "properties": {"equipment_id": {"type": "string"}, "window_min": {"type": "integer"}},
            "required": ["equipment_id"]}}}},
    {"toolSpec": {"name": "notify_technician",
        "description": ("Draft an SMS/paging dispatch to the assigned technician about the planned "
                        "window. Draft only — it is not sent until a human approves."),
        "inputSchema": {"json": {"type": "object",
            "properties": {"technician_id": {"type": "string"}, "subject": {"type": "string"},
                           "body": {"type": "string"}},
            "required": ["subject"]}}}},
    {"toolSpec": {"name": "open_work_order",
        "description": "Draft a predictive CMMS work order (not written until a human approves).",
        "inputSchema": {"json": {"type": "object",
            "properties": {"equipment_id": {"type": "string"}, "failure_mode_id": {"type": "string"},
                           "technician_id": {"type": "string"}, "detail": {"type": "string"}},
            "required": ["equipment_id", "failure_mode_id", "detail"]}}}},
]


def _dispatch(name: str, args: dict, ctx: dict) -> dict:
    if name == "check_parts":
        return tools.check_parts(args.get("equipment_id", ctx["equipment_id"]))
    if name == "assign_technician":
        return tools.assign_technician(args.get("equipment_class", ctx.get("equipment_class", "")))
    if name == "block_schedule":
        return tools.block_schedule(args.get("equipment_id", ctx["equipment_id"]),
                                    int(args.get("window_min", 45)))
    if name == "notify_technician":
        # draft only during planning — the human approval gates the actual send
        return tools.notify_technician(
            args.get("technician_id"), args.get("subject", f"Dispatch pending · {ctx['equipment_id']}"),
            args.get("body", ""), channel="sms", send=False)
    if name == "open_work_order":
        return tools.propose_work_order(args.get("equipment_id", ctx["equipment_id"]),
                                        args.get("failure_mode_id", ctx["failure_mode"]["failure_mode_id"]),
                                        args.get("technician_id"), args.get("detail", ""), "HIGH")
    return {"error": f"unknown tool {name}"}


def _system_prompt(ctx: dict) -> str:
    fm = ctx["failure_mode"]
    return (
        "You are an autonomous Maintenance Agent for a manufacturing plant. A health model has "
        "predicted an imminent equipment failure. Reason over the governed data using ONLY the provided "
        "tools, then recommend a plan a human will approve. Always: (1) check spare parts, (2) assign a "
        "certified technician, (3) block a planned schedule window, (4) draft a dispatch page to that "
        "technician, and (5) draft a work order. Be concise and decision-oriented. Ground every claim in "
        "tool results — never invent part numbers, technicians, or stock levels.\n\n"
        f"Context: equipment={ctx['equipment_id']} ({ctx.get('equipment_class')}), "
        f"criticality={ctx.get('criticality')}, predicted_failure_mode={fm['mode_code']} "
        f"({fm['failure_mode_name']}), failure_prob={ctx['prediction']['failure_prob']:.2f}, "
        f"top_driver={ctx['drivers'][0]['label']}={ctx['drivers'][0]['value']}."
    )


def _tool_text(name: str, result: dict) -> str:
    if name == "check_parts":
        return result.get("summary", "")
    if name == "assign_technician":
        return result.get("reason", "")
    if name == "block_schedule":
        return f"{result.get('note','')} Window {result.get('window','')}."
    if name == "notify_technician":
        return f"Drafted dispatch page ({result.get('preview','')}) — held until human approval."
    if name == "open_work_order":
        return "Drafted HIGH-priority predictive work order. Awaiting human approval."
    return json.dumps(result, default=str)[:200]


def _enhance_with_bedrock(baseline: dict, ctx: dict) -> dict:
    provider = config.provider_registry().build("bedrock")
    client = provider.session().client("bedrock-runtime", config=provider.client_config())
    messages = [{"role": "user", "content": [{"text":
                "Assess this alert and produce your recommended maintenance plan."}]}]
    trace, executed = [], {}
    for _ in range(6):
        resp = client.converse(
            modelId=provider.model_id,
            system=[{"text": _system_prompt(ctx)}],
            messages=messages,
            toolConfig={"tools": _TOOLS_SPEC},
            inferenceConfig={"maxTokens": config.BEDROCK_MAX_TOKENS, "temperature": 0.2})
        out_msg = resp["output"]["message"]
        messages.append(out_msg)
        tool_results = []
        for block in out_msg.get("content", []):
            if "text" in block and block["text"].strip():
                trace.append({"actor": "agent", "title": "Reasoning", "text": block["text"].strip()})
            elif "toolUse" in block:
                tu = block["toolUse"]
                result = _dispatch(tu["name"], tu.get("input") or {}, ctx)
                executed[tu["name"]] = result
                trace.append({"actor": "tool", "title": f"{tu['name']}()", "tool": tu["name"],
                              "text": _tool_text(tu["name"], result), "result": {}})
                tool_results.append({"toolResult": {"toolUseId": tu["toolUseId"],
                                                    "content": [{"json": result}]}})
        if resp.get("stopReason") == "tool_use" and tool_results:
            messages.append({"role": "user", "content": tool_results})
        else:
            break
    return _merge_llm(baseline, trace, executed, "bedrock")


def _merge_llm(baseline: dict, trace: list, executed: dict, mode: str) -> dict:
    """Overlay the LLM's reasoning trace + tool outputs onto the complete
    deterministic baseline, so the proposal is always fully populated."""
    if not trace:
        return baseline
    p = dict(baseline)
    p["mode"] = mode
    p["trace"] = trace
    if "check_parts" in executed:
        p["actions"]["parts"] = executed["check_parts"]
    if "assign_technician" in executed and executed["assign_technician"].get("technician"):
        p["actions"]["technician"] = executed["assign_technician"]["technician"]
        p["actions"]["technician_reason"] = executed["assign_technician"]["reason"]
    if "block_schedule" in executed:
        p["actions"]["schedule"] = executed["block_schedule"]
    return p


# ---------------------------------------------------------------------------
# Google Gemini tool-calling layer (default for the POC demo; free tier).
#
# Reuses the SAME governed tools, dispatch, system prompt and trace-merge as the
# Bedrock path — only the transport differs. The shared rate limiter + backoff
# (core.gemini) keep us under the free-tier RPM; any failure falls back to the
# deterministic plan.
# ---------------------------------------------------------------------------
def _gemini_tools():
    from google.genai import types
    decls = [types.FunctionDeclaration(
                name=s["toolSpec"]["name"],
                description=s["toolSpec"]["description"],
                parameters_json_schema=s["toolSpec"]["inputSchema"]["json"])
             for s in _TOOLS_SPEC]
    return [types.Tool(function_declarations=decls)]


def _enhance_with_gemini(baseline: dict, ctx: dict) -> dict:
    from google.genai import types
    provider = config.provider_registry().build("gemini")
    client = provider.client()
    cfg = types.GenerateContentConfig(
        system_instruction=_system_prompt(ctx),
        tools=_gemini_tools(),
        temperature=0.2,
        max_output_tokens=provider.settings.max_output_tokens,
        # we execute the governed tools ourselves — disable the SDK's auto-calling
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Content(role="user", parts=[types.Part.from_text(
        text="Assess this alert and produce your recommended maintenance plan.")])]
    trace, executed = [], {}
    for _ in range(6):
        resp = gemini.generate(client, model=provider.model_id, contents=contents, config=cfg)
        cand = (resp.candidates or [None])[0]
        if not cand or not cand.content:
            break
        contents.append(cand.content)
        responses = []
        for part in (cand.content.parts or []):
            if getattr(part, "text", None) and part.text.strip():
                trace.append({"actor": "agent", "title": "Reasoning", "text": part.text.strip()})
            fc = getattr(part, "function_call", None)
            if fc:
                result = _dispatch(fc.name, dict(fc.args or {}), ctx)
                executed[fc.name] = result
                trace.append({"actor": "tool", "title": f"{fc.name}()", "tool": fc.name,
                              "text": _tool_text(fc.name, result), "result": {}})
                payload = result if isinstance(result, dict) else {"result": result}
                responses.append(types.Part.from_function_response(name=fc.name, response=payload))
        if responses:
            contents.append(types.Content(role="user", parts=responses))
        else:
            break
    return _merge_llm(baseline, trace, executed, "gemini")


# ---------------------------------------------------------------------------
# Governance peer — consult the policy authority on the assembled plan
# ---------------------------------------------------------------------------
def _governance_text(v: dict) -> str:
    d = v.get("decision")
    if d == "APPROVE":
        return "Governance peer: APPROVED — " + (v["reasons"][0] if v.get("reasons") else "within policy.")
    if d == "CONDITIONS":
        return "Governance peer: APPROVE WITH CONDITIONS — " + "; ".join(v.get("conditions", [])[:2])
    if d == "VETO":
        return "Governance peer: VETO — " + (v["reasons"][0] if v.get("reasons") else "policy violation.")
    return "Governance peer unavailable — proceeding without an automated policy check."


def _apply_governance(proposal: dict) -> None:
    """Attach a governance verdict + a trace step. Best-effort: an unavailable
    peer must never break the loop (governance advises; the human still decides)."""
    try:
        verdict = services.governance().review_plan(proposal)
    except Exception as e:  # noqa: BLE001
        verdict = {"decision": "UNAVAILABLE", "reasons": [f"{type(e).__name__}: {e}"[:120]],
                   "conditions": [], "policy_version": None}
    proposal["governance"] = verdict
    step = {"actor": "agent", "title": f"Governance ruling · {verdict.get('decision')}",
            "text": _governance_text(verdict)}
    trace = proposal.get("trace") or []
    trace.insert(max(len(trace) - 1, 0), step)  # just before the final Recommendation
    proposal["trace"] = trace


_ENHANCERS = {"gemini": _enhance_with_gemini, "bedrock": _enhance_with_bedrock}


def decide(ctx: dict) -> dict:
    """Entry point per alert. Build the deterministic baseline, then (optionally)
    enhance with the active LLM provider's tool-calling loop, then consult the
    governance peer. Never raises — any provider failure keeps the baseline."""
    proposal = build_proposal(ctx)
    mode = config.agent_mode()
    enhancer = _ENHANCERS.get(mode)
    if enhancer is not None:
        try:
            proposal = enhancer(proposal, ctx)
        except Exception as e:  # noqa: BLE001 — demo must never crash
            from .providers.errors import normalize_exception
            err = normalize_exception(e, provider=mode)
            proposal["llm_error"] = (f"{err.code}: {err}" if err else f"{type(e).__name__}: {e}")[:200]
    elif mode != "deterministic":
        proposal["llm_note"] = f"{mode} has no legacy tool-calling loop; deterministic baseline kept"
    _apply_governance(proposal)
    return proposal
