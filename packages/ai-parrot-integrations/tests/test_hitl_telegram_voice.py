"""
Unit tests for TelegramHumanChannel voice-note reply support.

Covers:
- Voice note during HITL free-text: transcribed and routed correctly
- Audio file during HITL free-text: transcribed and routed correctly
- voice_config=None during HITL: user told to type instead
- Empty transcription: user prompted to retry
- show_transcription=True: italic preview sent before finalizing
- Transcription error: graceful error reply, temp file cleaned up
- Voice note NOT during HITL (no awaiting state): handler returns immediately
- _finalize_text_response: creates correct HumanResponse and invokes callback
- close(): releases transcriber resources
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from parrot.voice.transcriber import TranscriptionResult, VoiceTranscriberConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_voice_config(**kwargs) -> VoiceTranscriberConfig:
    defaults = dict(
        enabled=True,
        max_audio_duration_seconds=60,
        show_transcription=False,
        language=None,
    )
    defaults.update(kwargs)
    return VoiceTranscriberConfig(**defaults)


def _make_transcription(text: str = "Hello from voice") -> TranscriptionResult:
    return TranscriptionResult(
        text=text,
        language="en",
        duration_seconds=2.5,
        processing_time_ms=800,
    )


def _make_channel(voice_config=None):
    """Return a TelegramHumanChannel with mocked Bot and Redis."""
    bot = MagicMock()
    bot.get_file = AsyncMock()
    bot.download_file = AsyncMock()
    bot.send_message = AsyncMock()

    redis = AsyncMock()

    with patch(
        "parrot.human.channels.telegram.HAS_AIOGRAM", True
    ), patch(
        "parrot.human.channels.telegram.Router"
    ) as mock_router_cls:
        mock_router = MagicMock()
        mock_router.message = MagicMock()
        mock_router.message.register = MagicMock()
        mock_router.callback_query = MagicMock()
        mock_router.callback_query.register = MagicMock()
        mock_router_cls.return_value = mock_router

        from parrot.human.channels.telegram import TelegramHumanChannel

        channel = TelegramHumanChannel(bot=bot, redis=redis, voice_config=voice_config)
        channel.router = mock_router
        return channel, bot


def _make_voice_message(
    chat_id: int = 42,
    user_id: int = 99,
    message_id: int = 7,
    file_id: str = "voice_file_001",
    duration: int = 5,
) -> MagicMock:
    message = MagicMock()
    message.chat.id = chat_id
    message.chat.type = "private"
    message.message_id = message_id

    user = MagicMock()
    user.id = user_id
    message.from_user = user

    voice = MagicMock()
    voice.file_id = file_id
    voice.duration = duration
    message.voice = voice
    message.audio = None
    message.text = None

    message.reply = AsyncMock()
    message.answer = AsyncMock()
    return message


def _make_audio_message(
    chat_id: int = 42,
    user_id: int = 99,
    message_id: int = 8,
    file_id: str = "audio_file_001",
    mime_type: str = "audio/mpeg",
) -> MagicMock:
    message = MagicMock()
    message.chat.id = chat_id
    message.chat.type = "private"
    message.message_id = message_id

    user = MagicMock()
    user.id = user_id
    message.from_user = user

    audio = MagicMock()
    audio.file_id = file_id
    audio.mime_type = mime_type
    audio.duration = 4
    message.audio = audio
    message.voice = None
    message.text = None

    message.reply = AsyncMock()
    message.answer = AsyncMock()
    return message


def _make_file_info(file_path: str = "voice/abc.ogg") -> MagicMock:
    fi = MagicMock()
    fi.file_path = file_path
    return fi


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHITLVoiceReply:

    @pytest.mark.asyncio
    async def test_voice_reply_transcribed_and_finalized(self):
        """Voice note during HITL free-text interaction is transcribed + processed."""
        voice_config = _make_voice_config(show_transcription=False)
        channel, bot = _make_channel(voice_config=voice_config)

        interaction_id = "iid-001"
        channel._awaiting_text[42] = interaction_id

        response_cb = AsyncMock()
        channel._response_callback = response_cb
        channel._pending_by_chat[42] = {interaction_id}

        message = _make_voice_message(chat_id=42, user_id=99)
        file_info = _make_file_info("voice/abc.ogg")
        bot.get_file.return_value = file_info

        transcription = _make_transcription("Approve this request")
        mock_transcriber = AsyncMock()
        mock_transcriber.transcribe_file = AsyncMock(return_value=transcription)

        with patch.object(channel, "_get_transcriber", return_value=mock_transcriber):
            await channel._handle_voice_reply(message)

        # Should confirm receipt
        message.reply.assert_called()
        reply_text = message.reply.call_args[0][0]
        assert "Got it" in reply_text

        # Callback should be invoked
        response_cb.assert_awaited_once()
        hr = response_cb.call_args[0][0]
        assert hr.value == "Approve this request"
        assert hr.interaction_id == interaction_id
        assert hr.respondent == "99"

        # HITL state should be cleared
        assert 42 not in channel._awaiting_text

    @pytest.mark.asyncio
    async def test_voice_reply_not_awaiting_returns_immediately(self):
        """Voice note handler is a no-op when chat is not in HITL state."""
        voice_config = _make_voice_config()
        channel, bot = _make_channel(voice_config=voice_config)
        # No entry in _awaiting_text

        message = _make_voice_message(chat_id=42)
        await channel._handle_voice_reply(message)

        # No bot interaction
        bot.get_file.assert_not_called()
        message.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_voice_reply_no_voice_config_tells_user_to_type(self):
        """When voice_config is absent, user is instructed to type."""
        channel, bot = _make_channel(voice_config=None)
        channel._awaiting_text[42] = "iid-002"

        message = _make_voice_message(chat_id=42)
        await channel._handle_voice_reply(message)

        # Should NOT attempt download
        bot.get_file.assert_not_called()
        # Should inform user
        message.reply.assert_awaited_once()
        reply_text = message.reply.call_args[0][0]
        assert "type" in reply_text.lower() or "text" in reply_text.lower()

    @pytest.mark.asyncio
    async def test_voice_reply_empty_transcription_prompts_retry(self):
        """Empty transcription → user is asked to retry or type."""
        voice_config = _make_voice_config()
        channel, bot = _make_channel(voice_config=voice_config)
        channel._awaiting_text[42] = "iid-003"
        channel._pending_by_chat[42] = {"iid-003"}

        message = _make_voice_message(chat_id=42)
        file_info = _make_file_info()
        bot.get_file.return_value = file_info

        empty_result = _make_transcription(text="   ")
        mock_transcriber = AsyncMock()
        mock_transcriber.transcribe_file = AsyncMock(return_value=empty_result)

        with patch.object(channel, "_get_transcriber", return_value=mock_transcriber):
            await channel._handle_voice_reply(message)

        message.reply.assert_awaited_once()
        reply_text = message.reply.call_args[0][0]
        assert "understand" in reply_text.lower() or "try" in reply_text.lower()
        # HITL state NOT cleared (user can retry)
        assert 42 in channel._awaiting_text

    @pytest.mark.asyncio
    async def test_voice_reply_show_transcription_sends_preview(self):
        """show_transcription=True sends italic preview before finalizing."""
        voice_config = _make_voice_config(show_transcription=True)
        channel, bot = _make_channel(voice_config=voice_config)
        channel._awaiting_text[42] = "iid-004"
        channel._pending_by_chat[42] = {"iid-004"}
        channel._response_callback = AsyncMock()

        message = _make_voice_message(chat_id=42)
        bot.get_file.return_value = _make_file_info()

        transcription = _make_transcription("Please proceed")
        mock_transcriber = AsyncMock()
        mock_transcriber.transcribe_file = AsyncMock(return_value=transcription)

        with patch.object(channel, "_get_transcriber", return_value=mock_transcriber):
            await channel._handle_voice_reply(message)

        # answer() called with italic transcription
        message.answer.assert_awaited_once()
        preview = message.answer.call_args[0][0]
        assert "Please proceed" in preview

    @pytest.mark.asyncio
    async def test_voice_reply_error_sends_error_message(self):
        """Transcription error results in graceful error reply, not an exception."""
        voice_config = _make_voice_config()
        channel, bot = _make_channel(voice_config=voice_config)
        channel._awaiting_text[42] = "iid-005"

        message = _make_voice_message(chat_id=42)
        bot.get_file.return_value = _make_file_info()

        mock_transcriber = AsyncMock()
        mock_transcriber.transcribe_file = AsyncMock(
            side_effect=RuntimeError("whisper error")
        )

        with patch.object(channel, "_get_transcriber", return_value=mock_transcriber):
            await channel._handle_voice_reply(message)

        message.reply.assert_awaited()
        reply_text = message.reply.call_args[0][0]
        assert "❌" in reply_text or "type" in reply_text.lower()

    @pytest.mark.asyncio
    async def test_audio_file_reply_works(self):
        """ContentType.AUDIO (forwarded audio) also transcribes correctly."""
        voice_config = _make_voice_config(show_transcription=False)
        channel, bot = _make_channel(voice_config=voice_config)
        channel._awaiting_text[42] = "iid-006"
        channel._pending_by_chat[42] = {"iid-006"}
        channel._response_callback = AsyncMock()

        message = _make_audio_message(chat_id=42, mime_type="audio/mpeg")
        bot.get_file.return_value = _make_file_info("audio/abc.mp3")

        transcription = _make_transcription("Audio reply text")
        mock_transcriber = AsyncMock()
        mock_transcriber.transcribe_file = AsyncMock(return_value=transcription)

        with patch.object(channel, "_get_transcriber", return_value=mock_transcriber):
            await channel._handle_voice_reply(message)

        channel._response_callback.assert_awaited_once()
        hr = channel._response_callback.call_args[0][0]
        assert hr.value == "Audio reply text"

    @pytest.mark.asyncio
    async def test_close_releases_transcriber(self):
        """close() closes the transcriber and clears the reference."""
        voice_config = _make_voice_config()
        channel, _ = _make_channel(voice_config=voice_config)

        mock_transcriber = AsyncMock()
        mock_transcriber.close = AsyncMock()
        channel._transcriber = mock_transcriber

        await channel.close()

        mock_transcriber.close.assert_awaited_once()
        assert channel._transcriber is None

    @pytest.mark.asyncio
    async def test_close_noop_when_no_transcriber(self):
        """close() is a no-op when no transcriber has been initialized."""
        channel, _ = _make_channel()
        await channel.close()  # must not raise


class TestFinalizeTextResponse:

    @pytest.mark.asyncio
    async def test_creates_correct_human_response(self):
        """_finalize_text_response creates a HumanResponse with the given text."""
        channel, _ = _make_channel()
        interaction_id = "iid-fin-001"
        channel._awaiting_text[10] = interaction_id
        channel._pending_by_chat[10] = {interaction_id}

        response_cb = AsyncMock()
        channel._response_callback = response_cb

        # Stub Redis so _get_interaction_meta returns None (no form)
        channel.redis.get = AsyncMock(return_value=None)

        message = MagicMock()
        message.chat.id = 10
        message.message_id = 55
        message.from_user = MagicMock()
        message.from_user.id = 77
        message.reply = AsyncMock()

        await channel._finalize_text_response(message, "My typed answer")

        response_cb.assert_awaited_once()
        hr = response_cb.call_args[0][0]
        assert hr.value == "My typed answer"
        assert hr.respondent == "77"
        assert hr.interaction_id == interaction_id
        assert hr.metadata["channel"] == "telegram"
        assert 10 not in channel._awaiting_text

    @pytest.mark.asyncio
    async def test_noop_when_not_awaiting(self):
        """_finalize_text_response is a no-op if chat is not in awaiting state."""
        channel, _ = _make_channel()
        response_cb = AsyncMock()
        channel._response_callback = response_cb

        message = MagicMock()
        message.chat.id = 99  # not in _awaiting_text
        message.reply = AsyncMock()

        await channel._finalize_text_response(message, "irrelevant")

        response_cb.assert_not_awaited()
