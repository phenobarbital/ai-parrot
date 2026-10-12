"""Unit tests for CompositeEvaluator (TASK-4238)."""

import pytest

from parrot.eval.evaluators.base import Metric
from parrot.eval.evaluators.composite import CompositeEvaluator
from parrot.eval.models import EvalTask, MetricScore, Trajectory
from parrot.eval.registry import get_evaluator


class _Const(Metric):
    def __init__(self, name, value, passed):
        self.name, self._v, self._p = name, value, passed

    async def score(self, task, trajectory, sandbox=None):
        return MetricScore(name=self.name, value=self._v, passed=self._p)


class _Raises(Metric):
    name = "broken"

    async def score(self, task, trajectory, sandbox=None):
        raise RuntimeError("boom")


def _task():
    return EvalTask(task_id="t", inputs={})


def _trajectory():
    return Trajectory(task_id="t", attempt=1, final_output="answer")


def test_registered():
    assert get_evaluator("composite") is CompositeEvaluator


async def test_required_overrides_threshold():
    evaluator = CompositeEvaluator([_Const("a", 0.8, False), _Const("b", 1.0, True)], required={"a"}, threshold=0.5)
    result = await evaluator.evaluate(_task(), _trajectory())
    assert result.passed is False
    assert sum(score.value for score in result.scores) / 2 == 0.9


async def test_weights_and_passed_none():
    evaluator = CompositeEvaluator([_Const("a", 0.5, None), _Const("b", 1.0, True)], weights={"a": 3}, threshold=0.6)
    result = await evaluator.evaluate(_task(), _trajectory())
    assert result.passed is True


async def test_metric_exception_recorded():
    result = await CompositeEvaluator([_Raises()], threshold=1.0).evaluate(_task(), _trajectory())
    assert result.passed is False
    assert result.scores[0].value == 0.0
    assert result.scores[0].passed is False
    assert result.scores[0].detail["error"] == "boom"


def test_empty_metrics_raises():
    with pytest.raises(ValueError, match="at least one metric"):
        CompositeEvaluator([])
