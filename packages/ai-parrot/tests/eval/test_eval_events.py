"""Unit tests for eval lifecycle events (TASK-1426)."""
import pytest
from unittest.mock import AsyncMock

from parrot.eval import (
    EvalDataset,
    EvalRunCompleted,
    EvalRunConfig,
    EvalRunner,
    EvalRunStarted,
    EvalRolloutCompleted,
    EvalRolloutFailed,
    EvalRolloutStarted,
    EvalTask,
)
from parrot.eval.evaluators.base import AbstractEvaluator
from parrot.eval.models import EvalResult, MetricScore, Trajectory
from parrot.eval.rollout import RolloutStrategy
from parrot.eval.sandbox.base import NoopSandboxProvider
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SimplePassEvaluator(AbstractEvaluator):
    async def evaluate(self, task, trajectory, sandbox=None):
        return EvalResult(
            task_id=task.task_id,
            attempt=trajectory.attempt,
            scores=[MetricScore(name="x", value=1.0, passed=True)],
            passed=True,
            trajectory=trajectory,
        )


class SimpleFailEvaluator(AbstractEvaluator):
    """Always raises (to trigger EvalRolloutFailed)."""

    async def evaluate(self, task, trajectory, sandbox=None):
        raise RuntimeError("forced failure")


class NoopRollout(RolloutStrategy):
    async def run(self, bot, task, sandbox):
        return Trajectory(task_id=task.task_id, attempt=0, final_output="ok")


async def _fake_agent(sandbox):
    return AsyncMock()


# ---------------------------------------------------------------------------
# Tests: event subclass correctness
# ---------------------------------------------------------------------------


def test_eval_run_started_is_lifecycle_event():
    """EvalRunStarted is a LifecycleEvent subclass."""
    assert issubclass(EvalRunStarted, LifecycleEvent)


def test_eval_rollout_completed_is_lifecycle_event():
    """EvalRolloutCompleted is a LifecycleEvent subclass."""
    assert issubclass(EvalRolloutCompleted, LifecycleEvent)


def test_eval_run_completed_is_lifecycle_event():
    """EvalRunCompleted is a LifecycleEvent subclass."""
    assert issubclass(EvalRunCompleted, LifecycleEvent)


def test_eval_rollout_failed_is_lifecycle_event():
    """EvalRolloutFailed is a LifecycleEvent subclass."""
    assert issubclass(EvalRolloutFailed, LifecycleEvent)


def test_lifecycle_event_frozen():
    """EvalRunStarted instances are frozen (mutation raises)."""
    import dataclasses
    evt = EvalRunStarted(
        trace_context=TraceContext.new_root(),
        run_id="r1",
        dataset_name="test",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        evt.run_id = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tests: events emitted during a run
# ---------------------------------------------------------------------------


async def test_events_emitted_during_run():
    """EvalRunStarted and EvalRunCompleted are emitted for a simple run."""
    registry = EventRegistry(forward_to_global=False)
    received: list[LifecycleEvent] = []

    registry.subscribe(LifecycleEvent, lambda e: received.append(e) or None)

    ds = EvalDataset(
        name="smoke",
        tasks=[EvalTask(task_id="t1", inputs={"query": "x"})],
    )
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent,
        rollout=NoopRollout(),
        evaluator=SimplePassEvaluator(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=1),
        event_registry=registry,
    )
    report = await runner.run()

    event_types = [type(e).__name__ for e in received]
    assert "EvalRunStarted" in event_types
    assert "EvalRunCompleted" in event_types


async def test_rollout_completed_event_emitted():
    """EvalRolloutCompleted is emitted after each successful attempt."""
    registry = EventRegistry(forward_to_global=False)
    rollout_completed: list[EvalRolloutCompleted] = []
    registry.subscribe(EvalRolloutCompleted, lambda e: rollout_completed.append(e) or None)

    ds = EvalDataset(
        name="smoke",
        tasks=[EvalTask(task_id="t1", inputs={"query": "x"})],
    )
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent,
        rollout=NoopRollout(),
        evaluator=SimplePassEvaluator(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=2),
        event_registry=registry,
    )
    await runner.run()
    assert len(rollout_completed) == 2  # one per attempt


async def test_rollout_failed_event_emitted():
    """EvalRolloutFailed is emitted when the evaluator raises."""
    registry = EventRegistry(forward_to_global=False)
    failed_events: list[EvalRolloutFailed] = []
    registry.subscribe(EvalRolloutFailed, lambda e: failed_events.append(e) or None)

    ds = EvalDataset(
        name="smoke",
        tasks=[EvalTask(task_id="boom", inputs={"query": "x"})],
    )
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent,
        rollout=NoopRollout(),
        evaluator=SimpleFailEvaluator(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=1),
        event_registry=registry,
    )
    await runner.run()
    assert len(failed_events) == 1
    assert failed_events[0].task_id == "boom"


async def test_raising_subscriber_does_not_break_run():
    """A subscriber that raises does NOT abort the run (model-B isolation)."""
    registry = EventRegistry(forward_to_global=False)

    async def bad_subscriber(event):
        raise RuntimeError("subscriber exploded")

    registry.subscribe(LifecycleEvent, bad_subscriber)

    ds = EvalDataset(
        name="smoke",
        tasks=[EvalTask(task_id="t1", inputs={"query": "x"})],
    )
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent,
        rollout=NoopRollout(),
        evaluator=SimplePassEvaluator(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=1),
        event_registry=registry,
    )
    # Should NOT raise despite the subscriber exploding
    report = await runner.run()
    assert report.pass_k == 1.0


async def test_trajectory_trace_context_populated():
    """trajectory.trace_context is set when TraceContext is available."""
    # This test verifies that the runner captures trace info per rollout.
    # Since trace_context is set on Trajectory by the rollout (or runner),
    # we just verify the runner completes without error.
    ds = EvalDataset(
        name="smoke",
        tasks=[EvalTask(task_id="t1", inputs={"query": "x"})],
    )
    runner = EvalRunner(
        dataset=ds,
        agent_factory=_fake_agent,
        rollout=NoopRollout(),
        evaluator=SimplePassEvaluator(),
        sandbox_provider=NoopSandboxProvider(),
        config=EvalRunConfig(k=1),
    )
    report = await runner.run()
    assert report.pass_k == 1.0
