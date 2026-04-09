"""Unit tests for TelegramCrewTransport."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from parrot.integrations.telegram.crew.transport import TelegramCrewTransport
from parrot.integrations.telegram.crew.config import TelegramCrewConfig, CrewAgentEntry
from parrot.integrations.telegram.crew.agent_card import AgentCard
from parrot.integrations.telegram.crew.coordinator import CoordinatorBot
from parrot.integrations.telegram.crew.registry import CrewRegistry


@pytest.fixture
def crew_config():
    return TelegramCrewConfig(
        group_id=-1001234567890,
        coordinator_token="000000000:coordinator_fake_token_abc",
        coordinator_username="test_coordinator_bot",
        hitl_user_ids=[123456789],
        agents={
            "TestAgent": CrewAgentEntry(
                chatbot_id="test_agent",
                bot_token="111111111:agent_fake_token_xyz",
                username="test_agent_bot",
                tags=["test"],
                skills=[{"name": "echo", "description": "Echoes input"}],
            ),
            "ReportAgent": CrewAgentEntry(
                chatbot_id="report_agent",
                bot_token="222222222:report_fake_token_abc",
                username="report_agent_bot",
                tags=["reports"],
                skills=[],
            ),
        },
    )


@pytest.fixture
def minimal_config():
    """Config with no agents — useful for testing construction."""
    return TelegramCrewConfig(
        group_id=-100999,
        coordinator_token="000000000:coordinator_min_token",
        coordinator_username="min_coord_bot",
        agents={},
    )


class TestTelegramCrewTransportConstruction:
    def test_from_config(self, crew_config):
        transport = TelegramCrewTransport.from_config(crew_config)
        assert transport.config is crew_config
        assert transport.config.group_id == -1001234567890
        assert isinstance(transport.registry, CrewRegistry)
        assert transport.coordinator is None
        assert transport._wrappers == {}

    def test_from_config_with_bot_manager(self, crew_config):
        mock_bm = MagicMock()
        transport = TelegramCrewTransport.from_config(crew_config, bot_manager=mock_bm)
        assert transport.bot_manager is mock_bm

    def test_direct_construction(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        assert transport.config.group_id == -1001234567890
        assert len(transport.config.agents) == 2

    def test_list_online_agents_empty(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        agents = transport.list_online_agents()
        assert isinstance(agents, list)
        assert len(agents) == 0


class TestTelegramCrewTransportStop:
    @pytest.mark.asyncio
    async def test_stop_calls_coordinator_stop(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        transport.coordinator = AsyncMock(spec=CoordinatorBot)
        transport.coordinator.stop = AsyncMock()
        transport.coordinator.on_agent_leave = AsyncMock()

        await transport.stop()

        transport.coordinator.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_unregisters_all_agents(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        transport.coordinator = AsyncMock(spec=CoordinatorBot)
        transport.coordinator.stop = AsyncMock()
        transport.coordinator.on_agent_leave = AsyncMock()

        # Simulate registered wrappers
        transport._wrappers = {
            "test_agent_bot": MagicMock(),
            "report_agent_bot": MagicMock(),
        }

        await transport.stop()

        assert transport.coordinator.on_agent_leave.call_count == 2
        usernames = [
            call.args[0]
            for call in transport.coordinator.on_agent_leave.call_args_list
        ]
        assert "test_agent_bot" in usernames
        assert "report_agent_bot" in usernames

    @pytest.mark.asyncio
    async def test_stop_closes_bot_sessions(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        transport.coordinator = AsyncMock(spec=CoordinatorBot)
        transport.coordinator.stop = AsyncMock()
        transport.coordinator.on_agent_leave = AsyncMock()

        mock_bot = AsyncMock()
        mock_bot.session = AsyncMock()
        mock_bot.session.close = AsyncMock()
        transport._bots = {"test_bot": mock_bot}

        await transport.stop()

        mock_bot.session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cancels_polling_tasks(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        transport.coordinator = AsyncMock(spec=CoordinatorBot)
        transport.coordinator.stop = AsyncMock()
        transport.coordinator.on_agent_leave = AsyncMock()

        # Create a real asyncio task that blocks forever
        async def forever():
            await asyncio.sleep(9999)

        real_task = asyncio.create_task(forever())
        transport._polling_tasks = [real_task]

        await transport.stop()

        assert real_task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_cleans_up_payload(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        transport.coordinator = AsyncMock(spec=CoordinatorBot)
        transport.coordinator.stop = AsyncMock()
        transport.coordinator.on_agent_leave = AsyncMock()

        mock_payload = MagicMock()
        transport._payload = mock_payload

        await transport.stop()

        mock_payload.cleanup_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_clears_internal_state(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        transport.coordinator = AsyncMock(spec=CoordinatorBot)
        transport.coordinator.stop = AsyncMock()
        transport.coordinator.on_agent_leave = AsyncMock()
        transport._wrappers = {"a": MagicMock()}
        transport._bots = {"a": MagicMock()}
        transport._dispatchers = {"a": MagicMock()}

        # Mock bot session close
        transport._bots["a"].session = AsyncMock()
        transport._bots["a"].session.close = AsyncMock()

        await transport.stop()

        assert transport._wrappers == {}
        assert transport._bots == {}
        assert transport._dispatchers == {}

    @pytest.mark.asyncio
    async def test_stop_without_coordinator(self, crew_config):
        """Stop should not raise if coordinator was never started."""
        transport = TelegramCrewTransport(crew_config)
        transport.coordinator = None

        await transport.stop()  # Should not raise


class TestTelegramCrewTransportSendMessage:
    @pytest.mark.asyncio
    async def test_send_message_delegates_to_bot(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()
        transport._bots = {"test_agent_bot": mock_bot}

        await transport.send_message(
            from_username="test_agent_bot",
            mention="@jesus",
            text="Hello from agent",
        )

        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == -1001234567890
        assert "@jesus" in call_kwargs["text"]
        assert "Hello from agent" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_send_message_with_reply(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()
        transport._bots = {"test_agent_bot": mock_bot}

        await transport.send_message(
            from_username="test_agent_bot",
            mention="@jesus",
            text="Reply text",
            reply_to_message_id=42,
        )

        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["reply_to_message_id"] == 42

    @pytest.mark.asyncio
    async def test_send_message_unknown_bot_raises(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        transport._bots = {}

        with pytest.raises(KeyError, match="No bot registered"):
            await transport.send_message(
                from_username="unknown_bot",
                mention="@jesus",
                text="Hello",
            )

    @pytest.mark.asyncio
    async def test_send_message_strips_at_prefix(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()
        transport._bots = {"test_agent_bot": mock_bot}

        await transport.send_message(
            from_username="@test_agent_bot",
            mention="@jesus",
            text="Test",
        )

        mock_bot.send_message.assert_called_once()


class TestTelegramCrewTransportSendDocument:
    @pytest.mark.asyncio
    async def test_send_document_delegates_to_payload(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        mock_bot = AsyncMock()
        transport._bots = {"test_agent_bot": mock_bot}
        mock_payload = MagicMock()
        mock_payload.send_document = AsyncMock()
        transport._payload = mock_payload

        await transport.send_document(
            from_username="test_agent_bot",
            mention="@jesus",
            file_path="/tmp/report.csv",
            caption="Q4 Report",
        )

        mock_payload.send_document.assert_called_once()
        call_kwargs = mock_payload.send_document.call_args.kwargs
        assert call_kwargs["bot"] is mock_bot
        assert call_kwargs["chat_id"] == -1001234567890
        assert call_kwargs["file_path"] == "/tmp/report.csv"
        assert "@jesus" in call_kwargs["caption"]
        assert "Q4 Report" in call_kwargs["caption"]

    @pytest.mark.asyncio
    async def test_send_document_no_payload_raises(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        transport._bots = {"test_agent_bot": AsyncMock()}
        transport._payload = None

        with pytest.raises(RuntimeError, match="DataPayload not initialized"):
            await transport.send_document(
                from_username="test_agent_bot",
                mention="@jesus",
                file_path="/tmp/report.csv",
            )


class TestTelegramCrewTransportContextManager:
    @pytest.mark.asyncio
    async def test_context_manager(self, minimal_config):
        """Async context manager calls start/stop."""
        transport = TelegramCrewTransport(minimal_config)
        transport.start = AsyncMock()
        transport.stop = AsyncMock()

        async with transport as t:
            assert t is transport
            transport.start.assert_called_once()

        transport.stop.assert_called_once()


class TestTelegramCrewTransportListOnline:
    def test_list_online_empty(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        assert transport.list_online_agents() == []

    @pytest.mark.asyncio
    async def test_list_online_with_agents(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        now = datetime.now(timezone.utc)
        card = AgentCard(
            agent_id="a1",
            agent_name="Test",
            telegram_username="test_bot",
            telegram_user_id=111,
            model="gpt-4",
            joined_at=now,
            last_seen=now,
        )
        await transport.registry.register(card)

        agents = transport.list_online_agents()
        assert len(agents) == 1
        assert agents[0].agent_name == "Test"


class TestTelegramCrewTransportGetWrapper:
    def test_get_wrapper_found(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        mock_wrapper = MagicMock()
        transport._wrappers = {"test_bot": mock_wrapper}

        assert transport.get_wrapper("test_bot") is mock_wrapper

    def test_get_wrapper_with_at_prefix(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        mock_wrapper = MagicMock()
        transport._wrappers = {"test_bot": mock_wrapper}

        assert transport.get_wrapper("@test_bot") is mock_wrapper

    def test_get_wrapper_not_found(self, crew_config):
        transport = TelegramCrewTransport(crew_config)
        assert transport.get_wrapper("nonexistent") is None


class TestTelegramCrewTransportStart:
    @pytest.mark.asyncio
    async def test_start_creates_coordinator(self, minimal_config):
        """Start with no agents should create and start the coordinator."""
        with patch(
            "parrot.integrations.telegram.crew.transport.CoordinatorBot"
        ) as MockCoord:
            mock_coord = AsyncMock()
            mock_coord.start = AsyncMock()
            MockCoord.return_value = mock_coord

            transport = TelegramCrewTransport(minimal_config)
            await transport.start()

            MockCoord.assert_called_once()
            mock_coord.start.assert_called_once()
            assert transport.coordinator is mock_coord

            # Cleanup
            transport.coordinator = AsyncMock()
            transport.coordinator.stop = AsyncMock()
            transport.coordinator.on_agent_leave = AsyncMock()
            await transport.stop()

    @pytest.mark.asyncio
    async def test_start_creates_payload(self, minimal_config):
        with patch(
            "parrot.integrations.telegram.crew.transport.CoordinatorBot"
        ) as MockCoord:
            mock_coord = AsyncMock()
            mock_coord.start = AsyncMock()
            MockCoord.return_value = mock_coord

            transport = TelegramCrewTransport(minimal_config)
            await transport.start()

            assert transport._payload is not None

            # Cleanup
            transport.coordinator = AsyncMock()
            transport.coordinator.stop = AsyncMock()
            transport.coordinator.on_agent_leave = AsyncMock()
            await transport.stop()

    @pytest.mark.asyncio
    async def test_start_agent_failure_does_not_crash(self, crew_config):
        """If one agent fails to start, the transport continues."""
        with patch(
            "parrot.integrations.telegram.crew.transport.CoordinatorBot"
        ) as MockCoord:
            mock_coord = AsyncMock()
            mock_coord.start = AsyncMock()
            mock_coord.on_agent_join = AsyncMock()
            MockCoord.return_value = mock_coord

            transport = TelegramCrewTransport(crew_config)

            # Patch _start_agent to fail
            async def failing_start(name, entry):
                raise RuntimeError("Bot API error")

            transport._start_agent = failing_start
            await transport.start()

            # Transport should still be running (coordinator started)
            assert transport.coordinator is mock_coord
            assert len(transport._wrappers) == 0

            # Cleanup
            transport.coordinator = AsyncMock()
            transport.coordinator.stop = AsyncMock()
            transport.coordinator.on_agent_leave = AsyncMock()
            await transport.stop()
