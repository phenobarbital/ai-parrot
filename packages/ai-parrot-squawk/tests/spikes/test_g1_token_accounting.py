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
    """At the descriptor cap the payload stays under 250 tokens on every available tokenizer."""
    g1 = _load()
    df = g1.build_frame()
    for digits in (None, 3):
        tokens = g1.count_tokens(g1.descriptor_payload(df, preview_rows=3, summary_chars=1000, float_digits=digits))
        assert tokens["heuristic_len4"] < 250
        if "tiktoken_cl100k" in tokens:
            assert tokens["tiktoken_cl100k"] < 250


def test_preview_rows_are_budget_bound():
    """The preview keeps only the rows that fit; a 12-column frame keeps one row at 1000 chars."""
    g1 = _load()
    df = g1.build_frame()
    kept = len(g1.descriptor_summary(df, preview_rows=5, summary_chars=1000)["preview"])
    assert kept == 1
