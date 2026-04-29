"""Flow Primitives — Types Module.

Defines the shared type aliases, protocols, and enums used across both
AgentCrew and AgentsFlow orchestration engines.

No imports from ``parrot.bots.*`` or ``parrot.tools.*`` to remain
import-cycle-free.
"""
from __future__ import annotations

from enum import Enum
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Protocol,
    Union,
    runtime_checkable,
)


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ActionCallback = Callable[..., Union[None, Awaitable[None]]]
"""Callback type for pre/post node action hooks."""

DependencyResults = Dict[str, str]
"""Mapping of dependency node IDs → their string results."""

# ---------------------------------------------------------------------------
# FlowStatus enum
# ---------------------------------------------------------------------------


class FlowStatus(str, Enum):
    """Overall execution status for a flow/crew run.

    Values match the string literals previously used in ``CrewResult.status``.
    """

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# AgentLike Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class AgentLike(Protocol):
    """Structural protocol for any object that can act as an agent node.

    Using a Protocol (rather than importing ``BasicAgent`` / ``AbstractBot``)
    keeps this module import-cycle-free and allows StartNode, EndNode, and
    mock objects to satisfy the contract.

    Attributes:
        name: Human-readable agent identifier.

    Methods:
        invoke: Async call that processes a prompt and returns a result.
    """

    @property
    def name(self) -> str:
        """Human-readable agent identifier."""
        ...

    async def invoke(self, prompt: str, **kwargs: Any) -> Any:
        """Process a prompt and return a result.

        Args:
            prompt: The input prompt/question.
            **kwargs: Additional execution context.

        Returns:
            Agent response (type varies by agent implementation).
        """
        ...


# ---------------------------------------------------------------------------
# Composite type aliases (defined after AgentLike)
# ---------------------------------------------------------------------------

AgentRef = Union[str, AgentLike]
"""Reference to an agent — either its string name or an AgentLike object."""

PromptBuilder = Callable[[Any, DependencyResults], Union[str, Awaitable[str]]]
"""Callable that constructs a prompt from execution context and dependency results.

The first argument is ``Any`` (not ``AgentContext``) to avoid importing
``parrot.tools.agent`` and creating a circular dependency.
"""
