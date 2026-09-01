"""Unit tests for ``PublishSurfaceTool`` (FEAT-492, TASK-2704)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.outputs.a2ui.models import CreateSurface
from parrot.tools.ui_surfaces import PublishSurfaceArgs, PublishSurfaceTool


def _sample_envelope(surface_id="surface-1") -> dict:
    return CreateSurface(
        surfaceId=surface_id,
        components=[],
        dataModel={"filters": {"window": "all"}},
    ).model_dump(by_alias=True, mode="json")


class TestToolSchemaAndDocstring:
    def test_tool_schema_and_docstring(self):
        tool = PublishSurfaceTool()
        assert tool.name == "publish_surface"
        assert tool.description
        assert "surface" in tool.description.lower()
        assert tool.args_schema is PublishSurfaceArgs
        assert PublishSurfaceTool.__doc__ is not None
        assert "bookmarkable" in PublishSurfaceTool.__doc__

    def test_schema_lists_expected_fields(self):
        tool = PublishSurfaceTool()
        schema = tool.get_schema()
        props = schema["parameters"]["properties"]
        for field in ("kind", "title", "envelope", "recipe_name", "recipe_owner", "recipe_params", "overwrite"):
            assert field in props


class TestToolDelegatesToBot:
    async def test_tool_execute_delegates_to_bot_when_available(self):
        bot = MagicMock()
        bot.publish_surface = AsyncMock(return_value="surface-from-bot")
        tool = PublishSurfaceTool(bot=bot, surface_store="fake-store", user_id="u-1", session_id="s-1")

        result = await tool._execute(
            kind="dashboard",
            title="Q3 Revenue",
            envelope=_sample_envelope(),
            recipe_name="daily-budget",
        )

        assert result["surface_id"] == "surface-from-bot"
        assert result["kind"] == "dashboard"
        assert result["refreshable"] is True
        bot.publish_surface.assert_awaited_once()
        _, kwargs = bot.publish_surface.call_args
        assert kwargs["surface_store"] == "fake-store"
        assert kwargs["user_id"] == "u-1"
        assert kwargs["session_id"] == "s-1"
        assert kwargs["recipe_name"] == "daily-budget"

    async def test_tool_ignores_bot_without_publish_surface(self):
        bot = MagicMock(spec=["name"])  # no publish_surface attribute
        fake_store = MagicMock()
        fake_store.save = AsyncMock(return_value="surface-direct")
        tool = PublishSurfaceTool(bot=bot, surface_store=fake_store)

        result = await tool._execute(
            kind="widget", title="X", envelope=_sample_envelope("surface-direct")
        )

        assert result["surface_id"] == "surface-direct"
        fake_store.save.assert_awaited_once()


class TestToolExecuteDelegatesToStore:
    async def test_tool_execute_delegates_to_store_without_bot(self):
        fake_store = MagicMock()
        fake_store.save = AsyncMock(return_value="surface-standalone")
        tool = PublishSurfaceTool(surface_store=fake_store, agent_id="agent-x", user_id="user-x")

        result = await tool._execute(
            kind="infographic",
            title="Standalone",
            envelope=_sample_envelope("surface-standalone"),
        )

        assert result["surface_id"] == "surface-standalone"
        fake_store.save.assert_awaited_once()
        record = fake_store.save.call_args.args[0]
        assert record.agent_id == "agent-x"
        assert record.user_id == "user-x"

    async def test_tool_overwrite_false_conflict_raises(self):
        fake_store = MagicMock()
        fake_store.save = AsyncMock(side_effect=ValueError("surface already exists"))
        tool = PublishSurfaceTool(surface_store=fake_store)

        with pytest.raises(ValueError, match="already exists"):
            await tool._execute(
                kind="dashboard",
                title="X",
                envelope=_sample_envelope("surface-conflict"),
                overwrite=False,
            )

    async def test_tool_no_store_no_bot_actionable_error(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "parrot.handlers.models.ui_surfaces":
                raise ImportError("simulated: ai-parrot-server not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        tool = PublishSurfaceTool()
        with pytest.raises(RuntimeError, match="ai-parrot-server"):
            await tool._execute(
                kind="dashboard", title="X", envelope=_sample_envelope("surface-no-store")
            )
