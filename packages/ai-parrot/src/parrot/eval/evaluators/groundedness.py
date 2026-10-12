"""GroundednessMetric — offline FEAT-398 scoring over a Trajectory (FEAT-652, Module 3)."""
from __future__ import annotations

import logging

from parrot.eval.evaluators.base import Metric
from parrot.eval.models import EvalTask, MetricScore, Trajectory
from parrot.eval.registry import register_metric
from parrot.eval.rollout import _extract_question
from parrot.eval.sandbox.base import Sandbox
from parrot.models.basic import ToolCall
from parrot.security.groundedness import EvidenceIndex, GroundednessPolicy, GroundednessReport, GroundednessScorer

logger = logging.getLogger(__name__)


def _tool_calls_from_trajectory(trajectory: Trajectory) -> list[ToolCall]:
    """Rebuild ``ToolCall`` objects from every turn's records with stable IDs.

    Args:
        trajectory: Persisted evaluation rollout containing turn records.

    Returns:
        Tool calls rebuilt from all trajectory turns in their recorded order.
    """
    calls: list[ToolCall] = []
    for turn_index, turn in enumerate(trajectory.turns):
        for call_index, record in enumerate(turn.tool_calls):
            calls.append(
                ToolCall(
                    id=f"{turn_index}-{call_index}",
                    name=record.name,
                    arguments=dict(record.arguments),
                    result=record.result,
                    error=record.error,
                    execution_time=(record.latency_ms / 1000.0) if record.latency_ms is not None else None,
                )
            )
    return calls


@register_metric("groundedness")
class GroundednessMetric(Metric):
    """Score final-output hard facts against recorded tool-call evidence.

    ``no_evidence`` and ``no_factual_content`` reports are neutral. Otherwise,
    a result passes only when it meets ``min_score`` and, by default, has no
    contradicted atoms.
    """

    name = "groundedness"

    def __init__(
        self,
        policy: GroundednessPolicy | None = None,
        *,
        min_score: float = 0.8,
        fail_on_contradicted: bool = True,
    ) -> None:
        """Initialize the metric's deterministic scoring policy.

        Args:
            policy: Evidence extraction and groundedness scoring policy.
            min_score: Minimum non-neutral groundedness score that passes.
            fail_on_contradicted: Whether any contradicted atom fails a score.
        """
        self._policy = policy or GroundednessPolicy()
        self._scorer = GroundednessScorer(self._policy)
        self._min_score = min_score
        self._fail_on_contradicted = fail_on_contradicted

    async def score(
        self,
        task: EvalTask,
        trajectory: Trajectory,
        sandbox: Sandbox | None = None,
    ) -> MetricScore:
        """Score the persisted trajectory output against its tool evidence.

        Args:
            task: Evaluation task that supplies the original user prompt.
            trajectory: Persisted rollout to score offline.
            sandbox: Unused live sandbox, accepted for the metric contract.

        Returns:
            A groundedness metric score, or a non-fatal failure score.
        """
        answer = "" if trajectory.final_output is None else str(trajectory.final_output)
        try:
            tool_calls = _tool_calls_from_trajectory(trajectory)
            evidence = EvidenceIndex.from_tool_calls(
                tool_calls,
                self._policy,
                user_prompt=_extract_question(task),
            )
            report: GroundednessReport = self._scorer.score(answer, evidence)
        except Exception as exc:
            logger.warning("groundedness scoring failed for task %s: %s", task.task_id, exc)
            return MetricScore(name=self.name, value=0.0, passed=False, detail={"error": str(exc)})

        detail = report.model_dump() | {
            "no_evidence": report.no_evidence,
            "no_factual_content": report.no_factual_content,
            "tool_call_count": evidence.tool_call_count,
        }
        logger.debug(
            "groundedness score=%.3f supported=%d contradicted=%d unsupported=%d",
            report.score,
            len(report.supported),
            len(report.contradicted),
            len(report.unsupported),
        )
        if report.no_evidence or report.no_factual_content:
            return MetricScore(name=self.name, value=1.0, passed=True, detail=detail)

        passed = report.score >= self._min_score and (
            not self._fail_on_contradicted or not report.contradicted
        )
        return MetricScore(name=self.name, value=report.score, passed=passed, detail=detail)
