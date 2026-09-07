"""
Shared Google Gemini plumbing — one place for the client, the rate limiter, and
the backoff wrapper so the agent's tool-calling loop AND the LLM-backed peers
(Governance/Monitoring) share a single free-tier budget.

Everything here degrades gracefully: callers are expected to fall back to a
deterministic path if a call raises (rate-limited past retries, no key, etc.).
"""
from __future__ import annotations
import json
import random
import threading
import time

from . import config


class RateLimiter:
    """Thread-safe token bucket. Allows a small burst, then paces sustained calls
    to stay under `rpm` requests/minute. Shared across the agent and the peers so
    the whole app respects one free-tier quota."""
    def __init__(self, rpm: int):
        self.capacity = max(1, min(rpm, 6))
        self.tokens = float(self.capacity)
        self.refill_per_sec = max(rpm, 1) / 60.0
        self.lock = threading.Lock()
        self.last = time.monotonic()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.refill_per_sec)
                self.last = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.refill_per_sec
            time.sleep(min(max(wait, 0.05), 5.0))


# One limiter for the whole process (agent tool-calls + peer calls share it).
LIMITER = RateLimiter(config.GEMINI_RPM)


def is_transient(e: Exception) -> bool:
    code = getattr(e, "code", None)
    return code in (429, 500, 502, 503, 504) or "RESOURCE_EXHAUSTED" in str(e) \
        or "overloaded" in str(e).lower()


def get_client():
    """A Gemini client bound to the configured API key. Raises if unavailable."""
    from google import genai
    return genai.Client(api_key=config.GEMINI_API_KEY)


def generate(client, **kwargs):
    """One rate-limited generate_content call with exponential backoff + jitter on
    transient 429/5xx. Non-transient errors (bad key, bad request) raise at once."""
    delay = 1.0
    for attempt in range(config.GEMINI_MAX_RETRIES + 1):
        LIMITER.acquire()
        try:
            return client.models.generate_content(**kwargs)
        except Exception as e:  # noqa: BLE001
            if not is_transient(e) or attempt >= config.GEMINI_MAX_RETRIES:
                raise
            time.sleep(min(delay + random.uniform(0, 0.75), 30.0))
            delay *= 2


def structured_json(system: str, user: str) -> dict:
    """Ask Gemini for a JSON object (no tools) and parse it. Raises on any failure
    so the caller can fall back deterministically."""
    from google.genai import types
    client = get_client()
    resp = generate(
        client,
        model=config.GEMINI_MODEL_ID,
        contents=[types.Content(role="user", parts=[types.Part.from_text(text=user)])],
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            max_output_tokens=config.GEMINI_MAX_TOKENS,
            response_mime_type="application/json",
        ),
    )
    return json.loads((resp.text or "").strip())
