"""Unit tests for `AbstractTool.a2ui_requires_user_activation`/`.a2ui_hidden` (FEAT-469 TASK-2571)."""

from __future__ import annotations

from parrot.tools.abstract import AbstractTool


def test_defaults_are_false():
    assert AbstractTool.a2ui_requires_user_activation is False
    assert AbstractTool.a2ui_hidden is False


def test_subclass_can_override():
    class _SensitiveTool(AbstractTool):
        a2ui_hidden = True
        a2ui_requires_user_activation = True

        async def _execute(self, **kwargs):
            return None

    assert _SensitiveTool.a2ui_hidden is True
    assert _SensitiveTool.a2ui_requires_user_activation is True
    # Sibling subclasses are unaffected — these are independent class attrs.
    assert AbstractTool.a2ui_hidden is False
    assert AbstractTool.a2ui_requires_user_activation is False


def test_unrelated_subclass_keeps_defaults():
    class _PlainTool(AbstractTool):
        async def _execute(self, **kwargs):
            return None

    assert _PlainTool.a2ui_hidden is False
    assert _PlainTool.a2ui_requires_user_activation is False
