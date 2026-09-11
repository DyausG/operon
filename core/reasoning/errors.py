"""Failure type raised at the reasoning seam; never converts into application authority."""
from __future__ import annotations


class ReasoningBackendUnavailable(RuntimeError):
    """The backend produced nothing the application may use for this run.

    ``code`` names the boundary that refused (protocol, correlation, identity,
    result validation or a backend failure code); ``retryable`` is advisory for the
    caller's bounded automatic re-run policy. Raising this never changes a phase:
    ``PromotionService.run_supervisor`` records an ESCALATED/MODEL_FAILED audit
    report and re-raises, exactly as for any other invocation failure.
    """

    def __init__(self, message: str, *, code: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
