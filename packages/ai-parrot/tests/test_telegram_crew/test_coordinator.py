"""Unit tests for CoordinatorBot."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from parrot.integrations.telegram.crew.coordinator import CoordinatorBot
from parrot.integrations.telegram.crew.registry import CrewRegistry
from parrot.integrations.telegram.crew.agent_card import AgentCard


@pytest.fixture
def registry():
    return CrewRegistry()


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
    bot.edit_message_text = AsyncMock()
    bot.pin_chat_message = AsyncMock()
    bot.session = AsyncMock()
    bot.session.close = AsyncMock()
    return bot


@pytest.fixture
def coordinator(registry, mock_bot):
    coord = CoordinatorBot(
        token="000000000:fake_token_for_testing",
        group_id=-100123,
        registry=registry,
        username="coord_bot",
        bot=mock_bot,
    )
    return coord


@pytest.fixture
def sample_card():
    return AgentCard(
        agent_id="agent1",
        agent_name="DataAgent",
        telegram_username="data_bot",
        telegram_user_id=111,
        model="gpt-4",
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


@pytest.fixture
def second_card():
    return AgentCard(
        agent_id="agent2",
        agent_name="ReportAgent",
        telegram_username="report_bot",
        telegram_user_id=222,
        model="claude-3",
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


class TestCoordinatorBot:
    def test_render_registry_empty(self, coordinator):
        text = coordinator._render_registry()
        assert isinstance(text, str)
        assert "No agents registered" in text

    def test_render_registry_with_agents(self, coordinator, sample_card):
        coordinator.registry._agents["data_bot"] = sample_card
        text = coordinator._render_registry()
        assert "Crew Registry" in text
        assert "@data_bot" in text
        assert "DataAgent" in text
        assert "Active: 1/1" in text

    def test_render_registry_mixed_status(self, coordinator, sample_card, second_card):
        coordinator.registry._agents["data_bot"] = sample_card
        second_card.status = "offline"
        coordinator.registry._agents["report_bot"] = second_card
        text = coordinator._render_registry()
        assert "Active: 1/2" in text
        assert "@data_bot" in text
        assert "@report_bot" in text

    @pytest.mark.asyncio
    async def test_start(self, coordinator):
        await coordinator.start()
        coordinator.bot.send_message.assert_called_once()
        coordinator.bot.pin_chat_message.assert_called_once()
        assert coordinator._pinned_message_id == 42

    @pytest.mark.asyncio
    async def test_stop(self, coordinator):
        await coordinator.stop()
        coordinator.bot.session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_join_updates_pinned(self, coordinator, sample_card):
        coordinator._pinned_message_id = 42
        await coordinator.on_agent_join(sample_card)
        assert coordinator.registry.get("data_bot") is not None
        coordinator.bot.edit_message_text.assert_called()

    @pytest.mark.asyncio
    async def test_agent_join_pinned_text_contains_agent(self, coordinator, sample_card):
        coordinator._pinned_message_id = 42
        await coordinator.on_agent_join(sample_card)
        call_kwargs = coordinator.bot.edit_message_text.call_args.kwargs
        assert "@data_bot" in call_kwargs["text"]
        assert "DataAgent" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_agent_leave(self, coordinator, sample_card):
        coordinator._pinned_message_id = 42
        await coordinator.on_agent_join(sample_card)
        coordinator.bot.edit_message_text.reset_mock()
        await coordinator.on_agent_leave("data_bot")
        assert coordinator.registry.get("data_bot") is None
        coordinator.bot.edit_message_text.assert_called()

    @pytest.mark.asyncio
    async def test_status_change(self, coordinator, sample_card):
        coordinator._pinned_message_id = 42
        await coordinator.on_agent_join(sample_card)
        coordinator.bot.edit_message_text.reset_mock()
        await coordinator.on_agent_status_change("data_bot", "busy", "processing Q2")
        card = coordinator.registry.get("data_bot")
        assert card.status == "busy"
        assert card.current_task == "processing Q2"
        coordinator.bot.edit_message_text.assert_called()

    @pytest.mark.asyncio
    async def test_status_change_pinned_text(self, coordinator, sample_card):
        coordinator._pinned_message_id = 42
        await coordinator.on_agent_join(sample_card)
        await coordinator.on_agent_status_change("data_bot", "busy", "processing Q2")
        call_kwargs = coordinator.bot.edit_message_text.call_args.kwargs
        assert "processing Q2" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_update_registry_no_pinned(self, coordinator):
        # Should not raise when no pinned message
        coordinator._pinned_message_id = None
        await coordinator.update_registry()
        coordinator.bot.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_registry_message_not_modified(self, coordinator, sample_card):
        coordinator._pinned_message_id = 42
        coordinator.bot.edit_message_text = AsyncMock(
            side_effect=Exception("Bad Request: message is not modified")
        )
        await coordinator.on_agent_join(sample_card)
        # Should not raise — "not modified" errors are silently ignored

    @pytest.mark.asyncio
    async def test_update_registry_other_error_logged(self, coordinator, sample_card):
        coordinator._pinned_message_id = 42
        coordinator.bot.edit_message_text = AsyncMock(
            side_effect=Exception("Network error")
        )
        await coordinator.on_agent_join(sample_card)
        # Should not raise, but the error is logged (not silenced)

    @pytest.mark.asyncio
    async def test_concurrent_updates_serialized(self, coordinator, sample_card, second_card):
        coordinator._pinned_message_id = 42
        # Both joins should be serialized by the lock
        await asyncio.gather(
            coordinator.on_agent_join(sample_card),
            coordinator.on_agent_join(second_card),
        )
        assert coordinator.registry.get("data_bot") is not None
        assert coordinator.registry.get("report_bot") is not None

    @pytest.mark.asyncio
    async def test_start_pin_failure(self, coordinator):
        coordinator.bot.pin_chat_message = AsyncMock(
            side_effect=Exception("Insufficient rights")
        )
        # Should not raise — pin failure is warned but not fatal
        await coordinator.start()
        assert coordinator._pinned_message_id == 42
