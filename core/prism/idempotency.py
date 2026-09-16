"""Request identity normalization for operator messages.

``request_id`` identifies one transport request; ``idempotency_key`` identifies the
logical operator intent. A replayed frame (same key) never creates a second turn,
revision or Slow Path run: the repository's unique index on (session, key) makes the
deduplication durable and the ``BEGIN IMMEDIATE`` acceptance transaction makes it
atomic under concurrency. When the client sends no key the request id is the key,
so retried requests dedupe too. Effect idempotency lives in the effect ledger
(``PrismRepository.begin_effect``), keyed by (session, revision, key).
"""
from __future__ import annotations

import re
from uuid import uuid4

IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class InvalidIdentity(ValueError):
    pass


def validate_identity(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not IDENTITY_PATTERN.match(value):
        raise InvalidIdentity(f"{field} must match {IDENTITY_PATTERN.pattern}")
    return value


def normalize_request(request_id: str | None, idempotency_key: str | None) -> tuple[str, str]:
    request_id = validate_identity(request_id, field="request_id") if request_id else str(uuid4())
    key = validate_identity(idempotency_key, field="idempotency_key") if idempotency_key else request_id
    return request_id, key
