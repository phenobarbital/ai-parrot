"""Shared fixtures for AgentCrew infographic integration tests (FEAT-308).

TASK-1780: End-to-End Integration Tests for Crew Infographic.

Provides ``DummyAgent``-style stub agents (modeled after
``packages/ai-parrot/tests/_crew_test_helpers.py``, not importable from this
top-level ``tests/`` tree) and a deterministic ``fake_llm`` stub compatible
with ``AgentCrew``'s ``async with self._llm as client:`` synthesis pattern
(``parrot/bots/flows/core/storage/synthesis.py``).
"""
from __future__ import annotations

import types
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.clients.base import AbstractClient


class _DummyToolManager:
    """Minimal ToolManager stand-in compatible with ``AgentCrew.add_agent()``."""

    def __init__(self) -> None:
        self._tools: Dict[str, Any] = {}

    def add_tool(self, tool: Any, tool_name: str = None) -> None:
        name = tool_name or getattr(tool, "name", str(tool))
        self._tools[name] = tool

    def get_tool(self, tool_name: str) -> Any:
        return self._tools.get(tool_name or "")

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())


class DummyAgent:
    """Deterministic stub agent compatible with ``AgentCrew.add_agent()``/``run_*()``.

    Mirrors ``packages/ai-parrot/tests/_crew_test_helpers.DummyAgent`` (not
    importable here since it lives outside this test tree's sys.path).
    """

    is_configured: bool = True
    EVENT_STATUS_CHANGED: str = "status_changed"
    EVENT_TASK_STARTED: str = "task_started"
    EVENT_TASK_COMPLETED: str = "task_completed"
    EVENT_TASK_FAILED: str = "task_failed"

    def __init__(self, name: str, response: str = "ok") -> None:
        self._name = name
        self._response = response
        self.tool_manager = _DummyToolManager()
        self.description = f"Agent {name}"
        self.prompts_received: List[str] = []

    @property
    def name(self) -> str:  # noqa: D401
        return self._name

    async def invoke(self, prompt: str, **kwargs: Any) -> Any:
        """AgentLike protocol method — delegates to ask()."""
        return await self.ask(question=prompt, **kwargs)

    async def ask(self, prompt: str = "", *, question: str = "", **kwargs: Any):
        """Return a mock response with a ``.content`` attribute."""
        effective_prompt = question or prompt
        self.prompts_received.append(effective_prompt)
        return types.SimpleNamespace(content=f"{self._response}: {effective_prompt[:40]}")

    def add_event_listener(self, event: str, handler: Any) -> None:
        """No-op for tests."""

    def as_tool(self, **kwargs: Any) -> None:
        """No-op stub for AgentTool registration."""
        return None

    async def configure(self) -> None:
        """No-op configure."""


@pytest.fixture
def stub_agents() -> List[DummyAgent]:
    """3 stub research agents returning short, deterministic text results."""
    return [DummyAgent(f"researcher-{i}", response=f"finding-{i}") for i in range(3)]


@pytest.fixture
def fake_llm() -> MagicMock:
    """Deterministic ``AbstractClient`` stub for crew orchestration/synthesis.

    Supports the ``async with self._llm as client: await client.ask(...)``
    pattern used by ``SynthesisMixin._synthesize_results`` so
    ``generate_summary=True`` produces a deterministic ``result.summary``
    without any real LLM/API call.
    """
    llm = MagicMock(spec=AbstractClient)
    llm.__aenter__ = AsyncMock(return_value=llm)
    llm.__aexit__ = AsyncMock(return_value=False)
    llm.ask = AsyncMock(
        return_value=types.SimpleNamespace(
            content="Executive Summary: All agents completed successfully."
        )
    )
    llm.register_tool = MagicMock()
    return llm
