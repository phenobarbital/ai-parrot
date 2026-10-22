"""Walkthrough step-3 blocks lower to an envelope that carries the display hints (FEAT-623)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_WALKTHROUGH = Path(__file__).resolve().parents[4] / "examples" / "agents" / "a2ui" / "a2ui_dashboard_walkthrough.py"


@pytest.fixture(scope="module")
def walkthrough():
    if not _WALKTHROUGH.exists():
        pytest.skip("examples/ not available")
    spec = importlib.util.spec_from_file_location("a2ui_dashboard_walkthrough_under_test", _WALKTHROUGH)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(_WALKTHROUGH.parent))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(_WALKTHROUGH.parent))
    return mod


def test_step3_blocks_envelope_carries_hints(walkthrough):
    from parrot.models.infographic import InfographicResponse
    from parrot.outputs.a2ui.adapters import infographic_response_to_envelope

    monthly = walkthrough.build_monthly_metrics()
    plans = walkthrough.build_plan_mix(monthly)
    blocks = walkthrough.step3_blocks(monthly, plans)
    response = InfographicResponse(template=walkthrough.TEMPLATE, blocks=blocks)
    envelope = infographic_response_to_envelope(response)
    root = envelope.components[0].model_dump(by_alias=True, mode="json")
    # exercises the same assertions the walkthrough's step 5 runs
    walkthrough._assert_display_hints(root)
