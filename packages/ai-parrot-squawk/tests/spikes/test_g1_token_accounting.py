"""G1 regression — descriptor path stays under 250 heuristic tokens (opt-in)."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("PARROT_SPIKE") != "1", reason="spike: set PARROT_SPIKE=1")
SPIKE = Path(__file__).resolve().parents[4] / "sdd/state/FEAT-746/spikes/G1-token-accounting/spike.py"


def _load():
    spec = importlib.util.spec_from_file_location("g1_spike", SPIKE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_descriptor_under_250_tokens():
    g1 = _load()
    df = g1.build_frame()
    # Use the caps frozen in report.md: preview_rows=3, summary_chars=1000
    tokens = g1.count_tokens(g1.descriptor_payload(df, preview_rows=3, summary_chars=1000))
    assert tokens["heuristic_len4"] < 250
