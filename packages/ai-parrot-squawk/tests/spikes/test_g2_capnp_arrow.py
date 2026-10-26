"""G2 regression: an opt-in mTLS Arrow IPC cancellation spike."""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("PARROT_SPIKE") != "1", reason="spike: set PARROT_SPIKE=1")
pytest.importorskip("capnp")
SPIKE = Path(__file__).resolve().parents[4] / "sdd/state/FEAT-746/spikes/G2-capnp-arrow/spike.py"


def _load():
    """Load the isolated spike without turning it into a production package."""
    spec = importlib.util.spec_from_file_location("g2_spike", SPIKE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load spike at {SPIKE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cancel_leaves_valid_partial() -> None:
    """Cancellation leaves a sequence of independently readable Arrow streams."""
    g2 = _load()
    try:
        out = asyncio.run(g2.run(80_000, cancel_at_frame=1))
    except PermissionError as exc:
        if exc.errno == 1:
            pytest.skip("the current sandbox forbids loopback socket binding")
        raise
    assert out["status"] == "PARTIAL"
    assert out["frames_valid"] is True
    assert out["peer_san"] == "squawk://external/caller"
    assert out["hello_token_observed"] is True
