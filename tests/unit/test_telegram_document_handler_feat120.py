"""Unit tests for FEAT-120 complete document handler.

Tests verify:
- Document download, size validation, auth checks
- Reply context integration, caption enrichment
- _invoke_agent called with attachments
- Message IDs cached and metadata stored
- Error handling
"""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _make_wrapper(max_document_size_mb: int = 20):
    """Create a minimal TelegramAgentWrapper for document handler tests."""
    from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
    from parrot.integrations.telegram.models import TelegramAgentConfig

    config = TelegramAgentConfig(
        name="test-bot",
        chatbot_id="testbot",
        max_document_size_mb=max_document_size_mb,
        enable_reply_context=True,
    )
    agent = MagicMock()
    agent.ask = AsyncMock(return_value="response")
    bot = MagicMock()

    file_obj = MagicMock()
    file_obj.file_path = "documents/test.pdf"
    bot.get_file = AsyncMock(return_value=file_obj)
    bot.download_file = AsyncMock()

    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.config = config
    wrapper.agent = agent
    wrapper.bot = bot
    wrapper.logger = MagicMock()
    wrapper._agent_lock = asyncio.Lock()
    wrapper._user_sessions = {}
    wrapper.conversations = {}
    wrapper._message_id_cache = {}
    return wrapper


def _make_document_message(
    chat_id: int = 12345,
    msg_id: int = 100,
    file_name: str = "report.pdf",
    file_size: int = 1024 * 100,  # 100 KB
    caption: str = None,
    reply_to=None,
):
    """Create a mock document Message."""
    message = MagicMock()
    message.chat.id = chat_id
    message.message_id = msg_id
    message.caption = caption
    message.reply_to_message = reply_to
    message.answer = AsyncMock()
    message.from_user.id = 999

    doc = MagicMock()
    doc.file_id = "doc_file_id_abc"
    doc.file_name = file_name
    doc.file_size = file_size
    doc.mime_type = "application/pdf"
    message.document = doc
    return message


@pytest.mark.asyncio
class TestHandleDocument:
    """Tests for the full handle_document implementation."""

    async def test_downloads_document(self):
        """Document downloaded to temp file and path passed to agent."""
        wrapper = _make_wrapper()
        message = _make_document_message(file_name="report.pdf")

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        sent_msg = MagicMock()
        sent_msg.message_id = 999

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = AsyncMock(return_value="response")
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=sent_msg)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_document(message)

        wrapper._invoke_agent.assert_awaited_once()
        call_kwargs = wrapper._invoke_agent.call_args.kwargs
        attachments = call_kwargs.get("attachments", [])
        assert len(attachments) == 1
        assert attachments[0].endswith(".pdf")

    async def test_size_limit_rejection(self):
        """Document exceeding max size → user-friendly rejection message."""
        wrapper = _make_wrapper(max_document_size_mb=1)
        # 2 MB > 1 MB limit
        message = _make_document_message(
            file_name="big.pdf", file_size=2 * 1024 * 1024
        )

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._invoke_agent = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_document(message)

        # Agent should NOT be called
        wrapper._invoke_agent.assert_not_awaited()
        # User gets rejection message
        message.answer.assert_awaited_once()
        answer_text = message.answer.call_args[0][0]
        assert "too large" in answer_text.lower() or "maximum" in answer_text.lower()

    async def test_size_none_attempts_download(self):
        """Document with file_size=None → download attempted anyway."""
        wrapper = _make_wrapper(max_document_size_mb=1)
        message = _make_document_message(file_name="unknown.bin", file_size=None)

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        sent_msg = MagicMock()
        sent_msg.message_id = 555

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = AsyncMock(return_value="response")
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=sent_msg)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        # Should not raise — download is attempted
        await wrapper.handle_document(message)
        wrapper._invoke_agent.assert_awaited_once()

    async def test_no_filename_uses_bin(self):
        """Document without file_name → .bin extension used."""
        wrapper = _make_wrapper()
        message = _make_document_message(file_name=None)
        message.document.file_name = None

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        sent_msg = MagicMock()
        sent_msg.message_id = 444

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = AsyncMock(return_value="response")
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=sent_msg)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_document(message)

        call_kwargs = wrapper._invoke_agent.call_args.kwargs
        attachments = call_kwargs.get("attachments", [])
        assert len(attachments) == 1
        assert attachments[0].endswith(".bin")

    async def test_preserves_file_extension(self):
        """Document with file_name='report.pdf' → .pdf extension preserved."""
        wrapper = _make_wrapper()
        message = _make_document_message(file_name="report.pdf")

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        sent_msg = MagicMock()
        sent_msg.message_id = 333

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = AsyncMock(return_value="response")
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=sent_msg)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_document(message)

        call_kwargs = wrapper._invoke_agent.call_args.kwargs
        attachments = call_kwargs.get("attachments", [])
        assert attachments[0].endswith(".pdf")

    async def test_auth_required(self):
        """Unauthorized user → rejection message, no download."""
        wrapper = _make_wrapper()
        message = _make_document_message()

        wrapper._is_authorized = MagicMock(return_value=False)
        wrapper._invoke_agent = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_document(message)

        wrapper._invoke_agent.assert_not_awaited()
        message.answer.assert_awaited_once()
        assert "not authorized" in message.answer.call_args[0][0].lower()

    async def test_reply_context_included(self):
        """Reply to bot message → reply context prepended to caption."""
        wrapper = _make_wrapper()

        reply = MagicMock()
        reply.message_id = 5
        reply.text = "Previous bot response"
        reply.caption = None
        reply.voice = None
        reply.document = None

        message = _make_document_message(
            file_name="file.txt",
            caption="Please analyze this",
            reply_to=reply,
        )

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        sent_msg = MagicMock()
        sent_msg.message_id = 222

        invoked_with = {}

        async def mock_invoke(sess, question, *, memory, output_mode, message, **kw):
            invoked_with['question'] = question
            return "response"

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = mock_invoke
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=sent_msg)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_document(message)

        assert "<reply_context>" in invoked_with.get('question', '')
        assert "Previous bot response" in invoked_with.get('question', '')

    async def test_enriched_caption_format(self):
        """Caption includes [Attached document saved at: path]."""
        wrapper = _make_wrapper()
        message = _make_document_message(file_name="data.csv", caption="Analyze this CSV")

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        sent_msg = MagicMock()
        sent_msg.message_id = 111

        invoked_with = {}

        async def mock_invoke(sess, question, *, memory, output_mode, message, **kw):
            invoked_with['question'] = question
            return "response"

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = mock_invoke
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=sent_msg)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_document(message)

        question = invoked_with.get('question', '')
        assert "Analyze this CSV" in question
        assert "[Attached document saved at:" in question

    async def test_invoke_agent_called_with_attachments(self):
        """_invoke_agent receives attachments=[path]."""
        wrapper = _make_wrapper()
        message = _make_document_message(file_name="report.docx")

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        sent_msg = MagicMock()
        sent_msg.message_id = 77

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = AsyncMock(return_value="response")
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=sent_msg)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_document(message)

        wrapper._invoke_agent.assert_awaited_once()
        call_kwargs = wrapper._invoke_agent.call_args.kwargs
        attachments = call_kwargs.get("attachments")
        assert attachments is not None
        assert len(attachments) == 1

    async def test_message_ids_cached(self):
        """User and bot message IDs cached after response."""
        wrapper = _make_wrapper()
        message = _make_document_message(chat_id=9999, msg_id=10, file_name="file.pdf")

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        sent_msg = MagicMock()
        sent_msg.message_id = 20

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = AsyncMock(return_value="response")
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=sent_msg)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_document(message)

        assert 10 in wrapper._message_id_cache.get(9999, {})
        assert 20 in wrapper._message_id_cache.get(9999, {})

    async def test_error_handling(self):
        """Download error → user-friendly message, no crash."""
        wrapper = _make_wrapper()
        message = _make_document_message()

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper.bot.get_file = AsyncMock(side_effect=RuntimeError("Telegram API error"))
        wrapper._typing_indicator = AsyncMock()

        # Must not raise
        await wrapper.handle_document(message)

        message.answer.assert_awaited()
        answer_text = message.answer.call_args[0][0]
        assert "couldn't process" in answer_text.lower()

    async def test_typing_indicator_shown(self):
        """Typing indicator is started via asyncio.create_task during processing.

        We verify _typing_indicator is called (to create its coroutine for create_task)
        by using AsyncMock and checking .called (not .awaited_once).
        """
        wrapper = _make_wrapper()
        message = _make_document_message(chat_id=12345)

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        sent_msg = MagicMock()
        sent_msg.message_id = 66

        # Use AsyncMock so it returns a coroutine when called.
        # asyncio.create_task(self._typing_indicator(chat_id)) calls the mock
        # (which records the call) and passes the resulting coroutine to create_task.
        typing_mock = AsyncMock()

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = AsyncMock(return_value="response")
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=sent_msg)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = typing_mock

        await wrapper.handle_document(message)

        # _typing_indicator was CALLED (to produce a coroutine for create_task)
        typing_mock.assert_called_once_with(12345)
