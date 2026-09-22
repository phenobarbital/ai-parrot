"""FEAT-585 M1 — toolkit-owner discovery (AC12)."""

from __future__ import annotations

import pytest

from parrot.bots.agent import BasicAgent
from parrot.tools.manager import ToolManager, get_toolkit_owner
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.working_memory import WorkingMemoryToolkit


class _OtherToolkit(AbstractToolkit):
    """A toolkit that is NOT a WorkingMemoryToolkit, with one public tool."""

    name = "other"

    async def ping(self) -> str:
        """Return pong."""
        return "pong"


class _CountingWorkingMemoryToolkit(WorkingMemoryToolkit):
    """Working-memory toolkit that records answer-memory injections."""

    def __init__(self) -> None:
        super().__init__()
        self.answer_memory_assignments = 0

    def __setattr__(self, name: str, value: object) -> None:
        if name == "_answer_memory" and hasattr(self, "_answer_memory"):
            self.answer_memory_assignments += 1
        super().__setattr__(name, value)


class _Logger:
    """Minimal logger used by the unbound BasicAgent methods."""

    def debug(self, *args: object, **kwargs: object) -> None:
        """Accept a debug message without recording it."""


class _AgentLike:
    """Minimal object satisfying the toolkit-memory helpers' requirements."""

    _iter_toolkit_owners = BasicAgent._iter_toolkit_owners

    def __init__(self, tool_manager: ToolManager, answer_memory: object) -> None:
        self.tool_manager = tool_manager
        self.answer_memory = answer_memory
        self.logger = _Logger()
        self.task_memory = None


def test_direct_instance_is_its_own_owner():
    tk = WorkingMemoryToolkit()
    assert get_toolkit_owner(tk) is tk


def test_wrapped_method_resolves_to_toolkit():
    tk = WorkingMemoryToolkit()
    tools = tk.get_tools_sync()
    assert tools, "WorkingMemoryToolkit must generate at least one ToolkitTool"
    assert get_toolkit_owner(tools[0]) is tk


def test_unrelated_objects_have_no_owner():
    assert get_toolkit_owner(object()) is None
    assert get_toolkit_owner(None) is None


def test_manager_finds_registered_working_memory_toolkit():
    manager = ToolManager()
    tk = WorkingMemoryToolkit()
    manager.register_toolkit(tk)

    assert manager._find_working_memory_toolkit() is tk


@pytest.mark.asyncio
async def test_duplicate_wrappers_inject_once():
    """N wrapped methods result in exactly one injection into the same owner."""
    manager = ToolManager()
    tk = _CountingWorkingMemoryToolkit()
    other = _OtherToolkit()
    manager.register_toolkit(tk)
    manager.register_toolkit(other)
    answer_memory = object()
    agent = _AgentLike(manager, answer_memory)

    BasicAgent._inject_answer_memory_into_toolkits(agent)

    assert tk._answer_memory is answer_memory
    assert tk.answer_memory_assignments == 1
    assert get_toolkit_owner(manager.get_tool("ping")) is other


@pytest.mark.asyncio
async def test_explicit_answer_memory_is_preserved():
    manager = ToolManager()
    sentinel = object()
    tk = WorkingMemoryToolkit(answer_memory=sentinel)
    manager.register_toolkit(tk)
    agent = _AgentLike(manager, object())

    BasicAgent._inject_answer_memory_into_toolkits(agent)

    assert tk._answer_memory is sentinel
