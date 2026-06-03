"""State-based evaluator and metric for the Generic Agent Evaluation Harness.

FEAT-217 — Module 7.

``StateMatch``
    Metric that does a subset diff of the final world state against the
    annotated ``goal_state``.  Only keys present in ``goal_state`` are
    asserted; extra state the agent touched is ignored.  Score =
    ``matched_assertions / total_assertions``.

``StateBasedEvaluator``
    Evaluator that runs ``StateMatch`` and optionally checks ``forbidden``
    entities.  ``passed`` iff all goal assertions hold AND no forbidden
    entity is present.
"""
from __future__ import annotations

import logging
from typing import Any

from parrot.eval.evaluators.base import AbstractEvaluator, Metric
from parrot.eval.models import EvalResult, EvalTask, MetricScore, Trajectory
from parrot.eval.registry import register_evaluator, register_metric
from parrot.eval.sandbox.base import Sandbox

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# StateMatch metric
# ---------------------------------------------------------------------------


@register_metric("state_match")
class StateMatch(Metric):
    """Subset-match metric comparing final state to ``goal_state``.

    Scoring:
        ``value = matched_assertions / total_assertions``
        Each ``{collection, entity_id, field}`` triple in ``goal_state``
        is one assertion unit.  A missing collection/entity or a wrong
        field value counts as a mismatch.

    ``passed``:
        ``True`` iff all goal assertions match AND no ``forbidden``
        entity is present in the final state.

    ``detail``:
        ``{"mismatches": [...], "forbidden_present": [...]}``

    The evaluator prefers ``trajectory.final_state`` over a live
    ``sandbox.snapshot()`` so re-scoring works fully offline (spec D5).
    """

    name = "state_match"

    async def score(
        self,
        task: EvalTask,
        trajectory: Trajectory,
        sandbox: Sandbox | None = None,
    ) -> MetricScore:
        """Compute the state-match score.

        Args:
            task: Eval task with ``expected`` dict containing optional
                ``goal_state`` and ``forbidden`` keys.
            trajectory: The recorded agent trajectory; ``final_state``
                used when available.
            sandbox: Live sandbox (fallback if ``final_state`` is ``None``).

        Returns:
            ``MetricScore`` for the ``"state_match"`` metric.
        """
        # --- Obtain final state ---
        final: dict[str, Any] | None = trajectory.final_state
        if final is None and sandbox is not None:
            final = await sandbox.snapshot()
        if final is None:
            final = {}

        expected = task.expected or {}
        goal_state: dict[str, Any] = expected.get("goal_state", {}) or {}
        forbidden: dict[str, Any] | None = expected.get("forbidden")

        mismatches: list[dict[str, Any]] = []
        total_assertions = 0
        matched_assertions = 0

        # --- Subset diff ---
        for collection, entities in goal_state.items():
            if not isinstance(entities, dict):
                continue
            for entity_id, expected_fields in entities.items():
                if not isinstance(expected_fields, dict):
                    continue
                actual_collection = final.get(collection, {})
                actual_entity = actual_collection.get(entity_id)

                if actual_entity is None:
                    # Entity missing — all fields for this entity are mismatches
                    for field_name, expected_val in expected_fields.items():
                        total_assertions += 1
                        mismatches.append({
                            "path": f"{collection}.{entity_id}.{field_name}",
                            "expected": expected_val,
                            "actual": None,
                            "reason": "entity not found",
                        })
                    continue

                for field_name, expected_val in expected_fields.items():
                    total_assertions += 1
                    actual_val = actual_entity.get(field_name)
                    if actual_val == expected_val:
                        matched_assertions += 1
                    else:
                        mismatches.append({
                            "path": f"{collection}.{entity_id}.{field_name}",
                            "expected": expected_val,
                            "actual": actual_val,
                        })

        # --- Forbidden check ---
        forbidden_present: list[str] = []
        if forbidden:
            for collection, entity_ids in forbidden.items():
                if not isinstance(entity_ids, list):
                    continue
                actual_collection = final.get(collection, {})
                for eid in entity_ids:
                    if eid in actual_collection:
                        forbidden_present.append(f"{collection}.{eid}")

        # --- Scoring ---
        if total_assertions == 0:
            # No assertions → full score (nothing to violate)
            value = 1.0
        else:
            value = matched_assertions / total_assertions

        passed = (len(mismatches) == 0) and (len(forbidden_present) == 0)

        return MetricScore(
            name=self.name,
            value=value,
            passed=passed,
            detail={
                "mismatches": mismatches,
                "forbidden_present": forbidden_present,
                "total_assertions": total_assertions,
                "matched_assertions": matched_assertions,
            },
        )


# ---------------------------------------------------------------------------
# StateBasedEvaluator
# ---------------------------------------------------------------------------


@register_evaluator("state_based")
class StateBasedEvaluator(AbstractEvaluator):
    """Evaluator for state-based (τ-bench style) agent tasks.

    Uses a single ``StateMatch`` metric: diff the post-rollout world
    against the annotated ``goal_state`` + ``forbidden`` in
    ``task.expected``.

    Scoring is path-independent — only the final world state matters, not
    the sequence of tool calls that produced it.  Re-scoring is fully
    offline when ``trajectory.final_state`` is populated.
    """

    def __init__(self) -> None:
        self._metric = StateMatch()

    async def evaluate(
        self,
        task: EvalTask,
        trajectory: Trajectory,
        sandbox: Sandbox | None = None,
    ) -> EvalResult:
        """Evaluate the trajectory using state-match scoring.

        Args:
            task: Eval task with ``expected.goal_state`` and optional
                ``expected.forbidden``.
            trajectory: The recorded agent trajectory.
            sandbox: Live sandbox (fallback if ``final_state`` is ``None``).

        Returns:
            ``EvalResult`` with the ``"state_match"`` score and
            ``passed`` reflecting all goal assertions + forbidden check.
        """
        score = await self._metric.score(task, trajectory, sandbox)
        return EvalResult(
            task_id=task.task_id,
            attempt=trajectory.attempt,
            scores=[score],
            passed=bool(score.passed),
            trajectory=trajectory,
        )
