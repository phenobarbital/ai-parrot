"""Tests for the Matrix multi-agent crew integration (FEAT-044).

Unit tests for:
- Config loading and validation (TASK-296)
- Mention parsing/formatting utilities (TASK-297)
- Agent registry CRUD and concurrent access (TASK-298)
- Coordinator status board rendering (TASK-299)
- Agent wrapper chunking logic (TASK-300)
- Transport routing logic (TASK-301)

Integration tests (with mocks):
- Message routing by dedicated room
- Message routing by @mention
- Message routing to default agent
- Ignore self-messages
- Coordinator refresh on status change
- Transport lifecycle (start/stop)
"""
from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from parrot.integrations.matrix.crew.config import (
    MatrixCrewAgentEntry,
    MatrixCrewConfig,
)
from parrot.integrations.matrix.crew.coordinator import MatrixCoordinator
from parrot.integrations.matrix.crew.crew_wrapper import MatrixCrewAgentWrapper
from parrot.integrations.matrix.crew.mention import (
    build_pill,
    format_reply,
    parse_mention,
)
from parrot.integrations.matrix.crew.registry import (
    MatrixAgentCard,
    MatrixCrewRegistry,
)
from parrot.integrations.matrix.crew.transport import MatrixCrewTransport


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def crew_config() -> MatrixCrewConfig:
    """Sample crew config with 2 agents."""
    return MatrixCrewConfig(
        homeserver_url="https://matrix.example.com",
        server_name="example.com",
        as_token="as_token_123",
        hs_token="hs_token_456",
        bot_mxid="@coordinator:example.com",
        general_room_id="!general:example.com",
        agents={
            "analyst": MatrixCrewAgentEntry(
                chatbot_id="finance-analyst",
                display_name="Financial Analyst",
                mxid_localpart="analyst",
                dedicated_room_id="!analyst-room:example.com",
                skills=["Stock analysis", "Financial ratios"],
                tags=["finance"],
            ),
            "assistant": MatrixCrewAgentEntry(
                chatbot_id="general-bot",
                display_name="General Assistant",
                mxid_localpart="assistant",
                skills=["General Q&A"],
                tags=["general"],
            ),
        },
        unaddressed_agent="assistant",
    )


@pytest.fixture
def mock_appservice():
    """Mock MatrixAppService with bot_intent() returning mock intents."""
    appservice = MagicMock()
    mock_intent = AsyncMock()
    appservice._get_intent = MagicMock(return_value=mock_intent)
    appservice.bot_intent = mock_intent
    appservice.send_as_agent = AsyncMock(return_value="$event001")
    appservice.send_as_bot = AsyncMock(return_value="$event002")
    appservice.register_agent = AsyncMock(side_effect=lambda name, _: f"@{name}:example.com")
    appservice.ensure_agent_in_room = AsyncMock()
    appservice.set_event_callback = MagicMock()
    appservice.start = AsyncMock()
    appservice.stop = AsyncMock()
    appservice._registered_agents = {
        "analyst": "@analyst:example.com",
        "assistant": "@assistant:example.com",
    }
    return appservice


@pytest.fixture
def mock_bot_manager():
    """Mock BotManager.get_bot() returning a stub agent with .ask()."""
    bot = AsyncMock()
    bot.ask = AsyncMock(return_value="This is a test response from the agent.")
    return bot


@pytest.fixture
async def registry() -> MatrixCrewRegistry:
    """Populated in-memory registry with 2 agents."""
    reg = MatrixCrewRegistry()
    analyst_card = MatrixAgentCard(
        agent_name="analyst",
        display_name="Financial Analyst",
        mxid="@analyst:example.com",
        skills=["Stock analysis"],
    )
    assistant_card = MatrixAgentCard(
        agent_name="assistant",
        display_name="General Assistant",
        mxid="@assistant:example.com",
        skills=["General Q&A"],
    )
    await reg.register(analyst_card)
    await reg.register(assistant_card)
    return reg


@pytest.fixture
def mock_coordinator_client():
    """Mock client for MatrixCoordinator."""
    client = MagicMock()
    client.send_text = AsyncMock(return_value="$status_event_001")
    client.edit_message = AsyncMock(return_value="$status_event_002")
    client.set_room_state = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# TASK-296: Config Tests
# ---------------------------------------------------------------------------


class TestMatrixCrewConfig:
    """Unit tests for MatrixCrewConfig and MatrixCrewAgentEntry."""

    def test_config_from_dict(self) -> None:
        """Validate MatrixCrewConfig with valid data."""
        config = MatrixCrewConfig(
            homeserver_url="https://matrix.example.com",
            server_name="example.com",
            as_token="token",
            hs_token="hs",
            bot_mxid="@bot:example.com",
            general_room_id="!room:example.com",
        )
        assert config.homeserver_url == "https://matrix.example.com"
        assert config.server_name == "example.com"

    def test_config_defaults(self) -> None:
        """Verify default values are set correctly."""
        config = MatrixCrewConfig(
            homeserver_url="https://matrix.example.com",
            server_name="example.com",
            as_token="t",
            hs_token="h",
            bot_mxid="@b:example.com",
            general_room_id="!r:example.com",
        )
        assert config.appservice_port == 8449
        assert config.typing_indicator is True
        assert config.streaming is True
        assert config.pinned_registry is True
        assert config.max_message_length == 4096
        assert config.unaddressed_agent is None

    def test_config_missing_required(self) -> None:
        """Ensure ValidationError on missing required fields."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MatrixCrewConfig(
                server_name="example.com",
                as_token="t",
                hs_token="h",
                bot_mxid="@b:example.com",
                general_room_id="!r:example.com",
                # Missing homeserver_url
            )

    def test_config_from_yaml(self, tmp_path, monkeypatch) -> None:
        """Load a YAML string, verify env var substitution."""
        monkeypatch.setenv("TEST_AS_TOKEN", "yaml_as_token_value")
        monkeypatch.setenv("TEST_SERVER", "yaml.example.com")

        yaml_content = {
            "homeserver_url": "https://matrix.example.com",
            "server_name": "${TEST_SERVER}",
            "as_token": "${TEST_AS_TOKEN}",
            "hs_token": "static_hs",
            "bot_mxid": "@bot:example.com",
            "general_room_id": "!room:example.com",
        }
        yaml_file = tmp_path / "crew.yaml"
        yaml_file.write_text(yaml.dump(yaml_content))

        config = MatrixCrewConfig.from_yaml(str(yaml_file))
        assert config.as_token == "yaml_as_token_value"
        assert config.server_name == "yaml.example.com"

    def test_agent_entry_validation(self) -> None:
        """Validate MatrixCrewAgentEntry fields."""
        entry = MatrixCrewAgentEntry(
            chatbot_id="my-bot",
            display_name="My Bot",
            mxid_localpart="mybot",
            skills=["Skill A"],
            tags=["tag1"],
            file_types=["image/png"],
        )
        assert entry.chatbot_id == "my-bot"
        assert entry.dedicated_room_id is None
        assert entry.avatar_url is None
        assert len(entry.skills) == 1


# ---------------------------------------------------------------------------
# TASK-297: Mention Tests
# ---------------------------------------------------------------------------


class TestMentionParsing:
    """Unit tests for mention parsing and formatting utilities."""

    def test_mention_parse_plain_text(self) -> None:
        """@analyst what is AAPL? → analyst."""
        result = parse_mention("@analyst what is AAPL?", "example.com")
        assert result == "analyst"

    def test_mention_parse_pill_html(self) -> None:
        """Extract localpart from Matrix pill HTML."""
        body = '<a href="https://matrix.to/#/@analyst:example.com">analyst</a> question'
        result = parse_mention(body, "example.com")
        assert result == "analyst"

    def test_mention_parse_no_mention(self) -> None:
        """No mention in body → None."""
        result = parse_mention("What is AAPL?", "example.com")
        assert result is None

    def test_mention_parse_wrong_server(self) -> None:
        """Pill mention for wrong server → None."""
        body = '<a href="https://matrix.to/#/@analyst:other.com">analyst</a>'
        result = parse_mention(body, "example.com")
        assert result is None

    def test_mention_parse_plain_at_start(self) -> None:
        """@mention at start of message."""
        result = parse_mention("@researcher find me papers on LLMs", "example.com")
        assert result == "researcher"

    def test_build_pill(self) -> None:
        """Verify HTML pill output format."""
        pill = build_pill("@analyst:example.com", "Financial Analyst")
        assert 'href="https://matrix.to/#/@analyst:example.com"' in pill
        assert "Financial Analyst" in pill
        assert "<a " in pill
        assert "</a>" in pill

    def test_format_reply(self) -> None:
        """Verify reply formatting."""
        reply = format_reply("@analyst:example.com", "Financial Analyst", "AAPL P/E is 28")
        assert "Financial Analyst" in reply
        assert "AAPL P/E is 28" in reply


# ---------------------------------------------------------------------------
# TASK-298: Registry Tests
# ---------------------------------------------------------------------------


class TestMatrixCrewRegistry:
    """Unit tests for MatrixCrewRegistry CRUD operations."""

    @pytest.mark.asyncio
    async def test_registry_register(self) -> None:
        """Register an agent and verify retrieval."""
        reg = MatrixCrewRegistry()
        card = MatrixAgentCard(
            agent_name="analyst",
            display_name="Financial Analyst",
            mxid="@analyst:example.com",
        )
        await reg.register(card)
        result = await reg.get("analyst")
        assert result is not None
        assert result.agent_name == "analyst"
        assert result.status == "ready"
        assert result.joined_at is not None

    @pytest.mark.asyncio
    async def test_registry_unregister(self) -> None:
        """Register then unregister — verify agent is gone."""
        reg = MatrixCrewRegistry()
        card = MatrixAgentCard(
            agent_name="analyst",
            display_name="Financial Analyst",
            mxid="@analyst:example.com",
        )
        await reg.register(card)
        await reg.unregister("analyst")
        result = await reg.get("analyst")
        assert result is None

    @pytest.mark.asyncio
    async def test_registry_update_status(self) -> None:
        """Register, update to busy, verify status and last_seen."""
        reg = MatrixCrewRegistry()
        card = MatrixAgentCard(
            agent_name="analyst",
            display_name="Financial Analyst",
            mxid="@analyst:example.com",
        )
        await reg.register(card)
        before = datetime.now(timezone.utc)
        await reg.update_status("analyst", "busy", "Analyzing AAPL")
        result = await reg.get("analyst")
        assert result.status == "busy"
        assert result.current_task == "Analyzing AAPL"
        assert result.last_seen >= before

    @pytest.mark.asyncio
    async def test_registry_get_by_mxid(self) -> None:
        """Register, then lookup by MXID."""
        reg = MatrixCrewRegistry()
        card = MatrixAgentCard(
            agent_name="analyst",
            display_name="Financial Analyst",
            mxid="@analyst:example.com",
        )
        await reg.register(card)
        result = await reg.get_by_mxid("@analyst:example.com")
        assert result is not None
        assert result.agent_name == "analyst"

    @pytest.mark.asyncio
    async def test_registry_all_agents(self) -> None:
        """Register 3 agents and verify all are returned."""
        reg = MatrixCrewRegistry()
        for name in ["analyst", "researcher", "assistant"]:
            card = MatrixAgentCard(
                agent_name=name,
                display_name=f"{name.title()} Bot",
                mxid=f"@{name}:example.com",
            )
            await reg.register(card)
        agents = await reg.all_agents()
        assert len(agents) == 3

    @pytest.mark.asyncio
    async def test_registry_concurrent_access(self) -> None:
        """Multiple concurrent status updates must not corrupt state."""
        reg = MatrixCrewRegistry()
        card = MatrixAgentCard(
            agent_name="analyst",
            display_name="Financial Analyst",
            mxid="@analyst:example.com",
        )
        await reg.register(card)

        async def update(status: str, task: Optional[str] = None) -> None:
            await reg.update_status("analyst", status, task)

        await asyncio.gather(
            update("busy", "task-1"),
            update("busy", "task-2"),
            update("busy", "task-3"),
            update("ready"),
            update("busy", "task-5"),
        )
        result = await reg.get("analyst")
        assert result is not None  # State is consistent


# ---------------------------------------------------------------------------
# Agent Card Status Line Tests
# ---------------------------------------------------------------------------


class TestAgentCardStatusLine:
    """Unit tests for MatrixAgentCard.to_status_line()."""

    def test_status_line_ready(self) -> None:
        """Status line for ready agent."""
        card = MatrixAgentCard(
            agent_name="analyst",
            display_name="Financial Analyst",
            mxid="@analyst:example.com",
            status="ready",
            skills=["Stock analysis"],
        )
        line = card.to_status_line()
        assert "[ready]" in line
        assert "@analyst" in line
        assert "Financial Analyst" in line
        assert "Stock analysis" in line

    def test_status_line_busy(self) -> None:
        """Status line for busy agent with current task."""
        card = MatrixAgentCard(
            agent_name="researcher",
            display_name="Research Assistant",
            mxid="@researcher:example.com",
            status="busy",
            current_task="summarizing report",
        )
        line = card.to_status_line()
        assert "[busy: summarizing report]" in line
        assert "@researcher" in line

    def test_status_line_offline(self) -> None:
        """Status line for offline agent."""
        card = MatrixAgentCard(
            agent_name="assistant",
            display_name="General Assistant",
            mxid="@assistant:example.com",
            status="offline",
        )
        line = card.to_status_line()
        assert "[offline]" in line
        assert "@assistant" in line


# ---------------------------------------------------------------------------
# TASK-299: Coordinator Tests
# ---------------------------------------------------------------------------


class TestMatrixCoordinator:
    """Unit tests for MatrixCoordinator."""

    @pytest.mark.asyncio
    async def test_coordinator_start_sends_and_pins(
        self, mock_coordinator_client, registry
    ) -> None:
        """start() sends a status board message and pins it."""
        coord = MatrixCoordinator(
            client=mock_coordinator_client,
            registry=registry,
            general_room_id="!general:example.com",
        )
        await coord.start()

        mock_coordinator_client.send_text.assert_called_once()
        assert coord._status_event_id == "$status_event_001"
        mock_coordinator_client.set_room_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_coordinator_refresh_edits_message(
        self, mock_coordinator_client, registry
    ) -> None:
        """refresh_status_board() edits the pinned message."""
        coord = MatrixCoordinator(
            client=mock_coordinator_client,
            registry=registry,
            general_room_id="!general:example.com",
            rate_limit_interval=0.0,  # disable rate limit for test
        )
        await coord.start()
        # Reset last_update to force refresh
        coord._last_update = 0.0
        await coord.refresh_status_board()
        mock_coordinator_client.edit_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_coordinator_rate_limit(
        self, mock_coordinator_client, registry
    ) -> None:
        """Rate limiting prevents excessive edits."""
        coord = MatrixCoordinator(
            client=mock_coordinator_client,
            registry=registry,
            general_room_id="!general:example.com",
            rate_limit_interval=60.0,  # very long — will always skip
        )
        await coord.start()
        # Immediate second refresh should be skipped
        await coord.refresh_status_board()
        await coord.refresh_status_board()
        await coord.refresh_status_board()
        # edit_message should NOT have been called (rate-limited)
        mock_coordinator_client.edit_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_coordinator_stop_sends_notice(
        self, mock_coordinator_client, registry
    ) -> None:
        """stop() posts a shutdown notice."""
        coord = MatrixCoordinator(
            client=mock_coordinator_client,
            registry=registry,
            general_room_id="!general:example.com",
        )
        await coord.stop()
        mock_coordinator_client.send_text.assert_called_once()
        args = mock_coordinator_client.send_text.call_args
        assert "shutting down" in args[0][1].lower() or "offline" in args[0][1].lower()


# ---------------------------------------------------------------------------
# TASK-300: Agent Wrapper Tests
# ---------------------------------------------------------------------------


class TestMatrixCrewAgentWrapper:
    """Unit tests for MatrixCrewAgentWrapper._chunk_text()."""

    def test_chunk_text_short(self) -> None:
        """Short text is returned as single chunk."""
        chunks = MatrixCrewAgentWrapper._chunk_text("Short text", 200)
        assert chunks == ["Short text"]

    def test_chunk_text_long(self) -> None:
        """Long text is split into multiple chunks."""
        text = "A" * 250
        chunks = MatrixCrewAgentWrapper._chunk_text(text, 50)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 50

    def test_chunk_text_paragraph_boundary(self) -> None:
        """Chunks prefer paragraph boundaries."""
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph that is longer."
        chunks = MatrixCrewAgentWrapper._chunk_text(text, 30)
        assert len(chunks) >= 2

    def test_chunk_text_exact_length(self) -> None:
        """Text exactly at max_length is single chunk."""
        text = "A" * 100
        chunks = MatrixCrewAgentWrapper._chunk_text(text, 100)
        assert chunks == [text]


# ---------------------------------------------------------------------------
# Integration Tests (with mocks)
# ---------------------------------------------------------------------------


class TestMessageRouting:
    """Integration tests for message routing in MatrixCrewTransport."""

    def _make_transport(self, crew_config, mock_appservice, registry):
        """Create a partially-initialized transport for routing tests."""
        from parrot.integrations.matrix.crew.coordinator import MatrixCoordinator
        from parrot.integrations.matrix.crew.crew_wrapper import MatrixCrewAgentWrapper

        transport = MatrixCrewTransport.__new__(MatrixCrewTransport)
        transport._config = crew_config
        transport._appservice = mock_appservice
        transport._registry = registry
        transport._wrappers = {}
        transport._room_to_agent = {"!analyst-room:example.com": "analyst"}
        transport._agent_mxids = {
            "@analyst:example.com",
            "@assistant:example.com",
            "@coordinator:example.com",
        }
        transport.logger = __import__("logging").getLogger("test.transport")

        # Create mock wrappers
        for name in ["analyst", "assistant"]:
            wrapper = MagicMock()
            wrapper.handle_message = AsyncMock()
            transport._wrappers[name] = wrapper

        return transport

    @pytest.mark.asyncio
    async def test_message_routing_dedicated_room(
        self, crew_config, mock_appservice, registry
    ) -> None:
        """Message to dedicated room → correct wrapper receives it."""
        transport = self._make_transport(crew_config, mock_appservice, registry)
        await transport.on_room_message(
            room_id="!analyst-room:example.com",
            sender="@user:example.com",
            body="What is AAPL P/E?",
            event_id="$evt001",
        )
        transport._wrappers["analyst"].handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_message_routing_mention(
        self, crew_config, mock_appservice, registry
    ) -> None:
        """@mention in general room → mentioned agent handles it."""
        transport = self._make_transport(crew_config, mock_appservice, registry)
        await transport.on_room_message(
            room_id="!general:example.com",
            sender="@user:example.com",
            body="@analyst what is the P/E ratio?",
            event_id="$evt002",
        )
        transport._wrappers["analyst"].handle_message.assert_awaited_once()
        transport._wrappers["assistant"].handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_message_routing_default_agent(
        self, crew_config, mock_appservice, registry
    ) -> None:
        """Unmentioned message → default agent handles it."""
        transport = self._make_transport(crew_config, mock_appservice, registry)
        await transport.on_room_message(
            room_id="!general:example.com",
            sender="@user:example.com",
            body="What time is it?",
            event_id="$evt003",
        )
        transport._wrappers["assistant"].handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_message_routing_ignore_self(
        self, crew_config, mock_appservice, registry
    ) -> None:
        """Messages from agent MXIDs are ignored."""
        transport = self._make_transport(crew_config, mock_appservice, registry)
        await transport.on_room_message(
            room_id="!general:example.com",
            sender="@analyst:example.com",  # self
            body="I am responding",
            event_id="$evt004",
        )
        transport._wrappers["analyst"].handle_message.assert_not_awaited()
        transport._wrappers["assistant"].handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_coordinator_refresh_on_status_change(
        self, mock_coordinator_client, registry
    ) -> None:
        """Status board reflects agent state changes."""
        coord = MatrixCoordinator(
            client=mock_coordinator_client,
            registry=registry,
            general_room_id="!general:example.com",
            rate_limit_interval=0.0,
        )
        await coord.start()
        coord._last_update = 0.0  # reset to allow refresh
        await coord.on_status_change("analyst")
        mock_coordinator_client.edit_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_transport_lifecycle(
        self, crew_config, mock_appservice
    ) -> None:
        """start() initializes components; stop() cleans up.

        We test stop() directly since start() requires a real homeserver.
        """
        transport = MatrixCrewTransport(crew_config)

        # Simulate a partially-started state
        transport._coordinator = MagicMock()
        transport._coordinator.stop = AsyncMock()
        transport._appservice = mock_appservice
        transport._registry = MatrixCrewRegistry()
        transport._wrappers = {}

        await transport.stop()
        transport._coordinator.stop.assert_awaited_once()
        mock_appservice.stop.assert_awaited_once()
