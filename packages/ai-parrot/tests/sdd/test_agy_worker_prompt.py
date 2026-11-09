"""FEAT-847 M5 — the Google sdd-worker prompt carries the FEAT-549 loop in agy primitives."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKER = REPO_ROOT / ".agents/agents/sdd-worker/agent.md"
PACKAGED = REPO_ROOT / "packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-worker/agent.md"


@pytest.fixture(scope="module")
def text() -> str:
    return WORKER.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "needle",
    ["invoke_subagent", "manage_subagents", "coder_begin_execution", "coder_plan", "coder_run_chunk",
     "coder_prepare_native", "coder_merge", "coder_end_execution", "Brief Lane", "FEAT-584", 'Model="flash"'],
)
def test_worker_has_agy_orchestrator_loop(text: str, needle: str) -> None:
    assert needle in text


def test_worker_forbidden_patterns(text: str) -> None:
    """Test that forbidden patterns are not present in the worker prompt."""
    forbidden_patterns = [
        "Agent(",
        "TaskStop",
        "subagent_type",
        'Model="haiku"',
        'Model="sonnet"',
        "coder_init_run",
        "coder_next_wave",
        "coder_run_wave",
        "coder_finalize_task",
        "--mode auto"
    ]
    
    for pattern in forbidden_patterns:
        assert pattern not in text, f"Forbidden pattern '{pattern}' found in worker prompt"


def test_fresh_shell_rule(text: str) -> None:
    """Test that every line containing '$WT' also contains 'WT=' (fresh-shell rule)."""
    lines = text.splitlines()
    for line in lines:
        if "$WT" in line:
            assert "WT=" in line, f"Line contains '$WT' but not 'WT=': {line}"


def test_packaged_copy_identical() -> None:
    """Test that the packaged copy is byte-identical to the source."""
    assert WORKER.read_bytes() == PACKAGED.read_bytes()