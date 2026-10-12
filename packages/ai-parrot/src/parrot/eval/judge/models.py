"""Rubric / verdict models and the deterministic judge cache key (FEAT-652, Module 4)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field


class JudgeCriterion(BaseModel):
    """One yes/no question the judge answers about an answer."""

    name: str
    question: str


class Rubric(BaseModel):
    """Versioned list of criteria; ``pass_threshold`` is the fraction that must be True."""

    name: str
    version: str
    criteria: list[JudgeCriterion] = Field(min_length=1)
    pass_threshold: float = Field(default=1.0, ge=0.0, le=1.0)


class JudgeVerdict(BaseModel):
    """Per-criterion booleans plus a short rationale."""

    criteria: dict[str, bool]
    rationale: str = ""


# Bump whenever ``LLMJudgeMetric.build_prompt`` changes so stale cached verdicts are never served.
PROMPT_VERSION = "1"


def judge_cache_key(
    *,
    judge_model: str,
    rubric: Rubric,
    question: str,
    expected: Any,
    answer: str,
    prompt_version: str = PROMPT_VERSION,
) -> str:
    """sha256 hex of the canonical JSON of everything that determines a verdict (never the verdict itself)."""
    payload = {
        "judge_model": judge_model,
        "prompt_version": prompt_version,
        "rubric_name": rubric.name,
        "rubric_version": rubric.version,
        "criteria": [[c.name, c.question] for c in rubric.criteria],
        "question": question,
        "expected": expected,
        "answer": answer,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
