"""CompositeEvaluator — combine any registered metrics (FEAT-652, Module 2)."""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping, Sequence

from parrot.eval.evaluators.base import AbstractEvaluator, Metric
from parrot.eval.models import EvalResult, EvalTask, MetricScore, Trajectory
from parrot.eval.registry import register_evaluator
from parrot.eval.sandbox.base import Sandbox

logger = logging.getLogger(__name__)


@register_evaluator("composite")
class CompositeEvaluator(AbstractEvaluator):
    """Run metrics and apply required and weighted-threshold pass semantics."""

    def __init__(
        self,
        metrics: Sequence[Metric],
        *,
        required: Collection[str] = (),
        threshold: float = 1.0,
        weights: Mapping[str, float] | None = None,
    ) -> None:
        if not metrics:
            raise ValueError("CompositeEvaluator needs at least one metric")
        names = [metric.name for metric in metrics]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"CompositeEvaluator metrics must have unique names; duplicated: {duplicates}")
        unknown = sorted((set(required) | set(weights or {})) - set(names))
        if unknown:
            raise ValueError(f"CompositeEvaluator required/weights reference unknown metrics: {unknown}")
        self._metrics = list(metrics)
        self._required = set(required)
        self._threshold = threshold
        self._weights = dict(weights or {})

    async def evaluate(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> EvalResult:
        """Evaluate all metrics, recording an individual failure on exceptions."""
        scores: list[MetricScore] = []
        for metric in self._metrics:
            try:
                scores.append(await metric.score(task, trajectory, sandbox))
            except Exception as exc:  # one broken metric must not abort the run
                logger.warning("metric %s failed on task %s: %s", metric.name, task.task_id, exc)
                scores.append(MetricScore(name=metric.name, value=0.0, passed=False, detail={"error": str(exc)}))

        weighted_total = sum(score.value * self._weights.get(score.name, 1.0) for score in scores)
        total_weight = sum(self._weights.get(score.name, 1.0) for score in scores)
        weighted_mean = weighted_total / total_weight if total_weight else 0.0
        required_ok = all(score.passed is not False for score in scores if score.name in self._required)
        passed = required_ok and weighted_mean >= self._threshold
        return EvalResult(
            task_id=task.task_id,
            attempt=trajectory.attempt,
            scores=scores,
            passed=passed,
            trajectory=trajectory,
        )
