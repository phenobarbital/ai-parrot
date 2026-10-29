"""G6 regression — round-trip, deduplication, and DLQ on the memory fallback."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("PARROT_SPIKE") != "1", reason="spike: set PARROT_SPIKE=1")
SPIKE = Path(__file__).resolve().parents[4] / "sdd/state/FEAT-746/spikes/G6-bus-envelope/spike.py"


def test_roundtrip_and_dedup_memory_backend() -> None:
    """Round-trip one-megabyte and binary payloads while dropping a duplicate call."""
    spec = importlib.util.spec_from_file_location("g6_spike", SPIKE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load spike at {SPIKE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    output = asyncio.run(module.run(None))

    assert output["backend"] == "memory"
    assert output["executed"] == 2
    assert output["dlq"] == [{"topic": "squawk:caller:replies:undeliverable", "attempts": 1}]
    assert output["base64_overhead_pct"] > 33
