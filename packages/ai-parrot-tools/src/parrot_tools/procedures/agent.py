"""ProceduresAgent — a gated transport adapter over ProceduresAnswerService (FEAT-601 M11, R3)."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, AsyncIterator, Callable, Optional

from parrot.bots import Agent
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage
from parrot_tools.procedures.retrieval import AuthorizationDenied, Clarification, RequestContext
from parrot_tools.procedures.service import AnswerOutcome, ProceduresAnswerService
from parrot_tools.procedures.toolkit import ProceduresToolkit

logger = logging.getLogger(__name__)

PROCEDURES_SYSTEM_PROMPT = (
    "You help field technicians follow equipment assembly and maintenance procedures. "
    "Only the procedures tools may provide steps, parts, hazards and figures; never invent, reorder or skip steps. "
    "Answer in the technician's language (Spanish or English)."
)
_ANON = RequestContext(authenticated=False, tenant_id="", user_id="")


class UngatedAnswerRefused(PermissionError):
    """An entrypoint was called without the session data needed to build a trusted context."""

    def __init__(self, entrypoint: str) -> None:
        super().__init__(f"{entrypoint}() needs a trusted platform session; refusing an unverified answer")
        self.entrypoint = entrypoint


class _ContextProceduresToolkit(ProceduresToolkit):
    """Expose the agent's request-local context to otherwise shared toolkit methods."""

    def __init__(
        self,
        *,
        request_context_var: ContextVar[RequestContext],
        serials: dict[str, str],
        **kwargs: Any,
    ) -> None:
        self._request_context_var = request_context_var
        self._serials = serials
        super().__init__(**kwargs)

    @property
    def request_context(self) -> RequestContext:
        """Return this task's trusted context rather than a shared mutable value."""
        return self._request_context_var.get()

    @request_context.setter
    def request_context(self, value: RequestContext) -> None:
        """Bind a context in this task only and remember a successfully set serial."""
        self._request_context_var.set(value)
        if value.session_id and value.equipment_serial:
            self._serials[value.session_id] = value.equipment_serial

    def bind_context(self, context: RequestContext) -> None:
        """Bind a trusted transport context for the current async task."""
        self.request_context = context


class ProceduresAgent(Agent):
    """ReAct-capable agent whose every channel entrypoint passes the procedures release gate.

    Args:
        service: The shared release service, which is the sole answer path.
        context_factory: Builds a trusted context from platform-session keyword arguments.
        **kwargs: Forwarded to :class:`~parrot.bots.Agent`.
    """

    agent_id: str = "procedures_agent"

    def __init__(
        self,
        *,
        service: ProceduresAnswerService,
        context_factory: Callable[[dict[str, Any]], RequestContext],
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("system_prompt", PROCEDURES_SYSTEM_PROMPT)
        self.service = service
        self.context_factory = context_factory
        self._request_context: ContextVar[RequestContext] = ContextVar("procedures_request_context", default=_ANON)
        self._serials: dict[str, str] = {}
        self.toolkit = _ContextProceduresToolkit(
            service=service,
            request_context=_ANON,
            request_context_var=self._request_context,
            serials=self._serials,
        )
        # Agent.__init__ calls agent_tools(), so the toolkit must exist first.
        super().__init__(**kwargs)

    def agent_tools(self) -> list[Any]:
        """Expose the procedures toolkit's tools to the ReAct loop."""
        return self.toolkit.get_tools()

    def _context(self, kwargs: dict[str, Any]) -> RequestContext:
        """Build the trusted context and merge the session's remembered serial (Q7)."""
        context = self.context_factory(kwargs)
        serial = self._serials.get(context.session_id or "")
        if serial and not context.equipment_serial:
            context = context.model_copy(update={"equipment_serial": serial})
        self._request_context.set(context)
        self.toolkit.bind_context(context)
        return context

    async def ask(self, question: str, *args: Any, **kwargs: Any) -> AIMessage:
        """Release an answer through the service using only a trusted session context."""
        try:
            context = self._context(kwargs)
        except AuthorizationDenied as exc:
            return self._message(question, f"⛔ {exc.reason}", structured=None)
        outcome = await self.service.answer(question, request_context=context)
        return self._message(
            question,
            self.render(outcome),
            structured=outcome.answer if isinstance(outcome, AnswerOutcome) else outcome,
            image_urls=outcome.image_urls if isinstance(outcome, AnswerOutcome) else [],
            media_urls=outcome.media_urls if isinstance(outcome, AnswerOutcome) else [],
        )

    async def ask_stream(self, question: str, *args: Any, **kwargs: Any) -> AsyncIterator[str]:
        """Stream released content only; the service buffers before release."""
        context = self._context(kwargs)
        async for chunk in self.service.stream_answer(question, request_context=context):
            yield chunk

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        """Use the same gate as :meth:`ask`, refusing an absent trusted session."""
        question = kwargs.pop("question", None) or (args[0] if args else "")
        try:
            self.context_factory(kwargs)
        except Exception as exc:  # noqa: BLE001 - no session must never produce an answer
            raise UngatedAnswerRefused("invoke") from exc
        return await self.ask(question, **kwargs)

    @staticmethod
    def render(outcome: AnswerOutcome | Clarification) -> str:
        """Render a released answer deterministically without model draft text.

        Args:
            outcome: A released service outcome or a request for clarification.

        Returns:
            Chat-safe text constructed exclusively from released fields.
        """
        if isinstance(outcome, Clarification):
            lines = [outcome.reason]
            lines.extend(f"{index}. {_candidate_label(candidate)}" for index, candidate in enumerate(outcome.candidates, 1))
            return "\n".join(lines)

        answer = outcome.answer
        if answer.answer_kind in {"denied", "incomplete", "not_found", "out_of_scope"}:
            return answer.reason or answer.answer or "No verified procedure is available."

        lines: list[str] = []
        if answer.answer:
            lines.append(answer.answer)
        if answer.prerequisites and (answer.prerequisites.parts or answer.prerequisites.tools):
            lines.append("Before you start:")
            lines.extend(f"- Part: {_part_label(part)}" for part in answer.prerequisites.parts)
            lines.extend(f"- Tool: {_tool_label(tool)}" for tool in answer.prerequisites.tools)
        for step in answer.steps:
            lines.append(f"{step.order}. {step.text}")
            if step.applicability == "unknown":
                lines.append(f"   Unknown applicability: {step.applicability_note}")
        for hazard in answer.hazards:
            lines.append(f"⚠ {hazard.severity}: {hazard.text}")
        for tip in answer.tips:
            lines.append(f"Tip: {tip.text}")
        lines.extend(_citation_footer(citation.page) for citation in answer.citations)
        return "\n".join(lines) or "No verified procedure is available."

    def _message(
        self,
        question: str,
        text: str,
        *,
        structured: Any,
        image_urls: Optional[list[str]] = None,
        media_urls: Optional[list[str]] = None,
    ) -> AIMessage:
        """Wrap released content in an AIMessage with all required transport fields."""
        return AIMessage(
            input=question,
            output=text,
            response=text,
            structured_output=structured,
            image_urls=list(image_urls or []),
            media_urls=list(media_urls or []),
            model="procedures-service",
            provider="parrot",
            usage=CompletionUsage(),
        )


def _candidate_label(candidate: Any) -> str:
    """Return the released display label for a clarification candidate."""
    return str(getattr(candidate, "model", None) or getattr(candidate, "title", None) or candidate)


def _part_label(part: Any) -> str:
    """Render a released part reference."""
    name = part.name.value
    return f"{name} (x{part.quantity})" if part.quantity else name


def _tool_label(tool: Any) -> str:
    """Render a released tool reference."""
    return f"{tool.name.value} ({tool.spec})" if tool.spec else tool.name.value


def _citation_footer(page: Optional[int]) -> str:
    """Render a deterministic citation footer."""
    return f"Source: p.{page}" if page is not None else "Source: manual"
