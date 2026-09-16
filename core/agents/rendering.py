"""Model-facing rendering of trusted application context.

The context an agent receives is the validated ``SpecialistContext`` (or
``DiagnosticContext``); what is *sent* is a compact JSON view of exactly that
object. Nothing the model must cite, ground on or review is removed: durable IDs,
kinds, quality, provenance, observation times, summaries, hashes and full payload
content stay, and every evidence record still validates as an ``Evidence`` on its
own. What goes is optional application bookkeeping the model cannot use
(dependency fingerprints, collection keys, schema version tags) and, inside
payloads, values that merely repeat an enclosing record (a reading's asset,
sensor and unit already stated by its series). Every provider receives the same
view, so cloud and local runs reason over identical content; the payload
compaction is lossless under one convention stated in the message itself: a
field absent from a nested record inherits the nearest enclosing value.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

# Optional bookkeeping on evidence envelopes; never model input. Required Evidence
# fields (hashes, locators, timestamps) stay so the record remains self-validating.
BOOKKEEPING_KEYS = frozenset({"schema_version", "request_id", "collection_key", "source_state_hash",
                              "source_dependencies"})
# Optional lineage fields shown only when they carry a value.
OPTIONAL_KEYS = frozenset({"derived_from_ids", "supersedes_id"})
INHERITANCE_NOTE = "inside payloads, a field absent from a nested record inherits the nearest enclosing value"


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def compact(value: Any, inherited: dict[str, Any] | None = None) -> Any:
    """Return the compact model-facing view of a JSON-compatible value."""
    inherited = inherited or {}
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        scope = dict(inherited)
        for key, item in value.items():
            if key in BOOKKEEPING_KEYS:
                continue
            if key in OPTIONAL_KEYS and not item:
                continue
            if _is_scalar(item) and key in inherited and inherited[key] == item:
                continue
            if _is_scalar(item):
                scope[key] = item
        for key, item in value.items():
            if key in BOOKKEEPING_KEYS or (key in OPTIONAL_KEYS and not item):
                continue
            if _is_scalar(item):
                if key in inherited and inherited[key] == item:
                    continue
                out[key] = item
            else:
                out[key] = compact(item, scope)
        return out
    if isinstance(value, (list, tuple)):
        return [compact(item, inherited) for item in value]
    return value


# Context sections rendered verbatim: bounded advisory reports and the exact
# artifacts (draft, diagnosis, verdict) a specialist must review unchanged.
VERBATIM_SECTIONS = frozenset({"artifacts", "advisory_inputs"})


def payload_view(payload: dict[str, Any]) -> dict[str, Any]:
    """A payload with its own top level intact (typed payloads stay valid) and nested repeats removed."""
    scope = {key: item for key, item in payload.items() if _is_scalar(item) and key != "schema_version"}
    return {key: (item if _is_scalar(item) else compact(item, scope))
            for key, item in payload.items() if key != "schema_version"}


def evidence_view(record: dict[str, Any], inherited: dict[str, Any] | None = None) -> dict[str, Any]:
    """One evidence record: optional bookkeeping dropped, payload compacted, required fields kept."""
    out = {key: item for key, item in record.items()
           if key not in BOOKKEEPING_KEYS and not (key in OPTIONAL_KEYS and not item)}
    if isinstance(out.get("payload"), dict):
        out["payload"] = payload_view(out["payload"])
    return out


def context_view(context: dict[str, Any]) -> dict[str, Any]:
    """Compact view of one (Diagnostic|Specialist)Context dump: evidence is compacted, the rest kept."""
    out: dict[str, Any] = {}
    for key, item in context.items():
        if key == "schema_version":
            continue
        # Evidence is compacted; VERBATIM_SECTIONS and scalars pass through unchanged.
        out[key] = [evidence_view(record) for record in item] if key == "evidence" else item
    return out


def _is_context(value: Any) -> bool:
    return isinstance(value, dict) and {"incident_id", "run_id", "evidence"} <= set(value)


def model_view(value: Any) -> Any:
    """JSON-compatible compact view of a context, a dict holding one, or plain data."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        value = {key: (item.model_dump(mode="json") if isinstance(item, BaseModel) else item)
                 for key, item in value.items()}
        if _is_context(value):
            return context_view(value)
        return {key: (context_view(item) if _is_context(item) else item) for key, item in value.items()}
    return value


def model_message(value: Any) -> str:
    """The user message for an agent invocation: the compact view plus its one convention."""
    view = model_view(value)
    if isinstance(view, dict):
        view = {"_note": INHERITANCE_NOTE, **view}
    return json.dumps(view, separators=(",", ":"), ensure_ascii=False)


def estimate_message_chars(value: Any) -> int:
    return len(model_message(value))


def parse_model_message(text: str) -> dict[str, Any]:
    """The compact view back as a dict (without the convention note)."""
    view = json.loads(text)
    if isinstance(view, dict):
        view.pop("_note", None)
    return view


def context_from_message(text: str) -> dict[str, Any]:
    """The context dump behind a rendered message (the supervisor wraps it under ``context``).

    Every evidence record in the view still validates as ``Evidence``; only its payload
    is the compact rendering. Audit/test aid, never used on the model path.
    """
    view = parse_model_message(text)
    return view["context"] if "context" in view and _is_context(view["context"]) else view
