"""Unit tests for EvalRunner + EvalReport (TASK-1425)."""
import asyncio
import pytest
from unittest.mock import AsyncMock

from parrot.eval import (
    EvalDataset,
    EvalReport,
    EvalRunConfig,
    EvalRunner,
    EvalTask,
    StateBasedEvaluator,
    Trajectory,
)
from parrot.eval.evaluators.base import AbstractEvaluator
from parrot.eval.models import EvalResult, MetricScore
from parrot.eval.rollout import RolloutStrategy
from parrot.eval.sandbox.base import NoopSandbox, NoopSandboxProvider, SandboxSpec


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class AlwaysPassEvaluator(AbstractEvaluator):
    """Always returns passed=True."""

    async def evaluate(self, task, trajectory, sandbox=None):
        return EvalResult(
            task_id=task.task_id,
            attempt=trajectory.attempt,
            scores=[MetricScore(name="dummy", value=1.0, passed=True)],
            passed=True,
            trajectory=trajectory,
        )


class AlwaysFailEvaluator(AbstractEvaluator):
    """Always returns passed=False."""

    async def evaluate(self, task, trajectory, sandbox=None):
        return EvalResult(
            task_id=task.task_id,
            attempt=trajectory.attempt,
            scores=[MetricScore(name="dummy", value=0.0, passed=False)],
            passed=False,
            trajectory=trajectory,
        )


class FlipFlopEvaluator(AbstractEvaluator):
    """Passes on attempt 1, fails on attempt 2+."""

    async def evaluate(self, task, trajectory, sandbox=None):
        passed = trajectory.attempt == 1
        return EvalResult(
            task_id=task.task_id,
            attempt=trajectory.attempt,
            scores=[MetricScore(name="dummy", value=1.0 if passed else 0.0, passed=passed)],
            passed=passed,
            trajectory=trajectory,
        )


class NoopRollout(RolloutStrategy):
    """Rollout that returns an empty trajectory immediately."""

    async def run(self, bot, task, sandbox):
        return Trajectory(task_id=task.task_id, attempt=0, final_output="done")


async def _fake_agent_factory(sandbox):
    return AsyncMock()


def _make_dataset(*task_ids: str) -> EvalDataset:
    return EvalDataset(
        name="test",
        tasks=[EvalTask(task_id=t, inputs={"query": "x"}) for t in task_ids],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_runner_basic_pass_k1():
    """With k=1, all tasks pass → pass_k = 1.0."""
    ds = _make_dataset("t1", "t2")
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent_factory,
        rollout=NoopRollout(),
        evaluator=AlwaysPassEvaluator(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=1),
    )
    report = await runner.run()
    assert report.pass_k == 1.0
    assert report.pass_at_1 == 1.0
    assert len(report.results) == 2


async def test_runner_all_fail():
    """All tasks fail → pass_k = 0.0."""
    ds = _make_dataset("t1", "t2")
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent_factory,
        rollout=NoopRollout(),
        evaluator=AlwaysFailEvaluator(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=1),
    )
    report = await runner.run()
    assert report.pass_k == 0.0


async def test_runner_pass_k_all_must_pass():
    """pass^k = fraction of tasks where ALL k attempts pass.
    FlipFlopEvaluator passes attempt-1 but fails attempt-2, so pass^k=0.
    """
    ds = _make_dataset("t1")
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent_factory,
        rollout=NoopRollout(),
        evaluator=FlipFlopEvaluator(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=2),
    )
    report = await runner.run()
    # pass^k=0 because attempt-2 fails
    assert report.pass_k == 0.0
    # pass@1 = 1.0 because attempt-1 passes
    assert report.pass_at_1 == 1.0
    # Raw trajectories retained
    assert len(report.results) == 2


async def test_runner_retains_trajectories():
    """Raw trajectories are retained in report.results."""
    ds = _make_dataset("t1")
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent_factory,
        rollout=NoopRollout(),
        evaluator=AlwaysPassEvaluator(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=3),
    )
    report = await runner.run()
    assert len(report.results) == 3
    assert all(r.trajectory is not None for r in report.results)


async def test_runner_setup_latency_recorded():
    """setup_latency_ms is recorded separately from rollout latency."""
    ds = _make_dataset("t1")
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent_factory,
        rollout=NoopRollout(),
        evaluator=AlwaysPassEvaluator(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=1),
    )
    report = await runner.run()
    assert report.results[0].trajectory.setup_latency_ms >= 0.0


async def test_runner_per_tag_breakdown():
    """per_tag contains pass^k grouped by task tags."""
    tasks = [
        EvalTask(task_id="t1", inputs={"query": "x"}, tags=["db"]),
        EvalTask(task_id="t2", inputs={"query": "x"}, tags=["db", "jira"]),
    ]
    ds = EvalDataset(name="test", tasks=tasks)
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent_factory,
        rollout=NoopRollout(),
        evaluator=AlwaysPassEvaluator(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=1),
    )
    report = await runner.run()
    assert "db" in report.per_tag
    assert "jira" in report.per_tag
    assert report.per_tag["db"] == 1.0
    assert report.per_tag["jira"] == 1.0


async def test_runner_attempt_failure_isolated():
    """A failing attempt is recorded as failed result; other tasks continue."""

    class BombFirst(AbstractEvaluator):
        """Raises on task_id='boom', passes otherwise."""

        call_count = 0

        async def evaluate(self, task, trajectory, sandbox=None):
            BombFirst.call_count += 1
            if task.task_id == "boom":
                raise RuntimeError("explosion")
            return EvalResult(
                task_id=task.task_id,
                attempt=trajectory.attempt,
                scores=[],
                passed=True,
                trajectory=trajectory,
            )

    BombFirst.call_count = 0
    ds = _make_dataset("safe", "boom")
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent_factory,
        rollout=NoopRollout(),
        evaluator=BombFirst(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=1, fail_fast=False),
    )
    report = await runner.run()
    # Both tasks executed (fail_fast=False)
    assert len(report.results) == 2
    safe_result = next(r for r in report.results if r.task_id == "safe")
    boom_result = next(r for r in report.results if r.task_id == "boom")
    assert safe_result.passed
    assert not boom_result.passed
    assert boom_result.trajectory.error is not None


async def test_runner_empty_dataset():
    """Empty dataset → pass_k=None (no tasks) or 0 tasks processed."""
    ds = EvalDataset(name="empty", tasks=[])
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent_factory,
        rollout=NoopRollout(),
        evaluator=AlwaysPassEvaluator(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=1),
    )
    report = await runner.run()
    assert report.total_tasks == 0
    assert report.results == []
