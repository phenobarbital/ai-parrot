"""G4 smoke — one provider, three turns complete (opt-in, real LLM)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PARROT_SPIKE") != "1" or os.environ.get("PARROT_TEST_REAL_LLM") != "1",
    reason="spike: set PARROT_SPIKE=1 and PARROT_TEST_REAL_LLM=1",
)
SPIKE = Path(__file__).resolve().parents[4] / "sdd/state/FEAT-746/spikes/G4-mount-prompt-cache/spike.py"


def _load_spike():
    """Load the isolated spike without making it a production package."""
    spec = importlib.util.spec_from_file_location("g4_spike", SPIKE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load spike at {SPIKE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_three_turns_complete() -> None:
    """Configured providers complete the baseline, repeat, and mount turns."""
    results = asyncio.run(_load_spike().main_async())
    assert results, "configure at least one Anthropic, OpenAI, or Google provider"
    assert all(len(result["turns"]) == 3 for result in results)
    assert all(result["turns"][2]["tool_count"] == 9 for result in results)
