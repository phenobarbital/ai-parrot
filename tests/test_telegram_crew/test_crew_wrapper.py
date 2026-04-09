"""Unit tests for CrewAgentWrapper."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, timezone
from pathlib import Path

from parrot.integrations.telegram.crew.crew_wrapper import (
    CrewAgentWrapper,
    _chunk_text,
)
from parrot.integrations.telegram.crew.agent_card import AgentCard
from parrot.integrations.telegram.crew.coordinator import CoordinatorBot
from parrot.integrations.telegram.crew.registry import CrewRegistry
from parrot.integrations.telegram.crew.payload import DataPayload


@pytest.fixture
def mock_agent():
    agent = AsyncMock()
    agent.ask = AsyncMock(return_value="Test response from agent")
    return agent


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.send_chat_action = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.send_document = AsyncMock()
    # Mock bot.me() for extract_query_from_mention
    bot_user = MagicMock()
    bot_user.username = "test_bot"
    bot.me = AsyncMock(return_value=bot_user)
    return bot


@pytest.fixture
def sample_card():
    return AgentCard(
        agent_id="agent1",
        agent_name="TestAgent",
        telegram_username="test_bot",
        telegram_user_id=111,
        model="gpt-4",
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_coordinator():
    coord = AsyncMock(spec=CoordinatorBot)
    coord.on_agent_status_change = AsyncMock()
    return coord


@pytest.fixture
def mock_payload():
    payload = MagicMock(spec=DataPayload)
    payload.download_document = AsyncMock(return_value="/tmp/test_doc.csv")
    payload.cleanup_file = MagicMock()
    return payload


@pytest.fixture
def wrapper(mock_bot, mock_agent, sample_card, mock_coordinator, mock_payload):
    return CrewAgentWrapper(
        bot=mock_bot,
        agent=mock_agent,
        card=sample_card,
        group_id=-100123,
        coordinator=mock_coordinator,
        payload=mock_payload,
    )


def _make_message(text="@test_bot what is Python?", username="jesus", user_id=42):
    """Create a mock Telegram message."""
    message = MagicMock()
    message.text = text
    message.caption = None
    message.document = None
    message.chat = MagicMock()
    message.chat.id = -100123
    message.message_id = 99
    message.from_user = MagicMock()
    message.from_user.username = username
    message.from_user.id = user_id
    message.from_user.full_name = "Jesus Lara"
    # Set up entities for mention detection
    entity = MagicMock()
    entity.type = "mention"
    entity.offset = 0
    entity.length = len("@test_bot")
    message.entities = [entity]
    return message


class TestChunkText:
    def test_short_text_no_split(self):
        text = "Hello world"
        chunks = _chunk_text(text)
        assert chunks == ["Hello world"]

    def test_exact_limit(self):
        text = "a" * 4096
        chunks = _chunk_text(text)
        assert len(chunks) == 1
        assert len(chunks[0]) == 4096

    def test_long_text_splits(self):
        text = "Line one\n" * 500  # ~5000 chars
        chunks = _chunk_text(text, max_length=100)
        for chunk in chunks:
            assert len(chunk) <= 100

    def test_preserves_word_boundaries(self):
        # Long single line that exceeds limit
        text = "word " * 1000  # 5000 chars
        chunks = _chunk_text(text, max_length=100)
        for chunk in chunks:
            assert len(chunk) <= 100

    def test_empty_text(self):
        assert _chunk_text("") == [""]

    def test_single_very_long_word(self):
        text = "a" * 5000
        chunks = _chunk_text(text, max_length=100)
        assert all(len(c) <= 100 for c in chunks)


class TestCrewAgentWrapper:
    def test_init(self, wrapper, mock_bot, mock_agent, sample_card):
        assert wrapper.bot is mock_bot
        assert wrapper.agent is mock_agent
        assert wrapper.card is sample_card
        assert wrapper.group_id == -100123
        assert wrapper.router is not None

    def test_get_sender_mention_with_username(self, wrapper):
        message = _make_message(username="jesus")
        mention = wrapper._get_sender_mention(message)
        assert mention == "@jesus"

    def test_get_sender_mention_without_username(self, wrapper):
        message = _make_message()
        message.from_user.username = None
        mention = wrapper._get_sender_mention(message)
        assert mention == "Jesus Lara"

    def test_get_sender_mention_no_user(self, wrapper):
        message = _make_message()
        message.from_user = None
        mention = wrapper._get_sender_mention(message)
        assert mention == "User"

    @pytest.mark.asyncio
    async def test_handle_mention_calls_agent(self, wrapper, mock_agent, mock_bot):
        message = _make_message(text="@test_bot what is Python?")
        await wrapper._handle_mention(message)

        mock_agent.ask.assert_called_once()
        call_kwargs = mock_agent.ask.call_args
        assert "what is Python?" in call_kwargs.args[0]

    @pytest.mark.asyncio
    async def test_handle_mention_sends_response_with_sender(
        self, wrapper, mock_bot
    ):
        message = _make_message(username="jesus")
        await wrapper._handle_mention(message)

        mock_bot.send_message.assert_called()
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "@jesus" in sent_text

    @pytest.mark.asyncio
    async def test_handle_mention_includes_agent_response(
        self, wrapper, mock_bot, mock_agent
    ):
        mock_agent.ask = AsyncMock(return_value="Python is a language")
        message = _make_message()
        await wrapper._handle_mention(message)

        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "Python is a language" in sent_text

    @pytest.mark.asyncio
    async def test_handle_mention_creates_typing_task(self, wrapper, mock_bot, mock_agent):
        """Verify that _typing_indicator is started during mention handling."""
        # Make agent.ask yield control so the typing task can start
        async def yielding_ask(*args, **kwargs):
            await asyncio.sleep(0)
            return "response"

        mock_agent.ask = yielding_ask
        message = _make_message()
        await wrapper._handle_mention(message)

        mock_bot.send_chat_action.assert_called()

    @pytest.mark.asyncio
    async def test_handle_mention_status_busy_then_ready(
        self, wrapper, mock_coordinator
    ):
        message = _make_message()
        await wrapper._handle_mention(message)

        calls = mock_coordinator.on_agent_status_change.call_args_list
        assert len(calls) >= 2
        # First call: busy
        assert calls[0].args[1] == "busy"
        # Last call: ready
        assert calls[-1].args[1] == "ready"

    @pytest.mark.asyncio
    async def test_handle_mention_empty_query_ignored(
        self, wrapper, mock_agent, mock_bot
    ):
        # Message that is just the mention with no query
        message = _make_message(text="@test_bot")
        await wrapper._handle_mention(message)

        mock_agent.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_mention_error_sends_error_message(
        self, wrapper, mock_agent, mock_bot
    ):
        mock_agent.ask = AsyncMock(side_effect=Exception("LLM error"))
        message = _make_message()
        await wrapper._handle_mention(message)

        mock_bot.send_message.assert_called()
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "error" in sent_text.lower()

    @pytest.mark.asyncio
    async def test_handle_document_downloads_and_processes(
        self, wrapper, mock_agent, mock_payload, mock_bot
    ):
        message = _make_message()
        message.document = MagicMock()
        message.document.file_name = "data.csv"
        message.caption = "Analyze this CSV"

        await wrapper._handle_document(message)

        mock_payload.download_document.assert_called_once_with(
            mock_bot, message
        )
        mock_agent.ask.assert_called_once()
        query = mock_agent.ask.call_args.args[0]
        assert "Analyze this CSV" in query

    @pytest.mark.asyncio
    async def test_handle_document_cleanup(
        self, wrapper, mock_payload
    ):
        message = _make_message()
        message.document = MagicMock()
        message.caption = "Check this file"

        await wrapper._handle_document(message)

        mock_payload.cleanup_file.assert_called_once_with("/tmp/test_doc.csv")

    @pytest.mark.asyncio
    async def test_handle_document_download_failure(
        self, wrapper, mock_payload, mock_bot
    ):
        mock_payload.download_document = AsyncMock(return_value=None)
        message = _make_message()
        message.document = MagicMock()

        await wrapper._handle_document(message)

        mock_bot.send_message.assert_called()
        sent_text = mock_bot.send_message.call_args.kwargs["text"]
        assert "Could not download" in sent_text

    @pytest.mark.asyncio
    async def test_handle_document_no_payload(
        self, mock_bot, mock_agent, sample_card, mock_coordinator
    ):
        """Without a DataPayload configured, documents are ignored."""
        wrapper = CrewAgentWrapper(
            bot=mock_bot,
            agent=mock_agent,
            card=sample_card,
            group_id=-100123,
            coordinator=mock_coordinator,
            payload=None,
        )
        message = _make_message()
        message.document = MagicMock()

        await wrapper._handle_document(message)

        mock_agent.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_response_chunks_long_text(self, wrapper, mock_bot):
        long_text = "word " * 2000  # ~10000 chars
        mock_agent_response = MagicMock()
        mock_agent_response.text = long_text
        mock_agent_response.images = []
        mock_agent_response.documents = []
        mock_agent_response.media = []

        with patch(
            "parrot.integrations.telegram.crew.crew_wrapper.parse_response"
        ) as mock_parse:
            parsed = MagicMock()
            parsed.text = long_text
            parsed.images = []
            parsed.documents = []
            parsed.media = []
            mock_parse.return_value = parsed

            await wrapper._send_response(
                -100123, parsed, "@jesus", reply_to_message_id=99
            )

        # Multiple chunks should have been sent
        assert mock_bot.send_message.call_count > 1
        # All sent text should be under 4096
        for call in mock_bot.send_message.call_args_list:
            assert len(call.kwargs["text"]) <= 4096

    @pytest.mark.asyncio
    async def test_output_mode_telegram(self, wrapper, mock_agent):
        message = _make_message()
        await wrapper._handle_mention(message)

        call_kwargs = mock_agent.ask.call_args.kwargs
        assert call_kwargs["output_mode"] == "telegram"

    @pytest.mark.asyncio
    async def test_reply_to_original_message(self, wrapper, mock_bot):
        message = _make_message()
        message.message_id = 99
        await wrapper._handle_mention(message)

        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["reply_to_message_id"] == 99
