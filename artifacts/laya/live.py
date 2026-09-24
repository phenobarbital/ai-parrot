"""Live-mode guards for the Laya evaluation: preflight, logical-call cap, model evidence (spec §2)."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from parrot.models.responses import AIMessage  # verified: packages/ai-parrot/src/parrot/models/responses.py:75

from artifacts.laya.models import EvaluationCase, EvaluationConfig, RouteDecision, SampleResult

API_KEY_ENV = "ANTHROPIC_API_KEY"  # verified: client.py:173 — the client itself reads this name


class LivePreflightError(ValueError):
    """Live configuration incomplete; ``error_code`` is always ``live_config_missing``."""

    error_code = "live_config_missing"


def preflight_live(config: EvaluationConfig, env: Mapping[str, str] | None = None) -> None:
    """Reject a live run before any request when model IDs, cap or API key are missing (spec §2).

    Raises:
        LivePreflightError: listing every missing input at once.
    """
    if not config.live:
        return
    env = os.environ if env is None else env
    missing: list[str] = []
    if not config.primary_api_model:
        missing.append("--primary-api-model")
    if not config.cheap_api_model:
        missing.append("--cheap-api-model")
    if config.max_live_calls <= 0:
        missing.append("--max-live-calls (> 0)")
    if not env.get(API_KEY_ENV):
        missing.append(f"{API_KEY_ENV} (environment)")
    if missing:
        raise LivePreflightError(f"live mode requires: {', '.join(missing)}")


class LiveCallBudget:
    """Cap on logical ``Agent.ask`` calls across both arms, failed calls included (spec §2)."""

    NOT_A_MONEY_CAP = "logical-call cap: not an HTTP-attempt or money cap (client retries/fallback may add requests)"

    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self.used = 0

    @property
    def remaining(self) -> int:
        return self.max_calls - self.used

    def reserve(self) -> bool:
        """Reserve one slot BEFORE dispatch; False when exhausted (-> ``call_cap_reached``)."""
        if self.remaining <= 0:
            return False
        self.used += 1
        return True

    def reserve_pair(self) -> bool:
        """Reserve two slots atomically; a pair never starts with one slot left (spec §2)."""
        if self.remaining < 2:
            return False
        self.used += 2
        return True


class ModelEvidence(BaseModel):
    """What we can prove about which model answered (spec §2 'Record requested, selected, reported and provider-returned')."""

    model_config = ConfigDict(extra="forbid")
    requested_model: str | None
    reported_model: str | None  # AIMessage.model — NOT proof (factory echoes the request)
    actual_model: str | None  # raw_response["model"] when available
    verified: bool
    mismatch: bool
    fallback_metadata: dict[str, Any] | None
    usage: dict[str, Any] | None
    error_code: str | None  # "model_unverified" when actual_model is None


def extract_model_evidence(message: AIMessage, requested_model: str | None) -> ModelEvidence:
    """Prefer the raw provider model; keep fallback metadata separate; never substitute or 'correct' anything."""
    raw = message.raw_response if isinstance(message.raw_response, dict) else None
    actual = raw.get("model") if raw and isinstance(raw.get("model"), str) else None
    meta = message.metadata or {}
    fallback = {k: meta[k] for k in ("used_fallback_model", "original_model", "fallback_model") if k in meta} or None
    usage = message.usage.model_dump() if message.usage else None
    return ModelEvidence(
        requested_model=requested_model,
        reported_model=message.model,
        actual_model=actual,
        verified=actual is not None,
        mismatch=bool(actual and requested_model and actual != requested_model),
        fallback_metadata=fallback,
        usage=usage,
        error_code=None if actual else "model_unverified",
    )


def load_rubrics(path: Path) -> dict[str, dict[str, Any]]:
    """Load ``routing_rubrics.json`` ({case_id: {"exact_answer": str} | {"required_facts": [str]}})."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for case_id, rubric in data.items():
        if ("exact_answer" in rubric) == ("required_facts" in rubric):
            raise ValueError(f"rubric {case_id!r} must have exactly one of exact_answer / required_facts")
    return data


def _norm(text: str) -> str:
    """Normalize text for rubric comparison: collapse whitespace, strip, casefold."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def rubric_pass(answer: str, rubric: dict[str, Any] | None) -> bool | None:
    """Exact normalized match or all required facts present; None when no rubric exists."""
    if rubric is None:
        return None
    if "exact_answer" in rubric:
        return _norm(answer) == _norm(str(rubric["exact_answer"]))
    return all(_norm(str(fact)) in _norm(answer) for fact in rubric["required_facts"])


async def _arm_sample(
    agent: Any,
    case: EvaluationCase,
    arm: str,
    decision: RouteDecision,
    config: EvaluationConfig,
    rubric: dict[str, Any] | None,
) -> SampleResult:
    """One logical call → one SampleResult; provider errors are recorded, never substituted."""
    t0 = time.perf_counter()
    base = dict(
        case_id=case.id,
        scenario="routing",
        repeat=0,
        arm=arm,
        expected=case.expected,
        decision=decision,
        requested_model=decision.selected_model,
        selected_model=decision.selected_model,
    )
    try:
        message = await agent.ask_routed(
            case.state,
            decision,
            session_id=f"{case.id}:{arm}",
            max_tokens=config.max_output_tokens,
            temperature=0.0,
        )
    except Exception as exc:  # provider/model error: record with the stable code (spec §2)
        return SampleResult(
            status="error",
            error_code="provider_error",
            timings_ms={"llm_ms": (time.perf_counter() - t0) * 1000.0},
            answer=f"{type(exc).__name__}: {exc}",
            **base,
        )
    llm_ms = (time.perf_counter() - t0) * 1000.0
    evidence = extract_model_evidence(message, decision.selected_model)
    answer = message.response if isinstance(message.response, str) else str(message.output)
    return SampleResult(
        status="ok",
        predicted=decision.choice,
        error_code=evidence.error_code,
        timings_ms={"llm_ms": llm_ms},
        reported_model=evidence.reported_model,
        actual_model=evidence.actual_model,
        fallback_metadata=evidence.fallback_metadata,
        usage=evidence.usage,
        answer=answer,
        quality_pass=rubric_pass(answer, rubric),
        **base,
    )


async def run_live_routing_pairs(
    agent: Any,
    cases: Sequence[EvaluationCase],
    decisions: dict[str, RouteDecision],
    config: EvaluationConfig,
    budget: LiveCallBudget,
    rubrics: dict[str, dict[str, Any]],
) -> list[SampleResult]:
    """Primary-only vs routed call per case, two slots reserved BEFORE dispatch; stop at the cap (spec §2)."""
    primary_decision = RouteDecision(
        choice="primary", selected_model=config.primary_api_model, confidence=None, reason="primary_arm"
    )
    samples: list[SampleResult] = []
    for case in cases:
        decision = decisions.get(case.id)
        if decision is None:
            continue
        if not budget.reserve_pair():
            samples.append(
                SampleResult(
                    case_id=case.id,
                    scenario="routing",
                    repeat=0,
                    arm="primary",
                    expected=case.expected,
                    status="error",
                    error_code="call_cap_reached",
                    decision=decision,
                )
            )
            break
        rubric = rubrics.get(case.id)
        samples.append(await _arm_sample(agent, case, "primary", primary_decision, config, rubric))
        samples.append(await _arm_sample(agent, case, "routed", decision, config, rubric))
    return samples
