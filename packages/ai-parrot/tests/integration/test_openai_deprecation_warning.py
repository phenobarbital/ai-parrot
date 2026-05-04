"""Integration tests for OpenAI model deprecation warnings.

Spec: sdd/specs/openai-model-deprecation.spec.md §4
Implements: TASK-942
"""
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "packages/ai-parrot/src/parrot"


def test_no_internal_call_site_uses_deprecated_id():
    """No .py file under src/parrot/ (except models/openai.py) should contain
    known-deprecated model literal strings."""
    forbidden = ["gpt-4-turbo", "gpt-3.5-turbo", "gpt-5-chat-latest"]
    cmd = [
        "grep", "-rn", "--include=*.py",
        "--exclude-dir=__pycache__",
        "-E", "|".join(forbidden),
        str(SRC),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # Allow only matches inside models/openai.py (the registry):
    bad = [
        ln for ln in result.stdout.splitlines()
        if "models/openai.py" not in ln
    ]
    assert not bad, "Found deprecated model literals:\n" + "\n".join(bad)


def test_openai_client_warns_on_deprecated_call():
    """Constructing OpenAIClient with a deprecated model must emit DeprecationWarning."""
    from parrot.clients import gpt as gpt_mod
    gpt_mod._warned.clear()
    with pytest.warns(DeprecationWarning, match="deprecated"):
        gpt_mod.OpenAIClient(api_key="dummy", model="gpt-4-turbo")
