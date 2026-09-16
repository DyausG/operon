"""Structured, secret-safe transition logging and Fast Path latency instrumentation."""
from __future__ import annotations

import json
import logging
import statistics

logger = logging.getLogger("operon.prism")
_SECRET_MARKERS = ("api_key", "apikey", "secret", "token", "authorization", "password", "credential")


def scrub(value):
    """Drop anything that looks like a credential and truncate long strings."""
    if isinstance(value, dict):
        return {k: ("[redacted]" if any(m in str(k).lower() for m in _SECRET_MARKERS) else scrub(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    if isinstance(value, str) and len(value) > 300:
        return value[:300] + "…"
    return value


def log_transition(event: str, *, level: int = logging.INFO, **fields) -> dict:
    record = {"event": event, **{k: v for k, v in fields.items() if v is not None}}
    record = scrub(record)
    logger.log(level, "prism_transition=%s", json.dumps(record, sort_keys=True, default=str))
    return record


def latency_summary(samples: list[float]) -> dict:
    if not samples:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None, "last_ms": None}
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return {"count": len(samples), "p50_ms": round(statistics.median(ordered), 3),
            "p95_ms": round(ordered[p95_index], 3), "max_ms": round(ordered[-1], 3), "last_ms": round(samples[0], 3)}
