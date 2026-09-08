"""Unit tests for FEAT-525 budget resolution + calibration math."""

import pytest

from parrot.memory.compaction.models import CompactionCommit, CompactionState
from parrot.memory.compaction import budget as b


@pytest.mark.parametrize(
    "model,window",
    [
        ("claude-sonnet-5", 200_000),
        ("gpt-4.1-mini", 1_047_576),
        ("unknown-x", 32_000),
        (None, 32_000),
        ("", 32_000),
    ],
)
def test_resolve_window(model, window):
    assert b.resolve_window(model) == window


def test_build_default_budget_max_turns_override():
    assert b.build_default_budget("claude-opus-5", max_turns=12).max_turns == 12
    assert b.build_default_budget("claude-opus-5").max_turns == 30


def test_env_kill_switch(monkeypatch):
    monkeypatch.delenv("PARROT_COMPACTION_DISABLED", raising=False)
    assert not b.compaction_disabled_by_env()
    monkeypatch.setenv("PARROT_COMPACTION_DISABLED", "1")
    assert b.compaction_disabled_by_env()


def test_apply_usage_ewma_clamped():
    s0 = CompactionState(tokenizer="heuristic")
    assert b.apply_usage(s0, 0, 100) is s0 and b.apply_usage(s0, 100, None) is s0
    s1 = b.apply_usage(s0, 100, 150)
    assert s1.calibration == pytest.approx(1.5) and s1.samples == 1
    s2 = b.apply_usage(s1, 100, 500)  # ratio 5.0 → 0.2*5 + 0.8*1.5 = 2.2 → clamp 2.0
    assert s2.calibration == 2.0


def test_apply_commit_boundary_and_flag():
    s = b.apply_commit(None, CompactionCommit(100, "t3", False), "heuristic", 120)
    assert s.boundary_turn_id == "t3" and s.stage2_needed is False
    s = b.apply_commit(s, CompactionCommit(100, "t5", True), "heuristic", None)
    s = b.apply_commit(s, CompactionCommit(100, None, False), "heuristic", None)
    assert s.boundary_turn_id == "t5" and s.stage2_needed is True
