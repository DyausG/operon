"""``./demo.sh``: syntax, check mode, secret hygiene. Never starts services."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "demo.sh"
bash = shutil.which("bash")
pytestmark = pytest.mark.skipif(bash is None, reason="bash is required to exercise demo.sh")


def test_launcher_is_executable_and_parses():
    assert SCRIPT.is_file() and os.access(SCRIPT, os.X_OK)
    assert subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True, text=True).returncode == 0
    text = SCRIPT.read_text()
    for forbidden in ("apt-get", "brew install", "ollama pull", "curl -fsSL https://ollama", "aws configure"):
        assert forbidden not in text, forbidden
    assert "docs/DEMO.md" in text and "Press Ctrl+C to stop" in text and "trap" in text


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required for demo.sh --check")
def test_check_mode_reports_provider_without_secrets_and_starts_nothing():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("OPERON_", "SENTINEL_", "AWS_", "GEMINI", "GOOGLE", "POC_FORCE"))}
    env |= {"GEMINI_API_KEY": "fake-launcher-key-should-never-print-12345", "OPERON_AI_PROVIDER": "gemini",
            "TERM": "dumb", "POC_PORT": "8999"}
    result = subprocess.run([bash, str(SCRIPT), "--check", "--no-sync"], cwd=ROOT, env=env, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "Checking environment" in out and "AI provider" in out
    assert "Google Gemini selected" in out and "API key present (server-side)" in out
    assert "fake-launcher-key" not in out and "fake-launcher-key" not in result.stderr
    assert "nothing started" in out
