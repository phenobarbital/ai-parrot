"""Tests for the procedures channel transport adapter."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.knowledge.manuals.models import ProcedureAnswer, ProcedureCitation
from parrot_tools.procedures.agent import ProceduresAgent, UngatedAnswerRefused
from parrot_tools.procedures.retrieval import AuthorizationDenied, RequestContext
from parrot_tools.procedures.service import AnswerOutcome

from ._doubles import make_context


class _StubService:
    """Scripted release service that records trusted contexts."""

    def __init__(self, outcome: AnswerOutcome) -> None:
        self.outcome = outcome
        self.contexts: list[RequestContext] = []

    async def answer(self, question: str, *, request_context: RequestContext) -> AnswerOutcome:
        """Return the released outcome and retain the supplied trusted context."""
        self.contexts.append(request_context)
        return self.outcome

    async def stream_answer(self, question: str, *, request_context: RequestContext):
        """Yield one already released chunk."""
        self.contexts.append(request_context)
        yield self.outcome.answer.answer


def _outcome() -> AnswerOutcome:
    """Create a release outcome whose answer contains no producer draft."""
    answer = ProcedureAnswer(
        answer_kind="lookup",
        answer="This is a manual excerpt, not a verified procedure.",
        citations=[ProcedureCitation(manual_id="m1", node_id="n1", quote="Released excerpt", page=4)],
    )
    return AnswerOutcome(answer=answer, audit_id="audit-1", image_urls=["https://fake/f1.png"])


def _agent(service: Any, factory: Any) -> ProceduresAgent:
    """Build an adapter without Agent.__init__, which builds a real LLM client."""
    agent = ProceduresAgent.__new__(ProceduresAgent)
    agent.service = service
    agent.context_factory = factory
    agent._request_context = ContextVar("test_procedures_request_context", default=make_context())
    agent._serials = {}
    agent.toolkit = SimpleNamespace(bind_context=lambda context: None)
    agent.logger = logging.getLogger(__name__)
    return agent


async def test_agent_ask_is_gated() -> None:
    """ask returns released structured data and URLs, never a producer draft."""
    service = _StubService(_outcome())
    agent = _agent(service, lambda kwargs: make_context(session_id=kwargs["session_id"]))

    message = await agent.ask("How do I proceed?", session_id="s1")

    assert message.structured_output == service.outcome.answer
    assert message.image_urls == ["https://fake/f1.png"]
    assert "RAW-DRAFT-XYZ" not in message.output
    assert message.output == "This is a manual excerpt, not a verified procedure.\nSource: p.4"
    assert service.contexts == [make_context(session_id="s1")]


async def test_denied_context_returns_message_without_steps() -> None:
    """A transport-level denial becomes a channel-safe response instead of an exception."""
    agent = _agent(_StubService(_outcome()), lambda kwargs: (_ for _ in ()).throw(AuthorizationDenied("denied")))

    message = await agent.ask("How do I proceed?", session_id="s1")

    assert message.output == "⛔ denied"
    assert message.structured_output is None


def test_entrypoints_are_overridden() -> None:
    """No generic Agent entrypoint can bypass the release adapter."""
    for name in ("ask", "ask_stream", "invoke"):
        assert name in vars(ProceduresAgent)


async def test_invoke_without_session_refuses() -> None:
    """invoke refuses rather than produce any answer when session data is absent."""
    agent = _agent(_StubService(_outcome()), lambda kwargs: (_ for _ in ()).throw(AuthorizationDenied("missing")))

    with pytest.raises(UngatedAnswerRefused) as exc_info:
        await agent.invoke("How do I proceed?")

    assert exc_info.value.entrypoint == "invoke"


async def test_serial_is_reused_for_later_session_ask() -> None:
    """A serial captured by a toolkit call is merged into the later session context."""
    service = _StubService(_outcome())
    agent = _agent(service, lambda kwargs: make_context(session_id=kwargs["session_id"]))
    agent._serials["s1"] = "SN-42"

    await agent.ask("How do I proceed?", session_id="s1")

    assert service.contexts[0].equipment_serial == "SN-42"
