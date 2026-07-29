"""Eval lifecycle events for the Generic Agent Evaluation Harness.

FEAT-217 — Module 11.

These events extend the FEAT-176 ``LifecycleEvent`` taxonomy with a new
orchestration-layer scope.  They are read-only (observers cannot abort a
run) and follow the model-B error-isolation guarantee of ``EventRegistry``
(subscribers that raise do NOT propagate exceptions into the runner).

Events are emitted via ``EventRegistry.emit()``; dual-emit to ``EventBus``
is per-subscriber opt-in (``forward_to_bus=True`` in ``subscribe()``).

One eval run = one distributed trace.  ``TraceContext.new_root()`` is
created at run start; ``TraceContext.child()`` is used per rollout attempt.
"""
from __future__ import annotations

from dataclasses import dataclass

from parrot.core.events.lifecycle import LifecycleEvent


# ---------------------------------------------------------------------------
# EvalRunStarted
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalRunStarted(LifecycleEvent):
    """Emitted when ``EvalRunner.run()`` begins.

    Attributes:
        run_id: Unique identifier for the evaluation run.
        dataset_name: Name of the dataset being evaluated.
        k: Number of attempts configured per task.
        total_tasks: Number of tasks in the dataset.
    """

    run_id: str = ""
    dataset_name: str = ""
    k: int = 1
    total_tasks: int = 0


# ---------------------------------------------------------------------------
# EvalRolloutStarted
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalRolloutStarted(LifecycleEvent):
    """Emitted just before a (task, attempt) rollout begins.

    Attributes:
        run_id: The parent run identifier.
        task_id: The task being evaluated.
        attempt: Attempt index (1-based).
    """

    run_id: str = ""
    task_id: str = ""
    attempt: int = 1


# ---------------------------------------------------------------------------
# EvalRolloutCompleted
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalRolloutCompleted(LifecycleEvent):
    """Emitted after a (task, attempt) rollout completes successfully.

    Attributes:
        run_id: The parent run identifier.
        task_id: The evaluated task.
        attempt: Attempt index (1-based).
        passed: Whether the evaluator marked this attempt as passed.
        latency_ms: Rollout wall-clock time in milliseconds.
        setup_latency_ms: Agent setup time in milliseconds.
    """

    run_id: str = ""
    task_id: str = ""
    attempt: int = 1
    passed: bool = False
    latency_ms: float = 0.0
    setup_latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# EvalRolloutFailed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalRolloutFailed(LifecycleEvent):
    """Emitted when a (task, attempt) rollout raises an exception.

    The run continues (model-B isolation); the failed attempt is recorded
    as a failed ``EvalResult``.

    Attributes:
        run_id: The parent run identifier.
        task_id: The task that failed.
        attempt: Attempt index (1-based).
        error: String representation of the exception.
    """

    run_id: str = ""
    task_id: str = ""
    attempt: int = 1
    error: str = ""


# ---------------------------------------------------------------------------
# EvalRunCompleted
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalRunCompleted(LifecycleEvent):
    """Emitted when ``EvalRunner.run()`` finishes (whether or not all tasks
    passed).

    Attributes:
        run_id: Unique identifier for the evaluation run.
        dataset_name: Name of the evaluated dataset.
        pass_k: ``pass^k`` headline metric (fraction of tasks where all k
            attempts passed).  ``None`` if no tasks were evaluated.
        pass_at_1: Mean of attempt-1 pass flags.  ``None`` if no results.
        total_tasks: Total number of tasks.
        total_attempts: Total number of (task, attempt) pairs executed.
    """

    run_id: str = ""
    dataset_name: str = ""
    pass_k: float | None = None
    pass_at_1: float | None = None
    total_tasks: int = 0
    total_attempts: int = 0
