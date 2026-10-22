"""FEAT-721 — ToolManager keep-first toolkit re-registration."""

import logging
from unittest.mock import patch

import pytest

from parrot.tools.manager import ToolManager, ToolNameCollisionError
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.working_memory import WorkingMemoryToolkit


class _AlphaToolkit(AbstractToolkit):
    """Prefixed toolkit used to provoke a foreign-owner collision."""

    tool_prefix = "wm"

    async def get_stored(self, key: str) -> str:
        """Return a stored value (collides with WorkingMemoryToolkit's wm_get_stored)."""
        return key


class _WorkingMemorySubclass(WorkingMemoryToolkit):
    """Subclass used to verify exact-class matching."""


@pytest.fixture
def manager() -> ToolManager:
    return ToolManager(include_search_tool=False)


def test_reregistering_same_toolkit_keeps_first(manager: ToolManager) -> None:
    first, second = WorkingMemoryToolkit(session_id="s1"), WorkingMemoryToolkit(session_id="s2")
    manager.register_toolkit(first)
    snapshot = dict(manager._tools)
    manager.register_toolkit(second)
    assert manager._tools == snapshot
    assert manager.find_registered_toolkit(WorkingMemoryToolkit) is first


def test_reregistration_returns_registered_tools(manager: ToolManager) -> None:
    first = WorkingMemoryToolkit(session_id="s1")
    first_tools = manager.register_toolkit(first)

    second_tools = manager.register_toolkit(WorkingMemoryToolkit(session_id="s2"))

    assert second_tools == first_tools
    assert all(left is right for left, right in zip(second_tools, first_tools, strict=True))


def test_reregistration_by_class_does_not_construct(manager: ToolManager) -> None:
    manager.register_toolkit(WorkingMemoryToolkit(session_id="s1"))

    with patch.object(manager, "build_toolkit") as build_toolkit:
        result = manager.register_toolkit(WorkingMemoryToolkit)

    build_toolkit.assert_not_called()
    assert result == manager.register_toolkit(WorkingMemoryToolkit(session_id="s2"))


def test_second_instance_logs_warning(manager: ToolManager, caplog: pytest.LogCaptureFixture) -> None:
    first = WorkingMemoryToolkit(session_id="s1")
    manager.register_toolkit(first)
    second = WorkingMemoryToolkit(session_id="s2")

    with caplog.at_level(logging.WARNING, logger="parrot.tools.manager"):
        manager.register_toolkit(second)

    assert any(record.levelno == logging.WARNING for record in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="parrot.tools.manager"):
        manager.register_toolkit(first)
    assert not [record for record in caplog.records if record.levelno == logging.WARNING]


def test_same_class_different_prefix_registers_twice(manager: ToolManager) -> None:
    first = WorkingMemoryToolkit(session_id="s1")
    second = WorkingMemoryToolkit(session_id="s2")
    second.tool_prefix = "wm2"

    manager.register_toolkit(first)
    manager.register_toolkit(second)

    names = manager.list_tools()
    assert any(name.startswith("wm_") for name in names)
    assert any(name.startswith("wm2_") for name in names)


def test_foreign_owner_collision_still_raises(manager: ToolManager) -> None:
    manager.register_toolkit(WorkingMemoryToolkit(session_id="s1"))
    with pytest.raises(ToolNameCollisionError):
        manager.register_toolkit(_AlphaToolkit())


def test_find_registered_toolkit_exact_class_only(manager: ToolManager) -> None:
    subclass = _WorkingMemorySubclass(session_id="s1")
    manager.register_toolkit(subclass)

    assert manager.find_registered_toolkit(WorkingMemoryToolkit) is None
    assert manager.find_registered_toolkit(_WorkingMemorySubclass) is subclass
