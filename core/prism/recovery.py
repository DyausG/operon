"""Explicit, deterministic restart policy (implemented by ``PrismRepository.recover``).

Policy ``retry_current_revision``:
* the canonical current revision is restored from the session row (nothing is inferred);
* incomplete runs of superseded revisions become SUPERSEDED/CANCELLED history; never revived;
* an interrupted run of the current revision is FAILED("process_restart") and, unless that
  revision already has canonical state, retried as a new attempt (new run_id) for the same
  revision; the retry sees committed effects through the ledger and never repeats them;
* PENDING effects of interrupted runs become UNKNOWN (outcome not observed), never replayed.
Policy ``fail_only`` performs the same classification without scheduling a retry.
"""
from __future__ import annotations

POLICIES: tuple[str, ...] = ("retry_current_revision", "fail_only")
DEFAULT_POLICY = "retry_current_revision"


def describe(report: dict | None) -> str | None:
    if not report:
        return None
    parts = [f"policy {report.get('policy')}"]
    if report.get("superseded_runs"):
        parts.append(f"{len(report['superseded_runs'])} superseded run(s) closed")
    if report.get("retried"):
        parts.append(f"revision retried as attempt {report['retried']['attempt']}")
    if report.get("scheduled"):
        parts.append(f"{len(report['scheduled'])} queued run(s) rescheduled")
    if report.get("unknown_effects"):
        parts.append(f"{len(report['unknown_effects'])} effect(s) marked UNKNOWN")
    return "; ".join(parts)
