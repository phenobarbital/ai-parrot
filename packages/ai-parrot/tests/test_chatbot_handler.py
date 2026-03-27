"""Unit tests for ChatbotHandler.

Tests the unified agent management handler that manages agents
from both PostgreSQL (BotModel) and AgentRegistry (YAML/BotConfig).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Lightweight fakes to avoid importing the full navigator / asyncdb stack
# ---------------------------------------------------------------------------


class FakeBotModel:
    """Minimal BotModel stand-in."""

    class Meta:
        connection = None

    def __init__(self, **kwargs):
        self.chatbot_id = kwargs.get("chatbot_id", uuid.uuid4())
        self.name = kwargs.get("name", "test_bot")
        self.enabled = kwargs.get("enabled", True)
        self.bot_class = kwargs.get("bot_class", "BasicBot")
        self.description = kwargs.get("description", "A test bot")
        self.created_at = kwargs.get("created_at", datetime.now())
        self.updated_at = kwargs.get("updated_at", datetime.now())
        self._data = kwargs

    def to_dict(self) -> dict:
        return {
            "chatbot_id": self.chatbot_id,
            "name": self.name,
            "enabled": self.enabled,
            "description": self.description,
            "bot_class": self.bot_class,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_bot_config(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
        }

    def set(self, key: str, val: Any) -> None:
        setattr(self, key, val)

    async def insert(self) -> None:
        pass

    async def update(self) -> None:
        pass

    async def delete(self) -> None:
        pass

    @classmethod
    async def filter(cls, **kwargs):
        return []

    @classmethod
    async def get(cls, **kwargs):
        from asyncdb.exceptions import NoDataFound
        raise NoDataFound("Not found")


class FakeBotMetadata:
    """Minimal BotMetadata stand-in."""

    def __init__(self, name: str, bot_config=None, **kwargs):
        self.name = name
        self.bot_config = bot_config
        self.module_path = kwargs.get("module_path", "test.module")
        self.file_path = kwargs.get("file_path", "agents/test.yaml")
        self.singleton = kwargs.get("singleton", False)
        self.at_startup = kwargs.get("at_startup", False)
        self.priority = kwargs.get("priority", 0)
        self.tags = kwargs.get("tags", set())


class FakeBotConfig:
    """Minimal BotConfig stand-in."""

    def __init__(self, **kwargs):
        self.name = kwargs.get("name", "test_bot")
        self.class_name = kwargs.get("class_name", "BasicBot")
        self.module = kwargs.get("module", "parrot.bots.basic")
        self.enabled = kwargs.get("enabled", True)
        self.config = kwargs.get("config", {})
        self.singleton = kwargs.get("singleton", False)
        self.at_startup = kwargs.get("at_startup", False)
        self.tags = kwargs.get("tags", set())
        self.priority = kwargs.get("priority", 0)

    def model_dump(self, mode: str = "json") -> dict:
        return {
            "name": self.name,
            "class_name": self.class_name,
            "module": self.module,
            "enabled": self.enabled,
        }


class FakeAgentRegistry:
    """Minimal AgentRegistry stand-in."""

    def __init__(self):
        self._registered_agents: Dict[str, FakeBotMetadata] = {}

    def has(self, name: str) -> bool:
        return name in self._registered_agents

    def create_agent_factory(self, config):
        return MagicMock()

    def create_agent_definition(self, config, category="general"):
        from pathlib import Path
        return Path(f"agents/agents/{category}/{config.name}.yaml")

    async def get_instance(self, name: str):
        meta = self._registered_agents.get(name)
        if meta:
            bot = MagicMock()
            bot.name = name
            bot.is_configured = False
            bot.configure = AsyncMock()
            return bot
        return None


class FakeBotManager:
    """Minimal BotManager stand-in."""

    def __init__(self, registry=None):
        self.registry = registry or FakeAgentRegistry()
        self._bots: Dict[str, Any] = {}

    def get_bot_class(self, name: str):
        return MagicMock

    def create_bot(self, class_name=None, name=None, **kwargs):
        bot = MagicMock()
        bot.name = name
        bot.configure = AsyncMock()
        return bot

    def add_bot(self, bot) -> None:
        self._bots[bot.name] = bot

    def remove_bot(self, name: str) -> None:
        self._bots.pop(name, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler(
    *,
    match_info: dict | None = None,
    query: dict | None = None,
    json_body: dict | None = None,
    manager: FakeBotManager | None = None,
):
    """Build a ChatbotHandler-like object using mocks for the request."""
    from parrot.handlers.bots import ChatbotHandler

    mgr = manager or FakeBotManager()

    request = MagicMock()
    request.match_info = match_info or {}
    request.app = {"bot_manager": mgr}
    request.method = "GET"

    # query_parameters used by BaseView
    handler = ChatbotHandler.__new__(ChatbotHandler)
    handler.request = request
    handler.logger = MagicMock()
    handler._session = {}
    handler.handler = MagicMock()  # ConnectionHandler mock

    # Stub query_parameters
    handler.query_parameters = MagicMock(return_value=query or {})
    # Stub json_data
    handler.json_data = AsyncMock(return_value=json_body)
    # Stub session
    handler.session = AsyncMock()
    # Stub response helpers
    handler.json_response = MagicMock(side_effect=lambda data, **kw: data)
    handler.error = MagicMock(side_effect=lambda response, status=400: {
        **response, "_status": status
    })
    handler.get_userid = AsyncMock(return_value=1)

    return handler


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetEndpoint:
    """Tests for GET /api/v1/bots."""

    @pytest.mark.asyncio
    async def test_get_all_empty(self):
        """GET returns empty list when no agents exist."""
        handler = _make_handler()
        handler._get_db_agents = AsyncMock(return_value=[])

        result = await handler.get()

        assert result["agents"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_get_all_db_agents(self):
        """GET returns DB agents with source='database'."""
        db_bot = FakeBotModel(name="db_bot")
        handler = _make_handler()
        handler._get_db_agents = AsyncMock(return_value=[db_bot])

        result = await handler.get()

        assert result["total"] == 1
        assert result["agents"][0]["name"] == "db_bot"
        assert result["agents"][0]["source"] == "database"

    @pytest.mark.asyncio
    async def test_get_all_registry_agents(self):
        """GET returns registry agents with source='registry'."""
        registry = FakeAgentRegistry()
        registry._registered_agents["reg_bot"] = FakeBotMetadata(
            name="reg_bot"
        )
        mgr = FakeBotManager(registry=registry)

        handler = _make_handler(manager=mgr)
        handler._get_db_agents = AsyncMock(return_value=[])

        result = await handler.get()

        assert result["total"] == 1
        assert result["agents"][0]["name"] == "reg_bot"
        assert result["agents"][0]["source"] == "registry"

    @pytest.mark.asyncio
    async def test_get_all_merged_dedup(self):
        """GET deduplicates: DB agent wins over same-name registry agent."""
        db_bot = FakeBotModel(name="shared_bot")
        registry = FakeAgentRegistry()
        registry._registered_agents["shared_bot"] = FakeBotMetadata(
            name="shared_bot"
        )
        mgr = FakeBotManager(registry=registry)

        handler = _make_handler(manager=mgr)
        handler._get_db_agents = AsyncMock(return_value=[db_bot])

        result = await handler.get()

        assert result["total"] == 1
        assert result["agents"][0]["source"] == "database"

    @pytest.mark.asyncio
    async def test_get_one_from_db(self):
        """GET /{name} returns DB agent if found."""
        db_bot = FakeBotModel(name="my_bot")
        handler = _make_handler(match_info={"id": "my_bot"})
        handler._get_db_agent = AsyncMock(return_value=db_bot)

        result = await handler.get()

        assert result["name"] == "my_bot"
        assert result["source"] == "database"

    @pytest.mark.asyncio
    async def test_get_one_from_registry(self):
        """GET /{name} falls back to registry when not in DB."""
        registry = FakeAgentRegistry()
        registry._registered_agents["reg_bot"] = FakeBotMetadata(
            name="reg_bot"
        )
        mgr = FakeBotManager(registry=registry)

        handler = _make_handler(match_info={"id": "reg_bot"}, manager=mgr)
        handler._get_db_agent = AsyncMock(return_value=None)

        result = await handler.get()

        assert result["name"] == "reg_bot"
        assert result["source"] == "registry"

    @pytest.mark.asyncio
    async def test_get_one_not_found(self):
        """GET /{name} returns 404 when agent not found anywhere."""
        handler = _make_handler(match_info={"id": "nonexistent"})
        handler._get_db_agent = AsyncMock(return_value=None)

        result = await handler.get()

        assert result["_status"] == 404


class TestPutEndpoint:
    """Tests for PUT /api/v1/bots."""

    @pytest.mark.asyncio
    async def test_put_rejects_duplicate(self):
        """PUT returns 409 when agent name already exists."""
        handler = _make_handler(json_body={
            "name": "existing_bot",
            "storage": "database",
        })
        handler._check_duplicate = AsyncMock(return_value="database")

        result = await handler.put()

        assert result["_status"] == 409

    @pytest.mark.asyncio
    async def test_put_requires_name(self):
        """PUT returns 400 when name is missing."""
        handler = _make_handler(json_body={"storage": "database"})
        handler._check_duplicate = AsyncMock(return_value=None)

        result = await handler.put()

        assert result["_status"] == 400

    @pytest.mark.asyncio
    async def test_put_invalid_storage(self):
        """PUT returns 400 for invalid storage value."""
        handler = _make_handler(json_body={
            "name": "new_bot",
            "storage": "invalid",
        })
        handler._check_duplicate = AsyncMock(return_value=None)

        result = await handler.put()

        assert result["_status"] == 400


class TestPostEndpoint:
    """Tests for POST /api/v1/bots/{name}."""

    @pytest.mark.asyncio
    async def test_post_requires_name(self):
        """POST returns 400 when no agent name in URL."""
        handler = _make_handler(json_body={"description": "updated"})

        result = await handler.post()

        assert result["_status"] == 400

    @pytest.mark.asyncio
    async def test_post_not_found(self):
        """POST returns 404 when agent not found in DB or registry."""
        handler = _make_handler(
            match_info={"id": "nonexistent"},
            json_body={"description": "updated"},
        )
        handler._get_db_agent = AsyncMock(return_value=None)

        result = await handler.post()

        assert result["_status"] == 404

    @pytest.mark.asyncio
    async def test_post_db_agent_priority(self):
        """POST updates DB agent when it exists (DB has priority)."""
        db_bot = FakeBotModel(name="my_bot")
        handler = _make_handler(
            match_info={"id": "my_bot"},
            json_body={"description": "updated"},
        )
        handler._get_db_agent = AsyncMock(return_value=db_bot)
        handler._post_database = AsyncMock(return_value={
            "message": "updated", "source": "database",
        })

        result = await handler.post()

        handler._post_database.assert_awaited_once()
        assert result["source"] == "database"


class TestDeleteEndpoint:
    """Tests for DELETE /api/v1/bots/{name}."""

    @pytest.mark.asyncio
    async def test_delete_requires_name(self):
        """DELETE returns 400 when no agent name."""
        handler = _make_handler()

        result = await handler.delete()

        assert result["_status"] == 400

    @pytest.mark.asyncio
    async def test_delete_rejects_registry_agent(self):
        """DELETE returns 403 for registry-only agents."""
        registry = FakeAgentRegistry()
        registry._registered_agents["yaml_bot"] = FakeBotMetadata(
            name="yaml_bot"
        )
        mgr = FakeBotManager(registry=registry)

        handler = _make_handler(
            match_info={"id": "yaml_bot"},
            manager=mgr,
        )
        handler._get_db_agent = AsyncMock(return_value=None)

        result = await handler.delete()

        assert result["_status"] == 403

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """DELETE returns 404 when agent not in database."""
        handler = _make_handler(match_info={"id": "nonexistent"})
        handler._get_db_agent = AsyncMock(return_value=None)

        result = await handler.delete()

        assert result["_status"] == 404


class TestHelperMethods:
    """Tests for internal helper methods."""

    def test_bot_model_to_dict(self):
        """_bot_model_to_dict adds source='database' and stringifies UUID."""
        handler = _make_handler()
        bot = FakeBotModel(name="test", chatbot_id=uuid.uuid4())

        result = handler._bot_model_to_dict(bot)

        assert result["source"] == "database"
        assert isinstance(result["chatbot_id"], str)

    def test_registry_agent_to_dict_with_config(self):
        """_registry_agent_to_dict uses bot_config.model_dump when available."""
        handler = _make_handler()
        config = FakeBotConfig(name="reg_bot")
        meta = FakeBotMetadata(name="reg_bot", bot_config=config)

        result = handler._registry_agent_to_dict("reg_bot", meta)

        assert result["source"] == "registry"
        assert result["name"] == "reg_bot"

    def test_registry_agent_to_dict_without_config(self):
        """_registry_agent_to_dict falls back to metadata fields."""
        handler = _make_handler()
        meta = FakeBotMetadata(name="code_bot", bot_config=None)

        result = handler._registry_agent_to_dict("code_bot", meta)

        assert result["source"] == "registry"
        assert result["name"] == "code_bot"
        assert "module_path" in result

    def test_agent_name_from_request_id(self):
        """_agent_name_from_request extracts from match_info 'id'."""
        handler = _make_handler(match_info={"id": "my_bot"})

        assert handler._agent_name_from_request() == "my_bot"

    def test_agent_name_from_request_query(self):
        """_agent_name_from_request falls back to query parameter 'name'."""
        handler = _make_handler(query={"name": "query_bot"})

        assert handler._agent_name_from_request() == "query_bot"

    def test_agent_name_from_request_none(self):
        """_agent_name_from_request returns None when not available."""
        handler = _make_handler()

        assert handler._agent_name_from_request() is None

    @pytest.mark.asyncio
    async def test_check_duplicate_db(self):
        """_check_duplicate returns 'database' when agent in DB."""
        handler = _make_handler()
        handler._get_db_agent = AsyncMock(
            return_value=FakeBotModel(name="dup")
        )

        result = await handler._check_duplicate("dup")

        assert result == "database"

    @pytest.mark.asyncio
    async def test_check_duplicate_registry(self):
        """_check_duplicate returns 'registry' when agent in registry."""
        registry = FakeAgentRegistry()
        registry._registered_agents["dup"] = FakeBotMetadata(name="dup")
        mgr = FakeBotManager(registry=registry)

        handler = _make_handler(manager=mgr)
        handler._get_db_agent = AsyncMock(return_value=None)

        result = await handler._check_duplicate("dup")

        assert result == "registry"

    @pytest.mark.asyncio
    async def test_check_duplicate_none(self):
        """_check_duplicate returns None when not found anywhere."""
        handler = _make_handler()
        handler._get_db_agent = AsyncMock(return_value=None)

        result = await handler._check_duplicate("new_bot")

        assert result is None
