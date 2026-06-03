"""Abstract base classes for evaluation metrics and evaluators.

FEAT-217 — Module 6.  These ABCs define the scoring contract — the
polymorphic point of the harness.  Concrete implementations register
themselves via ``@register_metric`` / ``@register_evaluator``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from parrot.eval.models import EvalResult, EvalTask, MetricScore, Trajectory
from parrot.eval.sandbox.base import Sandbox

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Metric ABC
# ---------------------------------------------------------------------------


class Metric(ABC):
    """Abstract base for a single evaluation metric.

    A ``Metric`` computes a normalized score for one (task, trajectory) pair.
    Concrete subclasses are registered via ``@register_metric(name)`` and
    stored in the metric registry.

    Attributes:
        name: Registry name of this metric (e.g. ``"state_match"``).
    """

    name: str

    @abstractmethod
    async def score(
        self,
        task: EvalTask,
        trajectory: Trajectory,
        sandbox: Sandbox | None = None,
    ) -> MetricScore:
        """Compute a metric score for *trajectory* on *task*.

        Args:
            task: The evaluation task (inputs + expected/goal state).
            trajectory: The recorded agent trajectory.
            sandbox: Live sandbox, if available (enables re-scoring without
                re-running; prefer ``trajectory.final_state`` when set).

        Returns:
            ``MetricScore`` with a normalized ``value`` in ``[0.0, 1.0]``
            and an optional ``passed`` flag.
        """
        ...


# ---------------------------------------------------------------------------
# AbstractEvaluator ABC
# ---------------------------------------------------------------------------


class AbstractEvaluator(ABC):
    """Abstract base for evaluators that combine one or more metrics.

    An ``AbstractEvaluator`` aggregates metric scores into a single
    ``EvalResult``.  Concrete subclasses are registered via
    ``@register_evaluator(name)``.
    """

    @abstractmethod
    async def evaluate(
        self,
        task: EvalTask,
        trajectory: Trajectory,
        sandbox: Sandbox | None = None,
    ) -> EvalResult:
        """Evaluate *trajectory* against *task* and return a scored result.

        Args:
            task: The evaluation task (inputs + expected/goal state).
            trajectory: The recorded agent trajectory.
            sandbox: Live sandbox, if the final state has not been captured
                yet (``trajectory.final_state is None``).

        Returns:
            ``EvalResult`` with per-metric scores and an overall
            ``passed`` flag.
        """
        ...
