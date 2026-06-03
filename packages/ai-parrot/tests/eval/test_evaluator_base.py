"""Unit tests for Metric + AbstractEvaluator ABCs (TASK-1421)."""
import pytest

from parrot.eval import AbstractEvaluator, EvalResult, Metric, MetricScore
from parrot.eval.models import EvalTask, Trajectory


async def test_concrete_evaluator_roundtrip():
    """A trivial concrete evaluator can be implemented and awaited."""

    class Trivial(AbstractEvaluator):
        async def evaluate(self, task, trajectory, sandbox=None):
            return EvalResult(
                task_id=task.task_id,
                attempt=trajectory.attempt,
                scores=[],
                passed=True,
                trajectory=trajectory,
            )

    t = EvalTask(task_id="t1", inputs={})
    tr = Trajectory(task_id="t1", attempt=1)
    result = await Trivial().evaluate(t, tr)
    assert result.passed


async def test_concrete_metric_roundtrip():
    """A trivial concrete metric can be implemented and awaited."""

    class AlwaysOne(Metric):
        name = "always_one"

        async def score(self, task, trajectory, sandbox=None):
            return MetricScore(name=self.name, value=1.0, passed=True)

    t = EvalTask(task_id="t1", inputs={})
    tr = Trajectory(task_id="t1", attempt=1)
    score = await AlwaysOne().score(t, tr)
    assert score.value == 1.0
    assert score.passed is True


async def test_abstract_evaluator_cannot_instantiate():
    """AbstractEvaluator cannot be instantiated directly."""
    with pytest.raises(TypeError):
        AbstractEvaluator()  # type: ignore[abstract]


async def test_abstract_metric_cannot_instantiate():
    """Metric cannot be instantiated directly."""
    with pytest.raises(TypeError):
        Metric()  # type: ignore[abstract]


async def test_evaluator_sandbox_optional():
    """AbstractEvaluator.evaluate accepts sandbox=None (no live sandbox needed)."""

    class SandboxCheck(AbstractEvaluator):
        async def evaluate(self, task, trajectory, sandbox=None):
            return EvalResult(
                task_id=task.task_id,
                attempt=trajectory.attempt,
                scores=[],
                passed=(sandbox is None),
                trajectory=trajectory,
            )

    t = EvalTask(task_id="t1", inputs={})
    tr = Trajectory(task_id="t1", attempt=1)
    result = await SandboxCheck().evaluate(t, tr, sandbox=None)
    assert result.passed
