"""Core data models and abstractions for the AI-Parrot guardrails infrastructure.

Defines the guardrail stages, verdicts, result/context carriers, and the
``Guardrail`` abstract base class that every built-in and custom guardrail
implements. See ``sdd/specs/guardrails-infrastructure.spec.md`` (FEAT-396)
for the full design.
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class GuardrailStage(str, Enum):
    """Pipeline stage at which a guardrail runs.

    Attributes:
        INPUT: User text, before it reaches the LLM.
        TOOL_OUTPUT: A tool's result, before it is returned to the agent loop.
        OUTPUT: The final answer, before it is returned to the caller.
        OUTPUT_STREAM: Individual chunks emitted while streaming a response.
        TOOL_CALL: Before tool execution; intercepts the call before guards/body.
    """
    INPUT = "input"
    TOOL_OUTPUT = "tool_output"
    OUTPUT = "output"
    OUTPUT_STREAM = "output_stream"
    TOOL_CALL = "tool_call"


class GuardrailAction(str, Enum):
    """Verdict returned by a guardrail's ``check()`` call.

    Attributes:
        PASS: Content is unchanged; no action taken.
        TRANSFORM: Content was rewritten; see ``GuardrailResult.content``.
        FLAG: Content passes but is annotated; see ``GuardrailResult.report``.
        BLOCK: Content is rejected; see ``GuardrailResult.reason``.
    """
    PASS = "pass"
    TRANSFORM = "transform"
    FLAG = "flag"
    BLOCK = "block"


class GuardrailResult(BaseModel):
    """Outcome of a single guardrail's ``check()`` call.

    Attributes:
        action: The verdict for this guardrail run.
        content: The transformed content, populated when ``action`` is
            ``TRANSFORM``.
        report: Structured annotation data, populated when ``action`` is
            ``FLAG``. Attached to ``AIMessage.metadata["guardrails"][<name>]``.
        reason: A category label (never the offending content) explaining
            a ``BLOCK`` verdict.
    """
    action: GuardrailAction
    content: str | None = None
    report: dict[str, Any] | None = None
    reason: str | None = None


class GuardrailContext(BaseModel):
    """Contextual information passed to a guardrail's ``check()`` call.

    Attributes:
        stage: The pipeline stage this context was built for.
        agent_name: Name of the bot/agent invoking the guardrail.
        user_id: Identifier of the requesting user, if known.
        session_id: Identifier of the current conversation/session, if known.
        method: The bot entrypoint that triggered this check
            (e.g. ``"invoke"``, ``"ask"``, ``"ask_stream"``).
        tool_name: Name of the tool whose output is being checked.
            Only populated at ``GuardrailStage.TOOL_OUTPUT``.
        extras: Stage-specific additional data (e.g. the outgoing
            ``AIMessage`` at ``GuardrailStage.OUTPUT``).
    """
    stage: GuardrailStage
    agent_name: str
    user_id: str | None = None
    session_id: str | None = None
    method: str = ""
    tool_name: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("user_id", "session_id", mode="before")
    @classmethod
    def _coerce_to_str(cls, v: Any) -> str | None:
        """Accept int/str identifiers — always store as str."""
        if v is None:
            return None
        return str(v)


class Guardrail(ABC):
    """Abstract base class for all guardrails.

    A guardrail inspects (and optionally transforms, flags, or blocks)
    content at one or more pipeline stages. Concrete subclasses set
    ``name``, ``stages``, and ``priority`` and implement ``check()``.

    Default priority bands (lower runs first within a stage):
        - 0-99: sanitizers (e.g. prompt-injection detection).
        - 100-199: transformers (e.g. secrets/PII redaction).
        - 200+: observers (e.g. moderation flags, groundedness scoring).

    Attributes:
        name: Unique identifier for this guardrail (used in telemetry and
            ``AIMessage.metadata["guardrails"]`` report keys).
        stages: The set of stages at which this guardrail runs.
        priority: Execution order within a stage; lower runs first.
        on_error: Error-handling policy for unhandled exceptions raised by
            ``check()``. ``"fail_open"`` (default) logs and continues as if
            the guardrail returned PASS; ``"fail_closed"`` treats the error
            as a BLOCK.
    """
    name: str
    stages: set[GuardrailStage]
    priority: int
    on_error: Literal["fail_open", "fail_closed"] = "fail_open"

    @abstractmethod
    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        """Inspect (and optionally act on) ``content`` for ``ctx.stage``.

        Args:
            content: The text content to inspect.
            ctx: Contextual information about the current call.

        Returns:
            A ``GuardrailResult`` describing the verdict.
        """
        raise NotImplementedError
