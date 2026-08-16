"""Shared test fakes for the agentd test suite (FEAT-422).

`EchoAgent` is a minimal, dependency-free, duck-typed agent — it does NOT
subclass `AbstractBot` (that would require LLM client configuration) but
exposes the same interface surface `DaemonAgentProxy`/`_DaemonBotProxy` and
the MCP proxy expect: `ask`, `ask_stream`, `configure`,
`get_available_tools`, `get_tools_count`, `has_tools`.

Also exposed here: sync/async factory functions and a pre-built instance,
used to exercise every branch of `resolve_agent()`'s target-resolution
matrix (class / instance / sync factory / async factory).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


class EchoAgentResponse:
    """Minimal AIMessage-like response object."""

    def __init__(self, content: str) -> None:
        self.content = content

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.content

    def __eq__(self, other: object) -> bool:
        return isinstance(other, EchoAgentResponse) and other.content == self.content


class EchoAgent:
    """Duck-typed fake agent: echoes back whatever it is asked.

    Attributes:
        name: Agent name, included in echoed responses.
        configured: Set True after `configure()` has been awaited.
    """

    def __init__(self, name: str = "echo", **kwargs: Any) -> None:
        self.name = name
        self.configured = False
        self.kwargs = kwargs

    async def configure(self, app: Any = None) -> None:
        """Mark the agent as configured (mirrors `AbstractBot.configure`)."""
        self.configured = True

    async def ask(self, question: str, **kwargs: Any) -> EchoAgentResponse:
        """Echo the question back as the response."""
        return EchoAgentResponse(f"echo: {question}")

    async def ask_stream(
        self, question: str, **kwargs: Any
    ) -> AsyncIterator[str]:
        """Yield the echoed response one token at a time."""
        for token in f"echo: {question}".split():
            yield token

    def get_available_tools(self) -> list[str]:
        """Return the (empty) tool list."""
        return []

    def get_tools_count(self) -> int:
        """Return the tool count (always 0)."""
        return 0

    def has_tools(self) -> bool:
        """Return whether this agent has tools (always False)."""
        return False


def make_echo_agent(name: str = "echo", **kwargs: Any) -> EchoAgent:
    """Sync factory returning a new `EchoAgent` (not yet configured)."""
    return EchoAgent(name=name, **kwargs)


async def make_echo_agent_async(name: str = "echo", **kwargs: Any) -> EchoAgent:
    """Async factory returning a new `EchoAgent` (not yet configured)."""
    return EchoAgent(name=name, **kwargs)


#: Pre-built instance target, for the "already an instance" resolution case.
echo_instance = EchoAgent(name="singleton-instance")
