"""G5 regression — attenuated token allowed on hr.reports.*, refused on hr.people.* (opt-in)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PARROT_SPIKE") != "1",
    reason="spike: set PARROT_SPIKE=1",
)
pytest.importorskip("biscuit_auth")
SPIKE = (
    Path(__file__).resolve().parents[4]
    / "sdd/state/FEAT-746/spikes/G5-biscuit-attenuation/spike.py"
)


def test_issue_attenuate_refuse() -> None:
    """Test that the spike runs and returns 0 (all cases pass)."""
    spec = importlib.util.spec_from_file_location("g5_spike", SPIKE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load spike at {SPIKE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0