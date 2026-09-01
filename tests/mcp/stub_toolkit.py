"""Stub toolkit for MCP server factory testing.

Provides a minimal AbstractToolkit with plain, confirming, and LLM-dependent tools.
Importable via the dotted path "tests.mcp.stub_toolkit.StubToolkit".
"""

from typing import Any

from parrot.tools.toolkit import AbstractToolkit


class StubToolkit(AbstractToolkit):
    """Minimal toolkit for testing with three tool types."""

    confirming_tools = frozenset({"dangerous"})
    llm_dependent_tools = frozenset({"needs_llm"})

    def __init__(self, llm_client: Any = None) -> None:
        """Initialize stub toolkit.

        Args:
            llm_client: Optional LLM client.
        """
        self.llm_client = llm_client
        super().__init__()

    async def plain(self, x: str) -> str:
        """A plain tool that does not require LLM."""
        return f"plain({x})"

    async def dangerous(self, x: str) -> str:
        """A tool that requires confirmation."""
        return f"dangerous({x})"

    async def needs_llm(self, x: str) -> str:
        """A tool that requires an LLM client."""
        if self.llm_client is None:
            raise RuntimeError("needs_llm requires llm_client")
        return f"needs_llm({x})"
