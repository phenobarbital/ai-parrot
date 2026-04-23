"""Unit tests for FEAT-120 reply context extraction.

Tests verify:
- _extract_reply_context returns correct XML for all message types
- Truncation, cache usage, config disable work correctly
- handler integration in handle_message, handle_photo, handle_voice
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_wrapper(enable_reply_context: bool = True):
    """Create a minimal TelegramAgentWrapper for testing _extract_reply_context."""
    from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
    from parrot.integrations.telegram.models import TelegramAgentConfig

    config = TelegramAgentConfig(
        name="test-bot",
        chatbot_id="testbot",
        enable_reply_context=enable_reply_context,
    )
    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.config = config
    wrapper.logger = MagicMock()
    wrapper._message_id_cache = {}
    return wrapper


def _make_message(
    chat_id: int = 1001,
    msg_id: int = 50,
    text: str = "hello",
    reply_to=None,
):
    """Create a mock Message."""
    message = MagicMock()
    message.chat.id = chat_id
    message.message_id = msg_id
    message.text = text
    message.reply_to_message = reply_to
    return message


def _make_reply(
    msg_id: int = 10,
    text: str = None,
    caption: str = None,
    voice=None,
    document=None,
):
    """Create a mock reply_to_message."""
    reply = MagicMock()
    reply.message_id = msg_id
    reply.text = text
    reply.caption = caption
    reply.voice = voice
    reply.document = document
    return reply


class TestExtractReplyContext:
    """Tests for _extract_reply_context helper."""

    def test_text_message_reply(self):
        """Reply to text → returns <reply_context>text</reply_context>."""
        wrapper = _make_wrapper()
        reply = _make_reply(text="Original message")
        message = _make_message(reply_to=reply)

        result = wrapper._extract_reply_context(message)
        assert result == "<reply_context>Original message</reply_context>\n"

    def test_caption_reply(self):
        """Reply to photo with caption → returns caption in XML."""
        wrapper = _make_wrapper()
        reply = _make_reply(text=None, caption="Image caption here")
        message = _make_message(reply_to=reply)

        result = wrapper._extract_reply_context(message)
        assert result == "<reply_context>Image caption here</reply_context>\n"

    def test_voice_reply(self):
        """Reply to voice → returns [Voice message] placeholder."""
        wrapper = _make_wrapper()
        voice_mock = MagicMock()  # non-None voice
        reply = _make_reply(text=None, caption=None, voice=voice_mock)
        message = _make_message(reply_to=reply)

        result = wrapper._extract_reply_context(message)
        assert result == "<reply_context>[Voice message]</reply_context>\n"

    def test_document_reply_with_filename(self):
        """Reply to document → returns [Document: filename.pdf] placeholder."""
        wrapper = _make_wrapper()
        doc_mock = MagicMock()
        doc_mock.file_name = "report.pdf"
        reply = _make_reply(text=None, caption=None, voice=None, document=doc_mock)
        message = _make_message(reply_to=reply)

        result = wrapper._extract_reply_context(message)
        assert result == "<reply_context>[Document: report.pdf]</reply_context>\n"

    def test_document_reply_no_filename(self):
        """Reply to document without file_name → uses 'unknown'."""
        wrapper = _make_wrapper()
        doc_mock = MagicMock()
        doc_mock.file_name = None
        reply = _make_reply(text=None, caption=None, voice=None, document=doc_mock)
        message = _make_message(reply_to=reply)

        result = wrapper._extract_reply_context(message)
        assert result == "<reply_context>[Document: unknown]</reply_context>\n"

    def test_media_no_text(self):
        """Media message without text/caption/voice/doc → [Media message]."""
        wrapper = _make_wrapper()
        reply = _make_reply(text=None, caption=None, voice=None, document=None)
        message = _make_message(reply_to=reply)

        result = wrapper._extract_reply_context(message)
        assert result == "<reply_context>[Media message]</reply_context>\n"

    def test_truncation(self):
        """Original > 200 chars → truncated with '...'."""
        wrapper = _make_wrapper()
        long_text = "a" * 300
        reply = _make_reply(text=long_text)
        message = _make_message(reply_to=reply)

        result = wrapper._extract_reply_context(message)
        inner = result.removeprefix("<reply_context>").removesuffix("</reply_context>\n")
        assert len(inner) == 200
        assert inner.endswith("...")

    def test_no_reply(self):
        """Not a reply → returns empty string."""
        wrapper = _make_wrapper()
        message = _make_message(reply_to=None)

        result = wrapper._extract_reply_context(message)
        assert result == ""

    def test_deleted_message_none(self):
        """reply_to_message is None → returns empty string."""
        wrapper = _make_wrapper()
        message = _make_message(reply_to=None)
        message.reply_to_message = None

        result = wrapper._extract_reply_context(message)
        assert result == ""

    def test_config_disabled(self):
        """enable_reply_context=False → returns empty string."""
        wrapper = _make_wrapper(enable_reply_context=False)
        reply = _make_reply(text="Some text")
        message = _make_message(reply_to=reply)

        result = wrapper._extract_reply_context(message)
        assert result == ""

    def test_cache_hit(self):
        """Cached text used instead of message attributes."""
        wrapper = _make_wrapper()
        chat_id = 1001
        reply_msg_id = 10
        wrapper._message_id_cache[chat_id] = {reply_msg_id: "cached snippet"}

        reply = _make_reply(msg_id=reply_msg_id, text="original text from message")
        message = _make_message(chat_id=chat_id, reply_to=reply)

        result = wrapper._extract_reply_context(message)
        # Should use cached text, not message text
        assert "cached snippet" in result
        assert "original text from message" not in result

    def test_cache_miss_falls_back_to_message_text(self):
        """Cache miss falls back to reply_to_message.text."""
        wrapper = _make_wrapper()
        reply = _make_reply(msg_id=999, text="fallback text")
        message = _make_message(reply_to=reply)

        # Cache is empty — should use message.text
        result = wrapper._extract_reply_context(message)
        assert "fallback text" in result


@pytest.mark.asyncio
class TestHandlerReplyIntegration:
    """Integration tests for reply context prepending in handlers."""

    async def test_handle_message_with_reply(self):
        """Reply context prepended to user text in handle_message."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig

        config = TelegramAgentConfig(
            name="test-bot", chatbot_id="testbot", enable_reply_context=True
        )
        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.config = config
        wrapper.logger = MagicMock()
        wrapper._agent_lock = asyncio.Lock()
        wrapper._user_sessions = {}
        wrapper.conversations = {}
        wrapper._message_id_cache = {}

        # Build reply
        reply = _make_reply(text="Replied-to message")
        message = _make_message(chat_id=5001, msg_id=200, text="Follow up", reply_to=reply)
        message.from_user.id = 100
        message.answer = AsyncMock()

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        invoked_with = {}

        async def mock_invoke(sess, question, *, memory, output_mode, message, **kw):
            invoked_with['question'] = question
            return "response"

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._state_manager = MagicMock()
        wrapper._state_manager.get_suspended_session = AsyncMock(return_value=None)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = mock_invoke
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=None)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_message(message)

        # The question passed to _invoke_agent must contain reply context
        assert "<reply_context>" in invoked_with.get('question', '')
        assert "Replied-to message" in invoked_with.get('question', '')
        assert "Follow up" in invoked_with.get('question', '')

    async def test_handle_message_no_reply_unaffected(self):
        """When no reply, user text is unchanged."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig

        config = TelegramAgentConfig(name="test-bot", chatbot_id="testbot")
        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.config = config
        wrapper.logger = MagicMock()
        wrapper._agent_lock = asyncio.Lock()
        wrapper._user_sessions = {}
        wrapper.conversations = {}
        wrapper._message_id_cache = {}

        message = _make_message(chat_id=5001, msg_id=200, text="plain message", reply_to=None)
        message.from_user.id = 100
        message.answer = AsyncMock()

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        invoked_with = {}

        async def mock_invoke(sess, question, *, memory, output_mode, message, **kw):
            invoked_with['question'] = question
            return "response"

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._state_manager = MagicMock()
        wrapper._state_manager.get_suspended_session = AsyncMock(return_value=None)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = mock_invoke
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=None)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_message(message)

        # No reply context in the question
        assert "<reply_context>" not in invoked_with.get('question', '')
        assert invoked_with.get('question') == "plain message"
