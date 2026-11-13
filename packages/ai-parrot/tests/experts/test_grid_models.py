"""Tests for scope grid models."""
import pytest
from pydantic import ValidationError

from parrot.experts.grid import (
    ExpertStageConfig,
    ScopeGrid,
    ScopeGridError,
    ScopeGridErrorCode,
    ScopeMatch,
)


def test_subagent_single_expert():
    ExpertStageConfig(stage="a", experts=["x"], mode="subagent")
    with pytest.raises(ValidationError):
        ExpertStageConfig(stage="a", experts=["x", "y"], mode="subagent")


def test_experts_non_empty():
    with pytest.raises(ValidationError):
        ExpertStageConfig(stage="a", experts=[], mode="mob")


def test_inline_requires_conductor():
    with pytest.raises(ValidationError):
        ExpertStageConfig(stage="a", experts=["x"], mode="inline")
    s = ExpertStageConfig(stage="a", experts=["x"], mode="inline", conductor="c")
    assert s.conductor == "c"


def test_unique_stage_names():
    st = ExpertStageConfig(stage="a", experts=["x"], mode="pipeline")
    with pytest.raises(ValidationError):
        ScopeGrid(scope="s", stages=[st, st])
    g = ScopeGrid(scope="s", match=ScopeMatch(tags=["t"]), stages=[st])
    assert g.match.tags == ["t"]


def test_grid_requires_stages():
    with pytest.raises(ValidationError):
        ScopeGrid(scope="s", stages=[])


def test_error_code():
    e = ScopeGridError(ScopeGridErrorCode.CYCLE, "boom")
    assert e.code is ScopeGridErrorCode.CYCLE
    assert str(e) == "CYCLE: boom"
