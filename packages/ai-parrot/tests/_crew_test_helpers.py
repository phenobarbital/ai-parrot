"""Shared test infrastructure for FEAT-137 AgentCrew regression tests.

Provides ``DummyToolManager`` and ``DummyAgent`` — minimal stubs
compatible with ``AgentCrew.add_agent()`` — so individual test files
do not need to duplicate them.
"""
from __future__ import annotations

import asyncio
import types
from typing import Any, Dict, List, Optional


class DummyToolManager:
    """Minimal ToolManager stand-in for crew tests."""

    def __init__(self) -> None:
        self._tools: Dict[str, Any] = {}

    def add_tool(self, tool: Any, tool_name: Optional[str] = None) -> None:
        name = tool_name or getattr(tool, "name", str(tool))
        self._tools[name] = tool

    def get_tool(self, tool_name: Optional[str]) -> Any:
        return self._tools.get(tool_name or "")

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())


class DummyTool:
    """AbstractTool stand-in for ToolNode tests.

    Records every call in ``calls`` and returns a canned ``ToolResult``.

    Args:
        name: Tool identity.
        result: Payload placed in ``ToolResult.result`` on success.
        fail: If True, ``execute()`` returns a failed ``ToolResult``.
        delay: Optional asyncio sleep before returning.
    """

    def __init__(
        self,
        name: str = "dummy_tool",
        result: Any = "tool-output",
        *,
        fail: bool = False,
        delay: float = 0.0,
    ) -> None:
        self.name = name
        self.description = f"Dummy tool {name}"
        self._result = result
        self._fail = fail
        self._delay = delay
        self.calls: List[tuple] = []

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        """Record the call and return a canned ToolResult."""
        from parrot.tools.abstract import ToolResult

        self.calls.append((args, kwargs))
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            return ToolResult(
                success=False, status="error", result=None, error="boom"
            )
        return ToolResult(success=True, status="success", result=self._result)


class DummyAgent:
    """Deterministic agent for testing AgentCrew.

    Supports ``ask(prompt=..., question=..., **kwargs)`` matching the
    interface expected by ``AgentCrew._execute_agent`` (which passes
    ``question=``) and ``AgentNode.execute`` (which passes ``prompt=``).

    Args:
        name: Agent identity.
        response: Canned response prefix returned from ``ask()``.
        fail: If True, ``ask()`` always raises ``RuntimeError``.
        fail_on_iteration: Raise on the Nth call (1-based). -1 = never.
        delay: Optional asyncio sleep before returning.
    """

    is_configured: bool = True
    EVENT_STATUS_CHANGED: str = "status_changed"
    EVENT_TASK_STARTED: str = "task_started"
    EVENT_TASK_COMPLETED: str = "task_completed"
    EVENT_TASK_FAILED: str = "task_failed"

    def __init__(
        self,
        name: str,
        response: str = "ok",
        *,
        fail: bool = False,
        fail_on_iteration: int = -1,
        delay: float = 0.0,
    ) -> None:
        self._name = name
        self._response = response
        self._fail = fail
        self._fail_on_iteration = fail_on_iteration
        self._call_count = 0
        self._delay = delay
        self.tool_manager = DummyToolManager()
        self.description = f"Agent {name}"
        self.prompts_received: List[str] = []

    @property
    def name(self) -> str:  # noqa: D401
        return self._name

    async def invoke(self, prompt: str, **kwargs: Any) -> Any:
        """AgentLike protocol method — delegates to ask()."""
        return await self.ask(question=prompt, **kwargs)

    async def ask(
        self, prompt: str = "", *, question: str = "", **kwargs: Any
    ) -> types.SimpleNamespace:
        """Return a mock response with ``.content`` attribute."""
        effective_prompt = question or prompt
        self.prompts_received.append(effective_prompt)
        self._call_count += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail or self._call_count == self._fail_on_iteration:
            raise RuntimeError(f"{self._name} failed")
        return types.SimpleNamespace(
            content=f"{self._response}: {effective_prompt[:40]}"
        )

    def add_event_listener(self, event: str, handler: Any) -> None:
        """No-op for tests."""

    def as_tool(self, **kwargs: Any) -> None:
        """No-op stub for AgentTool registration."""
        return None

    async def configure(self) -> None:
        """No-op configure."""
