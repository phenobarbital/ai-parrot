"""LLMJudgeMetric — rubric-based LLM-as-judge with cache and self-consistency (FEAT-652, Module 5)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

from parrot.eval.evaluators.base import Metric
from parrot.eval.judge import JudgeCache, JudgeVerdict, Rubric, judge_cache_key
from parrot.eval.models import EvalTask, MetricScore, Trajectory
from parrot.eval.registry import register_metric
from parrot.eval.rollout import _extract_question, _extract_text
from parrot.eval.sandbox.base import Sandbox

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

logger = logging.getLogger(__name__)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.IGNORECASE)


def _parse_verdict(response: Any) -> JudgeVerdict | None:
    """JudgeVerdict from structured output or JSON response text; None if neither parses."""
    structured = getattr(response, "structured_output", None)
    if isinstance(structured, JudgeVerdict):
        return structured
    if isinstance(structured, dict):
        try:
            return JudgeVerdict.model_validate(structured)
        except Exception:
            return None

    text = _extract_text(response) or ""
    fenced = _FENCE.search(text)
    candidate = fenced.group(1) if fenced else text
    try:
        return JudgeVerdict.model_validate(json.loads(candidate.strip()))
    except Exception:
        return None


@register_metric("llm_judge")
class LLMJudgeMetric(Metric):
    """Judge ``final_output`` against a ``Rubric`` with a pinned judge model."""

    name = "llm_judge"

    def __init__(
        self,
        client: "AbstractClient",
        *,
        judge_model: str,
        rubric: Rubric,
        cache: JudgeCache | None = None,
        n_samples: int = 1,
        model_under_test: str | None = None,
        max_tokens: int = 1024,
    ) -> None:
        if model_under_test is not None and judge_model == model_under_test:
            raise ValueError("judge_model must differ from model_under_test (FEAT-217 D4)")
        if n_samples < 1:
            raise ValueError("n_samples must be >= 1")
        self._client = client
        self._judge_model = judge_model
        self._rubric = rubric
        self._cache = cache
        self._n_samples = n_samples
        self._max_tokens = max_tokens

    def build_prompt(self, task: EvalTask, answer: str) -> str:
        """Render the question, expected answer, candidate answer, and rubric as strict JSON instructions."""
        sections = [f"QUESTION:\n{_extract_question(task)}"]
        if task.expected is not None:
            sections.append(f"EXPECTED:\n{json.dumps(task.expected, ensure_ascii=False, sort_keys=True)}")
        sections.append(f"ANSWER:\n{answer}")
        criteria = "\n".join(f"- {criterion.name} — {criterion.question}" for criterion in self._rubric.criteria)
        sections.append(f"CRITERIA:\n{criteria}")
        sections.append(
            'Reply ONLY with JSON {"criteria": {"<name>": true|false, ...}, '
            '"rationale": "<one sentence>"}.'
        )
        return "\n\n".join(sections)

    @staticmethod
    def _merge(verdicts: list[JudgeVerdict], rubric: Rubric) -> JudgeVerdict:
        """Majority vote per criterion; ties and missing criteria resolve to False."""
        criteria: dict[str, bool] = {}
        for criterion in rubric.criteria:
            true_votes = sum(1 for verdict in verdicts if verdict.criteria.get(criterion.name, False))
            criteria[criterion.name] = true_votes > len(verdicts) / 2
        rationale = next((verdict.rationale for verdict in verdicts if verdict.rationale), "")
        return JudgeVerdict(criteria=criteria, rationale=rationale)

    async def _ask_once(self, prompt: str) -> JudgeVerdict | None:
        response = await self._client.ask(
            prompt,
            model=self._judge_model,
            temperature=0.0,
            max_tokens=self._max_tokens,
            structured_output=JudgeVerdict,
        )
        return _parse_verdict(response)

    async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore:
        """Score a trajectory with cached, self-consistent rubric judgments."""
        del sandbox
        answer = "" if trajectory.final_output is None else str(trajectory.final_output)
        question = _extract_question(task)
        key = judge_cache_key(
            judge_model=self._judge_model,
            rubric=self._rubric,
            question=question,
            expected=task.expected,
            answer=answer,
        )
        base_detail: dict[str, Any] = {
            "judge_model": self._judge_model,
            "rubric": f"{self._rubric.name}@{self._rubric.version}",
            "model_under_test": trajectory.model,
            "samples": self._n_samples,
        }
        try:
            verdict = await self._cache.get(key) if self._cache is not None else None
            cached = verdict is not None
            if verdict is None:
                prompt = self.build_prompt(task, answer)
                samples = await asyncio.gather(*(self._ask_once(prompt) for _ in range(self._n_samples)))
                parsed = [sample for sample in samples if sample is not None]
                if not parsed:
                    return MetricScore(
                        name=self.name,
                        value=0.0,
                        passed=False,
                        detail={**base_detail, "error": "judge output unparseable"},
                    )
                verdict = self._merge(parsed, self._rubric)
                if self._cache is not None:
                    await self._cache.set(
                        key,
                        verdict,
                        judge_model_version=self._judge_model,
                        rubric_version=self._rubric.version,
                    )
        except Exception as exc:
            logger.warning("llm_judge failed for task %s: %s", task.task_id, exc)
            return MetricScore(name=self.name, value=0.0, passed=False, detail={**base_detail, "error": str(exc)})

        value = sum(verdict.criteria.get(criterion.name, False) for criterion in self._rubric.criteria) / len(
            self._rubric.criteria
        )
        return MetricScore(
            name=self.name,
            value=value,
            passed=value >= self._rubric.pass_threshold,
            detail={**base_detail, "verdict": verdict.model_dump(), "cached": cached},
        )
