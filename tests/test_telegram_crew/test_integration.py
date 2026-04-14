"""Integration tests for TelegramCrewTransport.

These tests verify end-to-end flows with all components wired together,
using mocked Telegram API calls. They ensure the crew transport works
as a cohesive system.

Implements spec Section 4, Integration Tests table.
"""
import asyncio
from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.integrations.telegram.crew.agent_card import AgentCard, AgentSkill
from parrot.integrations.telegram.crew.coordinator import CoordinatorBot
from parrot.integrations.telegram.crew.crew_wrapper import CrewAgentWrapper
from parrot.integrations.telegram.crew.transport import TelegramCrewTransport
from parrot.integrations.telegram.crew.payload import DataPayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bot_mock(username: str = "test_bot", user_id: int = 100):
    """Build an AsyncMock that acts like an aiogram Bot."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
    bot.send_chat_action = AsyncMock()
    bot.send_document = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.edit_message_text = AsyncMock()
    bot.pin_chat_message = AsyncMock()
    bot.session = AsyncMock()
    bot.session.close = AsyncMock()
    bot_user = MagicMock()
    bot_user.username = username
    bot_user.id = user_id
    bot.me = AsyncMock(return_value=bot_user)
    return bot


def _make_message(text: str, sender_username: str = "human_user",
                  sender_id: int = 123456, chat_id: int = -1001234567890):
    """Build a MagicMock that acts like an aiogram Message."""
    msg = MagicMock()
    msg.text = text
    msg.message_id = 1001
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.username = sender_username
    msg.from_user.id = sender_id
    msg.from_user.full_name = sender_username
    msg.document = None
    msg.entities = []
    return msg


# ---------------------------------------------------------------------------
# Integration Test Classes
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCrewStartupFlow:
    """Full startup: coordinator sends pinned, agents register."""

    async def test_coordinator_sends_pinned_on_start(
        self, registry, mock_bot
    ):
        """Coordinator sends and pins a registry message on start."""
        coordinator = CoordinatorBot(
            token="000000000:coordinator_fake_token_abc",
            group_id=-1001234567890,
            registry=registry,
            username="test_coordinator_bot",
            bot=mock_bot,
        )
        await coordinator.start()

        # Verify message sent and pinned
        mock_bot.send_message.assert_called_once()
        mock_bot.pin_chat_message.assert_called_once()
        assert coordinator._pinned_message_id == 42

    async def test_agents_register_on_start(
        self, sample_agent_card, second_agent_card, registry, mock_bot
    ):
        """All configured agents appear in registry after start."""
        coordinator = CoordinatorBot(
            token="000000000:coordinator_fake_token_abc",
            group_id=-1001234567890,
            registry=registry,
            username="test_coordinator_bot",
            bot=mock_bot,
        )
        await coordinator.start()

        # Register both agents (simulating transport.start())
        await coordinator.on_agent_join(sample_agent_card)
        await coordinator.on_agent_join(second_agent_card)

        # Both agents in registry
        active = registry.list_active()
        assert len(active) == 2
        usernames = {c.telegram_username for c in active}
        assert "test_agent_bot" in usernames
        assert "report_agent_bot" in usernames

    async def test_pinned_message_updated_after_registration(
        self, sample_agent_card, registry, mock_bot
    ):
        """Pinned message is edited after each agent registration."""
        coordinator = CoordinatorBot(
            token="000000000:coordinator_fake_token_abc",
            group_id=-1001234567890,
            registry=registry,
            username="test_coordinator_bot",
            bot=mock_bot,
        )
        await coordinator.start()
        mock_bot.edit_message_text.reset_mock()

        await coordinator.on_agent_join(sample_agent_card)

        # Pinned was edited at least once
        assert mock_bot.edit_message_text.call_count >= 1


@pytest.mark.integration
class TestMentionRouting:
    """Simulate @mention message, verify agent.ask() called and response sent."""

    async def test_mention_to_agent_triggers_ask(
        self, sample_agent_card, registry, mock_bot, mock_agent
    ):
        """@mention routes to correct agent.ask() call."""
        coordinator = CoordinatorBot(
            token="000000000:coordinator_fake_token_abc",
            group_id=-1001234567890,
            registry=registry,
            username="test_coordinator_bot",
            bot=mock_bot,
        )
        await coordinator.start()
        await coordinator.on_agent_join(sample_agent_card)

        # Make agent.ask yield control so typing indicator can run
        async def yielding_ask(*args, **kwargs):
            await asyncio.sleep(0)
            return "Agent response text"

        mock_agent.ask = AsyncMock(side_effect=yielding_ask)

        wrapper = CrewAgentWrapper(
            bot=mock_bot,
            agent=mock_agent,
            card=sample_agent_card,
            group_id=-1001234567890,
            coordinator=coordinator,
        )

        # Simulate incoming @mention message
        with patch(
            "parrot.integrations.telegram.crew.crew_wrapper.extract_query_from_mention",
            new_callable=AsyncMock,
            return_value="Hello agent",
        ):
            msg = _make_message("@test_agent_bot Hello agent")
            await wrapper._handle_mention(msg)

        # Agent was called with the query
        mock_agent.ask.assert_called_once()
        call_args = mock_agent.ask.call_args
        assert "Hello agent" in call_args.args[0]

    async def test_response_includes_sender_mention(
        self, sample_agent_card, registry, mock_bot, mock_agent
    ):
        """Agent response includes @mention of the original sender."""
        coordinator = CoordinatorBot(
            token="000000000:coordinator_fake_token_abc",
            group_id=-1001234567890,
            registry=registry,
            username="test_coordinator_bot",
            bot=mock_bot,
        )
        await coordinator.start()
        await coordinator.on_agent_join(sample_agent_card)

        async def yielding_ask(*args, **kwargs):
            await asyncio.sleep(0)
            return "Here is my response"

        mock_agent.ask = AsyncMock(side_effect=yielding_ask)

        wrapper = CrewAgentWrapper(
            bot=mock_bot,
            agent=mock_agent,
            card=sample_agent_card,
            group_id=-1001234567890,
            coordinator=coordinator,
        )

        with patch(
            "parrot.integrations.telegram.crew.crew_wrapper.extract_query_from_mention",
            new_callable=AsyncMock,
            return_value="What is the status?",
        ):
            msg = _make_message(
                "@test_agent_bot What is the status?",
                sender_username="human_user",
            )
            await wrapper._handle_mention(msg)

        # The response should contain @human_user somewhere
        sent_text = mock_bot.send_message.call_args_list[-1].kwargs.get(
            "text", mock_bot.send_message.call_args_list[-1].args[0]
            if mock_bot.send_message.call_args_list[-1].args else ""
        )
        assert "@human_user" in sent_text


@pytest.mark.integration
class TestAgentDelegation:
    """Agent A sends @mention to Agent B, B processes and replies."""

    async def test_agent_to_agent(self, registry, mock_agent):
        """Agent A @mentions Agent B, B processes and replies to A."""
        bot_b = _make_bot_mock("agent_b_bot", 1002)

        coordinator_bot = _make_bot_mock("coordinator_bot", 1000)
        coordinator = CoordinatorBot(
            token="000000000:coordinator_fake_token_abc",
            group_id=-1001234567890,
            registry=registry,
            username="coordinator_bot",
            bot=coordinator_bot,
        )
        await coordinator.start()

        # Create cards for both agents
        now = datetime.now(timezone.utc)
        card_a = AgentCard(
            agent_id="agent_a",
            agent_name="AgentA",
            telegram_username="agent_a_bot",
            telegram_user_id=1001,
            model="test:model",
            skills=[AgentSkill(name="analyze", description="Analyze data")],
            tags=["analysis"],
            joined_at=now,
            last_seen=now,
        )
        card_b = AgentCard(
            agent_id="agent_b",
            agent_name="AgentB",
            telegram_username="agent_b_bot",
            telegram_user_id=1002,
            model="test:model",
            skills=[AgentSkill(name="report", description="Generate reports")],
            tags=["reports"],
            joined_at=now,
            last_seen=now,
        )

        await coordinator.on_agent_join(card_a)
        await coordinator.on_agent_join(card_b)

        # Create Agent B wrapper with a mock AI agent
        agent_b_ai = AsyncMock()

        async def yielding_ask(*args, **kwargs):
            await asyncio.sleep(0)
            return "Report generated by Agent B"

        agent_b_ai.ask = AsyncMock(side_effect=yielding_ask)

        wrapper_b = CrewAgentWrapper(
            bot=bot_b,
            agent=agent_b_ai,
            card=card_b,
            group_id=-1001234567890,
            coordinator=coordinator,
        )

        # Agent A sends message mentioning Agent B
        with patch(
            "parrot.integrations.telegram.crew.crew_wrapper.extract_query_from_mention",
            new_callable=AsyncMock,
            return_value="Generate the quarterly report",
        ):
            msg = _make_message(
                "@agent_b_bot Generate the quarterly report",
                sender_username="agent_a_bot",
                sender_id=1001,
            )
            await wrapper_b._handle_mention(msg)

        # Agent B's AI was called
        agent_b_ai.ask.assert_called_once()
        assert "Generate the quarterly report" in agent_b_ai.ask.call_args.args[0]

        # Response sent by Agent B should mention Agent A
        last_send = bot_b.send_message.call_args_list[-1]
        sent_text = last_send.kwargs.get("text", "")
        assert "@agent_a_bot" in sent_text


@pytest.mark.integration
class TestDocumentExchange:
    """Agent sends CSV document, recipient downloads and processes."""

    async def test_csv_exchange(
        self, sample_agent_card, registry, mock_bot, mock_agent, tmp_path
    ):
        """Agent receives a CSV document, processes it, and responds."""
        coordinator_bot = _make_bot_mock("coordinator_bot", 1000)
        coordinator = CoordinatorBot(
            token="000000000:coordinator_fake_token_abc",
            group_id=-1001234567890,
            registry=registry,
            username="coordinator_bot",
            bot=coordinator_bot,
        )
        await coordinator.start()
        await coordinator.on_agent_join(sample_agent_card)

        # Create a real CSV file in tmp_path
        csv_path = tmp_path / "test_data.csv"
        csv_path.write_text("name,value\nalpha,1\nbeta,2\n")

        payload = DataPayload(
            temp_dir=str(tmp_path),
            max_file_size_mb=50,
        )

        # Mock download_document to return the CSV path
        payload.download_document = AsyncMock(return_value=str(csv_path))

        async def yielding_ask(*args, **kwargs):
            await asyncio.sleep(0)
            return "Processed CSV with 2 rows"

        mock_agent.ask = AsyncMock(side_effect=yielding_ask)

        wrapper = CrewAgentWrapper(
            bot=mock_bot,
            agent=mock_agent,
            card=sample_agent_card,
            group_id=-1001234567890,
            coordinator=coordinator,
            payload=payload,
        )

        # Build a message with a document attachment
        msg = _make_message(
            "Analyze this data",
            sender_username="data_user",
        )
        msg.document = MagicMock()
        msg.document.file_name = "test_data.csv"
        msg.document.mime_type = "text/csv"
        msg.document.file_size = 100
        msg.document.file_id = "abc123"
        msg.caption = "Analyze this data"

        await wrapper._handle_document(msg)

        # Agent was called with document context
        mock_agent.ask.assert_called_once()
        call_text = mock_agent.ask.call_args.args[0]
        assert "test_data.csv" in call_text or "Document" in call_text

        # Response was sent back
        assert mock_bot.send_message.call_count >= 1
        last_send = mock_bot.send_message.call_args_list[-1]
        sent_text = last_send.kwargs.get("text", "")
        assert "@data_user" in sent_text


@pytest.mark.integration
class TestStatusLifecycle:
    """Agent goes ready -> busy -> ready, pinned message reflects each state."""

    async def test_ready_busy_ready(
        self, sample_agent_card, registry, mock_bot, mock_agent
    ):
        """Agent transitions ready -> busy -> ready, pinned reflects changes."""
        coordinator = CoordinatorBot(
            token="000000000:coordinator_fake_token_abc",
            group_id=-1001234567890,
            registry=registry,
            username="test_coordinator_bot",
            bot=mock_bot,
        )
        await coordinator.start()
        await coordinator.on_agent_join(sample_agent_card)

        # Initial state: ready (default)
        card = registry.get("test_agent_bot")
        assert card is not None
        assert card.status == "ready"

        # Simulate status changes as they happen during mention handling
        mock_bot.edit_message_text.reset_mock()

        # Transition to busy
        await coordinator.on_agent_status_change(
            "test_agent_bot", "busy", "processing query"
        )
        card = registry.get("test_agent_bot")
        assert card.status == "busy"
        assert card.current_task == "processing query"

        # Pinned message was edited to reflect busy
        assert mock_bot.edit_message_text.call_count >= 1
        busy_call = mock_bot.edit_message_text.call_args
        busy_text = busy_call.kwargs.get("text", "")
        assert "busy" in busy_text.lower() or "test_agent_bot" in busy_text

        # Transition back to ready
        mock_bot.edit_message_text.reset_mock()
        await coordinator.on_agent_status_change("test_agent_bot", "ready")
        card = registry.get("test_agent_bot")
        assert card.status == "ready"

        # Pinned message updated again
        assert mock_bot.edit_message_text.call_count >= 1


@pytest.mark.integration
class TestGracefulShutdown:
    """All agents unregistered, pinned updated, bot sessions closed."""

    async def test_shutdown_unregisters_all(
        self, sample_agent_card, second_agent_card, registry, mock_bot
    ):
        """All agents unregistered, pinned updated, sessions closed on shutdown."""
        coordinator = CoordinatorBot(
            token="000000000:coordinator_fake_token_abc",
            group_id=-1001234567890,
            registry=registry,
            username="test_coordinator_bot",
            bot=mock_bot,
        )
        await coordinator.start()
        await coordinator.on_agent_join(sample_agent_card)
        await coordinator.on_agent_join(second_agent_card)

        # Create mock bots for the agents
        agent_bot_1 = _make_bot_mock("test_agent_bot", 999999)
        agent_bot_2 = _make_bot_mock("report_agent_bot", 888888)

        # Simulate transport internal state
        transport = TelegramCrewTransport.__new__(TelegramCrewTransport)
        transport.config = MagicMock()
        transport.config.group_id = -1001234567890
        transport.registry = registry
        transport.coordinator = coordinator
        transport._wrappers = {
            "test_agent_bot": MagicMock(),
            "report_agent_bot": MagicMock(),
        }
        transport._bots = {
            "test_agent_bot": agent_bot_1,
            "report_agent_bot": agent_bot_2,
        }
        transport._dispatchers = {}
        transport._polling_tasks = []
        transport._payload = MagicMock()
        transport._payload.cleanup_all = MagicMock()
        transport.logger = MagicMock()

        # Verify 2 agents registered before shutdown
        assert len(registry.list_active()) == 2

        # Graceful shutdown
        await transport.stop()

        # All agents unregistered
        assert len(registry.list_active()) == 0

        # Bot sessions closed
        agent_bot_1.session.close.assert_called_once()
        agent_bot_2.session.close.assert_called_once()

        # Coordinator session closed
        mock_bot.session.close.assert_called()

        # Payload cleaned up
        transport._payload.cleanup_all.assert_called_once()

        # Internal state cleared
        assert len(transport._wrappers) == 0
        assert len(transport._bots) == 0
