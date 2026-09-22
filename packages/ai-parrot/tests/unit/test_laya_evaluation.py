"""FEAT-589 M5 request-local routing and confident-negative regression tests."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from parrot.models.basic import CompletionUsage  # noqa: E402
from parrot.models.responses import AIMessage  # noqa: E402

from artifacts.laya.models import INJECTION_QUESTION_ID, PredictionResult, RouteDecision  # noqa: E402
from artifacts.laya.routing import _DECISION, LayaEvaluationAgent  # noqa: E402
from artifacts.laya.scenarios import injection_verdict  # noqa: E402


class _SlowFakeClient:
    """Record ask kwargs while yielding so scoped calls interleave."""

    def __init__(self) -> None:
        """Initialize an unchanged client-default model and call log."""
        self.model = "client-default"
        self.calls: list[dict[str, Any]] = []

    async def ask(self, **kwargs: Any) -> AIMessage:
        """Record one request and return an answer carrying its requested model."""
        await asyncio.sleep(0.01)
        self.calls.append(dict(kwargs))
        await asyncio.sleep(0.01)
        return AIMessage(
            input=kwargs.get("prompt", ""),
            output="x",
            model=kwargs.get("model") or self.model,
            provider="fake",
            usage=CompletionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def _agent(client: _SlowFakeClient) -> LayaEvaluationAgent:
    """Build a minimal agent without constructing its normal provider client."""
    agent = LayaEvaluationAgent.__new__(LayaEvaluationAgent)
    agent.logger = logging.getLogger("test_laya_evaluation")
    agent._llm = client
    agent.name = "isolation-test"
    return agent


async def _scoped_calls(agent: LayaEvaluationAgent, client: _SlowFakeClient) -> tuple[AIMessage, AIMessage]:
    """Run two independently bound routing decisions concurrently."""

    async def scoped(model: str, prompt: str) -> AIMessage:
        decision = RouteDecision(choice="cheap", selected_model=model, confidence=0.9, reason="cheap")
        token = _DECISION.set(decision)
        try:
            return await agent.execute_llm_call(client, "ask", prompt=prompt, use_tools=False)
        finally:
            _DECISION.reset(token)

    return await asyncio.gather(scoped("model-A", "pa"), scoped("model-B", "pb"))


async def test_request_local_model_isolation() -> None:
    """Interleave scoped calls and preserve both the client default and ContextVar."""
    client = _SlowFakeClient()
    agent = _agent(client)

    first, second = await _scoped_calls(agent, client)

    by_prompt = {call["prompt"]: call["model"] for call in client.calls}
    assert by_prompt == {"pa": "model-A", "pb": "model-B"}
    assert (first.model, second.model) == ("model-A", "model-B")
    assert client.model == "client-default"
    assert _DECISION.get() is None


async def test_unscoped_call_after_scoped_ones_has_no_model() -> None:
    """Leave parent dispatch unchanged after scoped routing calls finish."""
    client = _SlowFakeClient()
    agent = _agent(client)

    await _scoped_calls(agent, client)
    response = await agent.execute_llm_call(client, "ask", prompt="plain", use_tools=False)

    plain_call = next(call for call in client.calls if call["prompt"] == "plain")
    assert "model" not in plain_call
    assert response.model == "client-default"
    assert _DECISION.get() is None


def test_confident_negative_end_to_end_verdict() -> None:
    """Treat low positive probability as clean even with high confidence."""
    result = PredictionResult(
        request_id="r",
        status="ok",
        answers={INJECTION_QUESTION_ID: {"type": "noul", "noul": 0.01, "confidence": 0.99}},
    )
    assert injection_verdict(result, 0.5) == "clean"
