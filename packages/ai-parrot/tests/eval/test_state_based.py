"""Unit tests for StateBasedEvaluator + StateMatch metric (TASK-1422)."""
import pytest

from parrot.eval import StateBasedEvaluator, StateMatch
from parrot.eval.models import EvalTask, Trajectory
from parrot.eval.registry import get_evaluator, get_metric


async def test_subset_pass_ignores_extra():
    """State with extra fields beyond goal_state still passes."""
    task = EvalTask(
        task_id="t",
        inputs={},
        expected={"goal_state": {"issues": {"P-1": {"assignee": "oncall"}}}},
    )
    tr = Trajectory(
        task_id="t",
        attempt=1,
        final_state={"issues": {"P-1": {"assignee": "oncall", "title": "Bug"}}},
    )
    result = await StateBasedEvaluator().evaluate(task, tr)
    assert result.passed


async def test_mismatch_fails():
    """Wrong field value in goal_state causes failure."""
    task = EvalTask(
        task_id="t",
        inputs={},
        expected={"goal_state": {"issues": {"P-1": {"assignee": "oncall"}}}},
    )
    tr = Trajectory(
        task_id="t",
        attempt=1,
        final_state={"issues": {"P-1": {"assignee": "wrong"}}},
    )
    result = await StateBasedEvaluator().evaluate(task, tr)
    assert not result.passed
    assert result.scores[0].detail["mismatches"]


async def test_forbidden_fails():
    """Forbidden entity present in final_state causes failure."""
    task = EvalTask(
        task_id="t",
        inputs={},
        expected={"goal_state": {}, "forbidden": {"issues": ["P-9"]}},
    )
    tr = Trajectory(
        task_id="t",
        attempt=1,
        final_state={"issues": {"P-9": {"a": 1}}},
    )
    result = await StateBasedEvaluator().evaluate(task, tr)
    assert result.passed is False
    assert result.scores[0].detail["forbidden_present"]


async def test_empty_goal_state_passes():
    """Empty goal_state (no assertions) → passes."""
    task = EvalTask(task_id="t", inputs={}, expected={"goal_state": {}})
    tr = Trajectory(task_id="t", attempt=1, final_state={"issues": {"P-1": {"x": 1}}})
    result = await StateBasedEvaluator().evaluate(task, tr)
    assert result.passed
    assert result.scores[0].value == 1.0


async def test_no_expected_passes():
    """Missing expected → no assertions → evaluator passes."""
    task = EvalTask(task_id="t", inputs={})
    tr = Trajectory(task_id="t", attempt=1, final_state={})
    result = await StateBasedEvaluator().evaluate(task, tr)
    assert result.passed


async def test_missing_entity_fails():
    """Entity listed in goal_state but missing from final_state fails."""
    task = EvalTask(
        task_id="t",
        inputs={},
        expected={"goal_state": {"issues": {"MISSING": {"status": "done"}}}},
    )
    tr = Trajectory(task_id="t", attempt=1, final_state={"issues": {}})
    result = await StateBasedEvaluator().evaluate(task, tr)
    assert not result.passed
    assert any("entity not found" in str(m) for m in result.scores[0].detail["mismatches"])


async def test_registry_resolves_state_based():
    """@register_evaluator('state_based') registered the class."""
    cls = get_evaluator("state_based")
    assert cls is StateBasedEvaluator


async def test_registry_resolves_state_match():
    """@register_metric('state_match') registered the class."""
    cls = get_metric("state_match")
    assert cls is StateMatch


async def test_partial_score():
    """Partial goal match produces value between 0 and 1."""
    task = EvalTask(
        task_id="t",
        inputs={},
        expected={
            "goal_state": {
                "issues": {
                    "P-1": {"assignee": "oncall"},
                    "P-2": {"assignee": "alice"},
                }
            }
        },
    )
    tr = Trajectory(
        task_id="t",
        attempt=1,
        final_state={
            "issues": {
                "P-1": {"assignee": "oncall"},
                "P-2": {"assignee": "wrong"},
            }
        },
    )
    result = await StateBasedEvaluator().evaluate(task, tr)
    assert not result.passed
    assert 0.0 < result.scores[0].value < 1.0


async def test_uses_final_state_not_sandbox():
    """Evaluator uses trajectory.final_state without calling sandbox.snapshot()."""

    class NoCallSandbox:
        async def snapshot(self):
            raise AssertionError("snapshot() should not be called")

    task = EvalTask(
        task_id="t",
        inputs={},
        expected={"goal_state": {"items": {"i1": {"v": 1}}}},
    )
    tr = Trajectory(task_id="t", attempt=1, final_state={"items": {"i1": {"v": 1}}})
    # sandbox.snapshot() must NOT be called — final_state is already set
    result = await StateBasedEvaluator().evaluate(task, tr, sandbox=NoCallSandbox())
    assert result.passed
