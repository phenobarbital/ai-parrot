"""Tests for Telegram wrapper handle_photo attachment passthrough."""
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
from parrot.integrations.telegram.models import TelegramAgentConfig
from parrot.integrations.telegram.auth import TelegramUserSession


def _make_wrapper():
    """Create a TelegramAgentWrapper with fully mocked dependencies."""
    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.bot = AsyncMock()
    wrapper.agent = AsyncMock()
    with patch("parrot.integrations.telegram.models.config") as mock_cfg:
        mock_cfg.get.return_value = "fake:token"
        wrapper.config = TelegramAgentConfig(
            name="test_agent",
            chatbot_id="test_agent",
            bot_token="fake:token",
        )
    wrapper.logger = MagicMock()
    wrapper._user_sessions = {}
    wrapper._auth_client = None
    wrapper._callback_registry = None

    # Mock internal helpers that depend on heavy imports
    wrapper.conversations = {}
    wrapper._is_authorized = MagicMock(return_value=True)
    wrapper._check_authentication = AsyncMock(return_value=True)

    fake_session = TelegramUserSession(
        telegram_id=456,
        telegram_username="testuser",
        telegram_first_name="Test",
        telegram_last_name="User",
    )
    wrapper._get_user_session = MagicMock(return_value=fake_session)
    wrapper._get_or_create_memory = MagicMock(return_value=MagicMock())

    wrapper._parse_response = MagicMock(return_value=MagicMock(text="ok"))
    wrapper._send_parsed_response = AsyncMock()
    wrapper.bot.send_chat_action = AsyncMock()

    return wrapper


def _make_photo_message(chat_id: int = 123, caption: str = None):
    """Create a mocked Telegram photo Message."""
    msg = AsyncMock()
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = 456
    msg.from_user.username = "testuser"
    msg.from_user.first_name = "Test"
    msg.from_user.last_name = "User"
    msg.caption = caption

    photo_obj = MagicMock()
    photo_obj.file_id = "AgACAgIAAxkBAAIBZ"
    msg.photo = [MagicMock(), photo_obj]

    return msg


def _setup_file_download(wrapper):
    """Configure bot mocks so file download creates a real temp file."""
    mock_file = MagicMock()
    mock_file.file_path = "photos/file_0.jpg"
    wrapper.bot.get_file = AsyncMock(return_value=mock_file)
    wrapper.bot.download_file = AsyncMock()


@pytest.mark.asyncio
async def test_add_comment_passes_attachments_to_ask():
    """Verify handle_photo passes attachments kwarg to agent.ask()."""
    wrapper = _make_wrapper()
    _setup_file_download(wrapper)

    # Remove ask_with_image so it falls back to ask()
    del wrapper.agent.ask_with_image

    msg = _make_photo_message(caption="Check this screenshot")
    await wrapper.handle_photo(msg)

    wrapper.agent.ask.assert_called_once()
    call_kwargs = wrapper.agent.ask.call_args[1]

    assert "attachments" in call_kwargs
    assert isinstance(call_kwargs["attachments"], list)
    assert len(call_kwargs["attachments"]) == 1
    assert call_kwargs["attachments"][0].endswith(".jpg")

    # Cleanup
    Path(call_kwargs["attachments"][0]).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_photo_enriches_caption_with_path():
    """Verify caption includes the saved file path."""
    wrapper = _make_wrapper()
    _setup_file_download(wrapper)

    del wrapper.agent.ask_with_image

    msg = _make_photo_message(caption="Bug screenshot")
    await wrapper.handle_photo(msg)

    question = wrapper.agent.ask.call_args[0][0]
    assert "Bug screenshot" in question
    assert "[Attached image saved at:" in question

    # Cleanup
    att_path = wrapper.agent.ask.call_args[1]["attachments"][0]
    Path(att_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_photo_tempfile_persists():
    """Verify temp file is NOT deleted after handle_photo returns."""
    wrapper = _make_wrapper()
    _setup_file_download(wrapper)

    del wrapper.agent.ask_with_image

    msg = _make_photo_message()
    await wrapper.handle_photo(msg)

    att_path = wrapper.agent.ask.call_args[1]["attachments"][0]
    # File should still exist (not deleted by handle_photo)
    assert Path(att_path).exists()

    # Cleanup
    Path(att_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_handle_photo_with_ask_with_image():
    """Verify attachments kwarg is passed to ask_with_image too."""
    wrapper = _make_wrapper()

    mock_file = MagicMock()
    mock_file.file_path = "photos/file_0.png"
    wrapper.bot.get_file = AsyncMock(return_value=mock_file)
    wrapper.bot.download_file = AsyncMock()

    # Keep ask_with_image on the agent
    wrapper.agent.ask_with_image = AsyncMock(return_value="Image described")

    msg = _make_photo_message(caption="Describe this")
    await wrapper.handle_photo(msg)

    wrapper.agent.ask_with_image.assert_called_once()
    call_kwargs = wrapper.agent.ask_with_image.call_args[1]

    assert "attachments" in call_kwargs
    assert len(call_kwargs["attachments"]) == 1
    assert call_kwargs["attachments"][0].endswith(".png")
    assert "image_path" in call_kwargs

    # Cleanup
    Path(call_kwargs["attachments"][0]).unlink(missing_ok=True)
