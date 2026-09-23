"""FEAT-590: AbstractTool delegate flags."""

from __future__ import annotations

from typing import Any

from parrot.tools.abstract import AbstractTool


class _PlainTool(AbstractTool):
    name = "plain"
    description = "A plain tool."

    async def _execute(self, **kwargs: Any) -> Any:
        return None


class _SafeTool(_PlainTool):
    name = "safe"
    delegate_safe = True
    delegate_description = "Fetch a page."


def test_abstract_tool_delegate_defaults() -> None:
    """Unflagged tools are not delegate-safe and carry no delegate description."""
    tool = _PlainTool()
    assert tool.delegate_safe is False
    assert tool.delegate_description is None


def test_subclass_override() -> None:
    """A subclass opts in by overriding the class attributes."""
    tool = _SafeTool()
    assert tool.delegate_safe is True
    assert tool.delegate_description == "Fetch a page."
    assert _PlainTool().delegate_safe is False
    assert _PlainTool().delegate_description is None
