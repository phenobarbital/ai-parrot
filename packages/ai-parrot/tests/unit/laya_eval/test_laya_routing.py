"""FEAT-589 M3 — routing fallbacks and request-local model isolation at the dispatch hook."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest

from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage

from artifacts.laya.models import ROUTING_QUESTION_ID, EvaluationConfig, PredictionResult, RouteDecision
from artifacts.laya.routing import _DECISION, LayaEvaluationAgent, choose_route


def _cfg(**kwargs: Any) -> EvaluationConfig:
    base = {
        "worker_python": Path("/bin/python3"),
        "checkpoint_path": Path("/tmp/c"),
        "checkpoint_revision": "r",
        "output_dir": Path("/tmp/o"),
        "primary_api_model": "claude-primary-id",
        "cheap_api_model": "claude-cheap-id",
    }
    base.update(kwargs)
    return EvaluationConfig(**base)


def _res(choice: str, confidence: float) -> PredictionResult:
    probabilities = {candidate: (1.0 if candidate == choice else 0.0) for candidate in ("primary", "cheap", "abstain")}
    return PredictionResult(
        request_id="r",
        status="ok",
        answers={
            ROUTING_QUESTION_ID: {
                "type": "choice",
                "choice": choice,
                "probabilities": probabilities,
                "confidence": confidence,
            }
        },
    )


@pytest.mark.parametrize(
    ("result", "expected_choice", "expected_model", "reason_prefix"),
    [
        (_res("cheap", 0.95), "cheap", "claude-cheap-id", "cheap"),
        (_res("primary", 0.95), "primary", "claude-primary-id", "primary"),
        (_res("abstain", 0.95), "primary", "claude-primary-id", "abstain"),
        (_res("cheap", 0.5), "primary", "claude-primary-id", "low_confidence"),
        (
            PredictionResult(request_id="r", status="error", error_code="inference_timeout", error_message="t"),
            "primary",
            "claude-primary-id",
            "error:inference_timeout",
        ),
        (PredictionResult(request_id="r", status="ok", answers={}), "primary", "claude-primary-id", "invalid_answer"),
    ],
)
def test_choose_route_fallbacks_have_distinct_reasons(
    result: PredictionResult, expected_choice: str, expected_model: str, reason_prefix: str
) -> None:
    decision = choose_route(result, _cfg())
    assert (decision.choice, decision.selected_model) == (expected_choice, expected_model)
    assert decision.reason.startswith(reason_prefix)


def test_choose_route_never_invents_a_model_without_cli_inputs() -> None:
    decision = choose_route(_res("cheap", 0.99), _cfg(primary_api_model=None, cheap_api_model=None))
    assert decision.choice == "cheap"
    assert decision.selected_model is None


class FakeClient:
    """AbstractClient-shaped stub recording every ``ask`` kwargs dictionary."""

    def __init__(self) -> None:
        self.model = "client-default-model"
        self.calls: list[dict[str, Any]] = []

    async def ask(self, **kwargs: Any) -> AIMessage:
        """Record a call and return a minimal framework response."""
        self.calls.append(kwargs)
        await asyncio.sleep(0)
        return AIMessage(
            input=kwargs.get("prompt", ""),
            output="ok",
            model=kwargs.get("model") or self.model,
            provider="fake",
            usage=CompletionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def _agent(client: FakeClient) -> LayaEvaluationAgent:
    agent = LayaEvaluationAgent.__new__(LayaEvaluationAgent)
    agent.logger = logging.getLogger("test")
    agent._llm = client
    agent.name = "laya-eval"
    return agent


async def test_unbound_decision_leaves_parent_behaviour_unchanged() -> None:
    client = FakeClient()
    await _agent(client).execute_llm_call(client, "ask", prompt="p", use_tools=False)
    assert "model" not in client.calls[0]
    assert _DECISION.get() is None


async def test_bound_decision_injects_copy_and_reaches_super() -> None:
    client = FakeClient()
    original = {"prompt": "p", "use_tools": False}
    token = _DECISION.set(RouteDecision(choice="cheap", selected_model="claude-cheap-id", confidence=0.9, reason="cheap"))
    try:
        message = await _agent(client).execute_llm_call(client, "ask", **original)
    finally:
        _DECISION.reset(token)
    assert client.calls[0]["model"] == "claude-cheap-id"
    assert "model" not in original
    assert message.model == "claude-cheap-id"
    assert client.model == "client-default-model"


async def test_bound_decision_without_model_is_invalid_live_configuration() -> None:
    client = FakeClient()
    token = _DECISION.set(RouteDecision(choice="cheap", selected_model=None, confidence=0.9, reason="cheap"))
    try:
        with pytest.raises(ValueError):
            await _agent(client).execute_llm_call(client, "ask", prompt="p")
    finally:
        _DECISION.reset(token)


async def test_ask_routed_resets_contextvar_on_success_error_and_cancel() -> None:
    agent = _agent(FakeClient())
    decision = RouteDecision(choice="cheap", selected_model="claude-cheap-id", confidence=0.9, reason="cheap")

    async def ask_success(question: str, **kwargs: Any) -> AIMessage:
        return AIMessage(
            input=question,
            output="ok",
            model="fake",
            provider="fake",
            usage=CompletionUsage(),
        )

    agent.ask = ask_success
    await agent.ask_routed("success", decision)
    assert _DECISION.get() is None

    async def ask_error(question: str, **kwargs: Any) -> AIMessage:
        raise RuntimeError("expected")

    agent.ask = ask_error
    with pytest.raises(RuntimeError, match="expected"):
        await agent.ask_routed("error", decision)
    assert _DECISION.get() is None

    async def ask_cancel(question: str, **kwargs: Any) -> AIMessage:
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    agent.ask = ask_cancel
    task = asyncio.create_task(agent.ask_routed("cancel", decision))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _DECISION.get() is None


async def test_interleaved_scoped_calls_do_not_leak_models() -> None:
    client = FakeClient()
    agent = _agent(client)

    async def ask_dispatch(question: str, **kwargs: Any) -> AIMessage:
        return await agent.execute_llm_call(client, "ask", prompt=question, **kwargs)

    agent.ask = ask_dispatch
    cheap = RouteDecision(choice="cheap", selected_model="claude-cheap-id", confidence=0.9, reason="cheap")
    primary = RouteDecision(choice="primary", selected_model="claude-primary-id", confidence=0.9, reason="primary")
    await asyncio.gather(agent.ask_routed("cheap", cheap), agent.ask_routed("primary", primary))
    models_by_prompt = {call["prompt"]: call["model"] for call in client.calls}
    assert models_by_prompt == {"cheap": "claude-cheap-id", "primary": "claude-primary-id"}
    assert _DECISION.get() is None
