"""Deterministic reference-based text metrics (FEAT-652, Module 2).

``exact_match`` / ``contains`` / ``token_f1`` score ``trajectory.final_output``
against ``task.expected`` — no LLM anywhere in this module.
"""

from __future__ import annotations

import re
import string
from collections import Counter
from typing import Literal

from parrot.eval.evaluators.base import Metric
from parrot.eval.models import EvalTask, MetricScore, Trajectory
from parrot.eval.registry import register_metric
from parrot.eval.sandbox.base import Sandbox

_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def normalize_text(text: str, *, casefold: bool = True, strip_punct: bool = True) -> str:
    """Casefold, strip ASCII punctuation and collapse whitespace."""
    out = text.casefold() if casefold else text
    if strip_punct:
        out = out.translate(_PUNCT_TABLE)
    return " ".join(out.split())


def _expected_answers(task: EvalTask, key: str = "answer") -> list[str]:
    """Return ``task.expected[key]`` as a list of strings (``[]`` when missing)."""
    raw = (task.expected or {}).get(key)
    if raw is None:
        return []
    return [str(item) for item in raw] if isinstance(raw, (list, tuple)) else [str(raw)]


def _output_text(trajectory: Trajectory) -> str:
    """Coerce a trajectory output to text for scoring."""
    return "" if trajectory.final_output is None else str(trajectory.final_output)


def _missing(name: str, key: str) -> MetricScore:
    """Return the standard scored failure for a missing expected value."""
    return MetricScore(name=name, value=0.0, passed=False, detail={"reason": f"expected.{key} missing"})


@register_metric("exact_match")
class ExactMatch(Metric):
    """1.0 iff the normalized output equals any accepted answer; passed == (value == 1.0)."""

    name = "exact_match"

    def __init__(self, *, casefold: bool = True, strip_punct: bool = True) -> None:
        self._casefold = casefold
        self._strip_punct = strip_punct

    async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore:
        """Score the final output against any accepted exact answer."""
        answers = _expected_answers(task)
        if not answers:
            return _missing(self.name, "answer")
        output = normalize_text(_output_text(trajectory), casefold=self._casefold, strip_punct=self._strip_punct)
        normalized_answers = [
            normalize_text(answer, casefold=self._casefold, strip_punct=self._strip_punct) for answer in answers
        ]
        matched = next(
            (answer for answer, normalized in zip(answers, normalized_answers, strict=True) if normalized == output),
            None,
        )
        value = 1.0 if matched is not None else 0.0
        return MetricScore(
            name=self.name,
            value=value,
            passed=value == 1.0,
            detail={"matched": matched, "normalized_output": output},
        )


@register_metric("contains")
class ContainsMatch(Metric):
    """Fraction of ``expected["must_contain"]`` found in the output; passed by ``mode`` ("all" | "any")."""

    name = "contains"

    def __init__(self, *, mode: Literal["all", "any"] = "all", regex: bool = False, ignore_case: bool = True) -> None:
        self._mode = mode
        self._regex = regex
        self._flags = re.IGNORECASE if ignore_case else 0

    async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore:
        """Score the fraction of required substrings or patterns found in the output."""
        needles = _expected_answers(task, "must_contain")
        if not needles:
            return _missing(self.name, "must_contain")
        output = _output_text(trajectory)
        if self._regex:
            try:
                found = [needle for needle in needles if re.search(needle, output, self._flags) is not None]
            except re.error as exc:
                return MetricScore(name=self.name, value=0.0, passed=False, detail={"error": f"invalid regex: {exc}"})
        else:
            normalized_output = normalize_text(output)
            # A needle that normalizes to "" (e.g. "?") would match everything; it never counts as found.
            found = [
                needle
                for needle in needles
                if (normalized := normalize_text(needle)) and normalized in normalized_output
            ]
        missing = [needle for needle in needles if needle not in found]
        value = len(found) / len(needles)
        passed = all(needle in found for needle in needles) if self._mode == "all" else bool(found)
        return MetricScore(name=self.name, value=value, passed=passed, detail={"found": found, "missing": missing})


@register_metric("token_f1")
class TokenF1(Metric):
    """SQuAD-style token F1 vs. the best accepted answer; passed == value >= threshold."""

    name = "token_f1"

    def __init__(self, *, threshold: float = 0.5) -> None:
        self._threshold = threshold

    @staticmethod
    def _f1(pred: list[str], ref: list[str]) -> float:
        """Return the SQuAD-style token F1 for two token sequences."""
        if not pred and not ref:
            return 1.0
        if not pred or not ref:
            return 0.0
        common = sum((Counter(pred) & Counter(ref)).values())
        precision = common / len(pred)
        recall = common / len(ref)
        return 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None = None) -> MetricScore:
        """Score the final output against the best token-overlap answer."""
        answers = _expected_answers(task)
        if not answers:
            return _missing(self.name, "answer")
        pred = normalize_text(_output_text(trajectory)).split()
        best = max(self._f1(pred, normalize_text(answer).split()) for answer in answers)
        return MetricScore(
            name=self.name,
            value=best,
            passed=best >= self._threshold,
            detail={"threshold": self._threshold, "candidates": len(answers)},
        )
