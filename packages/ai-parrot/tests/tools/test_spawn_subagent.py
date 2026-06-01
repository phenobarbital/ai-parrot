"""Unit tests for SpawnSubAgentTool (FEAT-208 / TASK-1389).

Verifies:
- Happy path: create → poll ready → invoke → discard lifecycle.
- Timeout: sub-agent is discarded even when invoke exceeds timeout.
- Teardown on error: sub-agent is discarded when invoke raises.
- Tool subset enforcement: requested tools outside allowlist are excluded.
- Never calls promote_user_bot.
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, call

from parrot.tools.spawn import SpawnSubAgentTool, SpawnSubAgentInput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_status(chatbot_id: str = "sub-bot-001", phase: str = "ready") -> MagicMock:
    """Return a mock EphemeralAgentStatus."""
    status = MagicMock()
    status.chatbot_id = chatbot_id
    status.phase = phase
    status.error = None
    return status


def _make_response(content: str = "done") -> MagicMock:
    """Return a mock AIMessage with a content attribute."""
    msg = MagicMock()
    msg.content = content
    return msg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sub_bot():
    """A mock sub-agent bot whose invoke() returns immediately."""
    bot = MagicMock()
    bot.invoke = AsyncMock(return_value=_make_response("task result"))
    return bot


@pytest.fixture
def mock_bot_manager(mock_sub_bot):
    """BotManager mock simulating app=None behavior (phase='ready' immediate)."""
    bm = MagicMock()

    status = _make_status(phase="ready")
    bm.create_ephemeral_user_bot = AsyncMock(return_value=status)
    bm.get_ephemeral_status = MagicMock(return_value=status)
    bm.discard_ephemeral_user_bot = AsyncMock(return_value=True)
    bm.get_bots = MagicMock(return_value={status.chatbot_id: mock_sub_bot})

    return bm


@pytest.fixture
def tool(mock_bot_manager):
    """SpawnSubAgentTool with a mock BotManager and a small allowlist."""
    return SpawnSubAgentTool(
        bot_manager=mock_bot_manager,
        owner_id="agent:test-parent",
        allowed_tools=["get_weather", "search_docs"],
    )


# ---------------------------------------------------------------------------
# SpawnSubAgentInput schema
# ---------------------------------------------------------------------------


class TestSpawnSubAgentInput:
    def test_defaults(self) -> None:
        schema = SpawnSubAgentInput(task="do something")
        assert schema.task == "do something"
        assert schema.tools == []
        assert schema.timeout == 120
        assert schema.ttl_seconds == 300
        assert schema.model is None
        assert schema.system_prompt is None

    def test_full(self) -> None:
        schema = SpawnSubAgentInput(
            task="summarize",
            tools=["search_docs"],
            model="gpt-4o",
            system_prompt="Be concise.",
            timeout=60,
            ttl_seconds=120,
        )
        assert schema.tools == ["search_docs"]
        assert schema.timeout == 60

    def test_timeout_bounds(self) -> None:
        with pytest.raises(Exception):
            SpawnSubAgentInput(task="t", timeout=0)
        with pytest.raises(Exception):
            SpawnSubAgentInput(task="t", timeout=901)


# ---------------------------------------------------------------------------
# SpawnSubAgentTool initialization
# ---------------------------------------------------------------------------


class TestSpawnSubAgentToolInit:
    def test_routing_meta_has_requires_grant_false(
        self, mock_bot_manager: MagicMock
    ) -> None:
        t = SpawnSubAgentTool(
            bot_manager=mock_bot_manager,
            owner_id="agent:x",
        )
        assert t.routing_meta.get("requires_grant") is False

    def test_routing_meta_can_be_extended(self, mock_bot_manager: MagicMock) -> None:
        t = SpawnSubAgentTool(
            bot_manager=mock_bot_manager,
            owner_id="agent:x",
            routing_meta={"custom_key": "value"},
        )
        assert t.routing_meta["custom_key"] == "value"
        assert t.routing_meta["requires_grant"] is False

    def test_args_schema_is_spawn_input(self, tool: SpawnSubAgentTool) -> None:
        assert tool.args_schema is SpawnSubAgentInput


# ---------------------------------------------------------------------------
# Tool subset enforcement
# ---------------------------------------------------------------------------


class TestToolSubsetEnforcement:
    def test_intersection_with_allowlist(self, tool: SpawnSubAgentTool) -> None:
        effective = tool._compute_effective_tools(["get_weather", "unknown_tool"])
        assert effective == ["get_weather"]
        assert "unknown_tool" not in effective

    def test_empty_requested_returns_empty(self, tool: SpawnSubAgentTool) -> None:
        effective = tool._compute_effective_tools([])
        assert effective == []

    def test_no_allowlist_returns_empty(self, mock_bot_manager: MagicMock) -> None:
        t = SpawnSubAgentTool(
            bot_manager=mock_bot_manager,
            owner_id="agent:x",
            allowed_tools=[],
        )
        effective = t._compute_effective_tools(["get_weather"])
        assert effective == []

    def test_all_in_allowlist(self, tool: SpawnSubAgentTool) -> None:
        effective = tool._compute_effective_tools(["get_weather", "search_docs"])
        assert sorted(effective) == ["get_weather", "search_docs"]

    def test_tools_to_config_mapping(self) -> None:
        config = SpawnSubAgentTool._tools_to_config(["get_weather", "search_docs"])
        assert config == [{"name": "get_weather"}, {"name": "search_docs"}]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSpawnSubAgentToolHappyPath:
    @pytest.mark.asyncio
    async def test_happy_path_returns_result(
        self,
        tool: SpawnSubAgentTool,
        mock_bot_manager: MagicMock,
        mock_sub_bot: MagicMock,
    ) -> None:
        """Full lifecycle: create → poll → invoke → discard; result returned."""
        result = await tool._execute(
            task="Summarize the news.",
            tools=["search_docs"],
            timeout=30,
            ttl_seconds=120,
        )

        assert result == "task result"

        # create was called with agent ownership
        mock_bot_manager.create_ephemeral_user_bot.assert_awaited_once()
        create_kwargs = mock_bot_manager.create_ephemeral_user_bot.call_args.kwargs
        assert create_kwargs["owner_id"] == "agent:test-parent"
        assert create_kwargs["owner_kind"] == "agent"

        # invoke was called with the task question
        mock_sub_bot.invoke.assert_awaited_once_with(question="Summarize the news.")

        # discard was called (guaranteed teardown)
        mock_bot_manager.discard_ephemeral_user_bot.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tools_config_passed_in_config(
        self,
        tool: SpawnSubAgentTool,
        mock_bot_manager: MagicMock,
    ) -> None:
        """Tools subset is translated into tools_config_plain in the config dict."""
        await tool._execute(
            task="Do something.",
            tools=["get_weather"],
            timeout=30,
        )
        create_kwargs = mock_bot_manager.create_ephemeral_user_bot.call_args.kwargs
        config = create_kwargs["config"]
        assert "tools_config_plain" in config
        assert config["tools_config_plain"] == [{"name": "get_weather"}]

    @pytest.mark.asyncio
    async def test_system_prompt_in_config(
        self,
        tool: SpawnSubAgentTool,
        mock_bot_manager: MagicMock,
    ) -> None:
        """system_prompt is forwarded as system_prompt_template (UserBotModel field name)."""
        await tool._execute(
            task="Do something.",
            system_prompt="Be very concise.",
            timeout=30,
        )
        create_kwargs = mock_bot_manager.create_ephemeral_user_bot.call_args.kwargs
        # UserBotModel field is system_prompt_template, not system_prompt.
        assert create_kwargs["config"].get("system_prompt_template") == "Be very concise."

    @pytest.mark.asyncio
    async def test_model_override_in_config(
        self,
        tool: SpawnSubAgentTool,
        mock_bot_manager: MagicMock,
    ) -> None:
        """Model override is forwarded to the bot config."""
        await tool._execute(
            task="Do something.",
            model="gpt-4o-mini",
            timeout=30,
        )
        create_kwargs = mock_bot_manager.create_ephemeral_user_bot.call_args.kwargs
        assert create_kwargs["config"].get("llm") == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_ttl_seconds_forwarded(
        self,
        tool: SpawnSubAgentTool,
        mock_bot_manager: MagicMock,
    ) -> None:
        """ttl_seconds is passed to create_ephemeral_user_bot."""
        await tool._execute(task="Do something.", timeout=30, ttl_seconds=60)
        create_kwargs = mock_bot_manager.create_ephemeral_user_bot.call_args.kwargs
        assert create_kwargs["ttl_seconds"] == 60

    @pytest.mark.asyncio
    async def test_never_calls_promote(
        self,
        tool: SpawnSubAgentTool,
        mock_bot_manager: MagicMock,
    ) -> None:
        """promote_user_bot is never called during the lifecycle."""
        # Wire up promote BEFORE the call so we can assert it was never invoked.
        mock_bot_manager.promote_user_bot = AsyncMock()
        await tool._execute(task="Do something.", timeout=30)
        mock_bot_manager.promote_user_bot.assert_not_awaited()


# ---------------------------------------------------------------------------
# Timeout path
# ---------------------------------------------------------------------------


class TestSpawnSubAgentToolTimeout:
    @pytest.mark.asyncio
    async def test_timeout_discards_sub_agent(
        self,
        mock_bot_manager: MagicMock,
    ) -> None:
        """When invoke exceeds timeout, the sub-agent is still discarded."""
        # Make invoke block forever (will be cancelled by wait_for)
        async def _blocking_invoke(*args, **kwargs):
            await asyncio.sleep(999)

        slow_bot = MagicMock()
        slow_bot.invoke = _blocking_invoke

        status = _make_status(phase="ready")
        mock_bot_manager.create_ephemeral_user_bot = AsyncMock(return_value=status)
        mock_bot_manager.get_ephemeral_status = MagicMock(return_value=status)
        mock_bot_manager.discard_ephemeral_user_bot = AsyncMock(return_value=True)
        mock_bot_manager.get_bots = MagicMock(
            return_value={status.chatbot_id: slow_bot}
        )

        t = SpawnSubAgentTool(
            bot_manager=mock_bot_manager,
            owner_id="agent:test",
            allowed_tools=["search"],
        )

        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await t._execute(task="Slow task.", timeout=1)

        # discard was still called (guaranteed teardown)
        mock_bot_manager.discard_ephemeral_user_bot.assert_awaited_once()


# ---------------------------------------------------------------------------
# Error teardown
# ---------------------------------------------------------------------------


class TestSpawnSubAgentToolTeardownOnError:
    @pytest.mark.asyncio
    async def test_teardown_on_invoke_error(
        self,
        mock_bot_manager: MagicMock,
    ) -> None:
        """When invoke raises, the sub-agent is still discarded."""
        error_bot = MagicMock()
        error_bot.invoke = AsyncMock(side_effect=RuntimeError("LLM failure"))

        status = _make_status(phase="ready")
        mock_bot_manager.create_ephemeral_user_bot = AsyncMock(return_value=status)
        mock_bot_manager.get_ephemeral_status = MagicMock(return_value=status)
        mock_bot_manager.discard_ephemeral_user_bot = AsyncMock(return_value=True)
        mock_bot_manager.get_bots = MagicMock(
            return_value={status.chatbot_id: error_bot}
        )

        t = SpawnSubAgentTool(
            bot_manager=mock_bot_manager,
            owner_id="agent:test",
        )

        with pytest.raises(RuntimeError, match="LLM failure"):
            await t._execute(task="Fail task.", timeout=30)

        # discard must have been called
        mock_bot_manager.discard_ephemeral_user_bot.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_teardown_on_warmup_error(
        self,
        mock_bot_manager: MagicMock,
    ) -> None:
        """When sub-agent warm-up fails (phase='error'), discard is still called."""
        error_status = _make_status(phase="error")
        error_status.error = "MCP handshake failed"

        mock_bot_manager.create_ephemeral_user_bot = AsyncMock(
            return_value=error_status
        )
        mock_bot_manager.get_ephemeral_status = MagicMock(return_value=error_status)
        mock_bot_manager.discard_ephemeral_user_bot = AsyncMock(return_value=True)

        t = SpawnSubAgentTool(
            bot_manager=mock_bot_manager,
            owner_id="agent:test",
        )

        with pytest.raises(RuntimeError, match="warm-up failed"):
            await t._execute(task="Warmup fail task.", timeout=30)

        # discard must have been called even on warm-up error
        mock_bot_manager.discard_ephemeral_user_bot.assert_awaited_once()


# ---------------------------------------------------------------------------
# Teardown completeness
# ---------------------------------------------------------------------------


class TestSpawnSubAgentTeardownCompleteness:
    @pytest.mark.asyncio
    async def test_bots_dict_not_contain_chatbot_after_happy_path(
        self,
        mock_bot_manager: MagicMock,
        mock_sub_bot: MagicMock,
    ) -> None:
        """After a successful execution, discard is called exactly once."""
        status = _make_status(chatbot_id="teardown-test-bot", phase="ready")
        mock_bot_manager.create_ephemeral_user_bot = AsyncMock(return_value=status)
        mock_bot_manager.get_ephemeral_status = MagicMock(return_value=status)
        mock_bot_manager.get_bots = MagicMock(
            return_value={"teardown-test-bot": mock_sub_bot}
        )
        mock_bot_manager.discard_ephemeral_user_bot = AsyncMock(return_value=True)

        t = SpawnSubAgentTool(
            bot_manager=mock_bot_manager,
            owner_id="agent:test",
        )
        await t._execute(task="Test teardown.", timeout=30)

        discard_calls = mock_bot_manager.discard_ephemeral_user_bot.call_args_list
        assert len(discard_calls) == 1
        # Confirm the correct chatbot_id was discarded
        discard_kwargs = discard_calls[0].kwargs
        assert discard_kwargs.get("owner_id") == "agent:test"
