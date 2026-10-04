"""Request-local model routing for the Laya evaluation (spec §3 Module 3)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from parrot.bots.agent import Agent
from parrot.clients.base import AbstractClient
from parrot.models.responses import AIMessage

from artifacts.laya.models import ROUTING_QUESTION_ID, EvaluationConfig, PredictionResult, RouteDecision

_DECISION: ContextVar[RouteDecision | None] = ContextVar("laya_route_decision", default=None)


def choose_route(result: PredictionResult, config: EvaluationConfig) -> RouteDecision:
    """Choose only a configured model; abstention/error/low confidence retains primary.

    ``selected_model`` is ``config.primary_api_model`` / ``config.cheap_api_model`` and stays
    ``None`` when the corresponding CLI input is absent — a model name is never invented.
    """
    primary = config.primary_api_model
    if result.status == "error":
        return RouteDecision(
            choice="primary",
            selected_model=primary,
            confidence=None,
            reason=f"error:{result.error_code}",
        )
    answer = result.answers.get(ROUTING_QUESTION_ID)
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return RouteDecision(choice="primary", selected_model=primary, confidence=None, reason="invalid_answer")
    choice, confidence = answer.get("choice"), answer.get("confidence")
    if choice == "abstain":
        return RouteDecision(choice="primary", selected_model=primary, confidence=confidence, reason="abstain")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return RouteDecision(choice="primary", selected_model=primary, confidence=None, reason="invalid_answer")
    if confidence < config.routing_threshold:
        return RouteDecision(
            choice="primary",
            selected_model=primary,
            confidence=confidence,
            reason=f"low_confidence:{confidence:.3f}",
        )
    if choice == "cheap":
        return RouteDecision(
            choice="cheap",
            selected_model=config.cheap_api_model,
            confidence=confidence,
            reason="cheap",
        )
    if choice == "primary":
        return RouteDecision(choice="primary", selected_model=primary, confidence=confidence, reason="primary")
    return RouteDecision(choice="primary", selected_model=primary, confidence=confidence, reason="invalid_answer")


class LayaEvaluationAgent(Agent):
    """Evaluation-only Agent with a request-scoped downstream model decision."""

    async def ask_routed(self, question: str, decision: RouteDecision, **kwargs: Any) -> AIMessage:
        """Bind decision, call inherited ask, and reset its ContextVar even on cancellation."""
        kwargs.setdefault("use_tools", False)
        kwargs.setdefault("use_vector_context", False)
        kwargs.setdefault("use_conversation_history", False)
        token = _DECISION.set(decision)
        try:
            return await self.ask(question, **kwargs)
        finally:
            _DECISION.reset(token)

    async def execute_llm_call(self, client: AbstractClient, method: str = "ask", **llm_kwargs: Any) -> Any:
        """Inject the scoped model into copied ask kwargs and delegate through super."""
        decision = _DECISION.get()
        if decision is None or method != "ask":
            return await super().execute_llm_call(client, method, **llm_kwargs)
        if decision.selected_model is None:
            raise ValueError("bound RouteDecision has no selected_model: invalid live configuration (spec §3 M3)")
        scoped = dict(llm_kwargs)
        scoped["model"] = decision.selected_model
        self.logger.debug(
            "routed call: choice=%s model=%s reason=%s", decision.choice, decision.selected_model, decision.reason
        )
        return await super().execute_llm_call(client, method, **scoped)
