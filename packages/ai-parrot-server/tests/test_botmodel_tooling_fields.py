"""Tests for FEAT-593 database-backed agent tooling fields."""

from unittest.mock import MagicMock

import pytest

from parrot.handlers.bots import STUDIO_ONLY_FIELDS, ChatbotHandler
from parrot.handlers.models.bots import BotModel
from parrot.tools.spec import ToolkitSpec


def test_defaults() -> None:
    """New tooling fields use nullable-safe defaults."""
    model = BotModel(name="x")

    assert model.toolkit_config == {}
    assert model.mcp_servers == []


def test_to_bot_config_normalizes() -> None:
    """Configured toolkits replace their duplicate plain tool names."""
    model = BotModel(
        name="x",
        tools=["jira", "weather"],
        toolkit_config={"jira": {"params": {"default_project": "T"}}},
    )

    config = model.to_bot_config()

    assert "weather" in config["tools"]
    assert "jira" not in config["tools"]
    assert any(isinstance(tool, ToolkitSpec) and tool.slug == "jira" for tool in config["tools"])
    assert config["agent_mcp_servers"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", sorted(STUDIO_ONLY_FIELDS))
async def test_put_database_rejects(field: str) -> None:
    """Direct creates cannot bypass the Agent Studio tooling vault."""
    handler = ChatbotHandler.__new__(ChatbotHandler)
    handler.error = MagicMock(side_effect=lambda response, status: (response, status))

    response, status = await ChatbotHandler._put_database(handler, {"name": "x", field: {}})

    assert status == 400
    assert response["code"] == "use_studio_endpoint"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", sorted(STUDIO_ONLY_FIELDS))
async def test_post_database_rejects(field: str) -> None:
    """Direct updates cannot bypass the Agent Studio tooling vault."""
    handler = ChatbotHandler.__new__(ChatbotHandler)
    handler.error = MagicMock(side_effect=lambda response, status: (response, status))

    response, status = await ChatbotHandler._post_database(handler, MagicMock(), {field: {}})

    assert status == 400
    assert response["code"] == "use_studio_endpoint"
