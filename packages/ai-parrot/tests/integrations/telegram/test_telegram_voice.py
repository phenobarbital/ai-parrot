"""Unit tests for TelegramAgentWrapper.handle_voice (TASK-267).

Tests cover:
- ContentType.VOICE downloads and transcribes
- ContentType.AUDIO downloads and transcribes
- show_transcription=True sends italic reply before processing
- show_transcription=False skips the transcription reply
- voice_config=None silently ignores the message
- Empty transcription result sends error message
- Duration exceeded sends error without downloading
- Temp file cleanup on error
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.telegram.models import TelegramAgentConfig
from parrot.voice.transcriber import TranscriptionResult, VoiceTranscriberConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_voice_config(**kwargs) -> VoiceTranscriberConfig:
    """Return a VoiceTranscriberConfig with sensible test defaults."""
    defaults = dict(
        enabled=True,
        max_audio_duration_seconds=60,
        show_transcription=True,
        language=None,
    )
    defaults.update(kwargs)
    return VoiceTranscriberConfig(**defaults)


def _make_config(voice_config=None, allowed_chat_ids=None) -> TelegramAgentConfig:
    return TelegramAgentConfig(
        name="TestVoiceBot",
        chatbot_id="test_voice_bot",
        bot_token="test:token",
        allowed_chat_ids=allowed_chat_ids,
        voice_config=voice_config,
    )


def _make_wrapper(config: TelegramAgentConfig):
    """Create a TelegramAgentWrapper with mocked bot/agent dependencies."""
    mock_agent = MagicMock()
    mock_agent.get_available_tools = MagicMock(return_value=[])
    mock_agent.ask = AsyncMock(return_value="Agent response text")

    mock_bot = MagicMock()
    mock_bot.get_file = AsyncMock()
    mock_bot.download_file = AsyncMock()
    mock_bot.send_chat_action = AsyncMock()

    with patch("parrot.integrations.telegram.wrapper.CallbackRegistry") as mock_cb:
        mock_cb.return_value.discover_from_agent.return_value = 0
        mock_cb.return_value.prefixes = []

        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        wrapper = TelegramAgentWrapper(agent=mock_agent, bot=mock_bot, config=config)

    return wrapper


def _make_voice_message(
    chat_id: int = 12345,
    user_id: int = 67890,
    file_id: str = "voice_file_123",
    duration: int = 5,
) -> MagicMock:
    """Create a mock Telegram message with ContentType.VOICE."""
    message = MagicMock()
    message.chat.id = chat_id
    message.answer = AsyncMock()

    user = MagicMock()
    user.id = user_id
    user.username = "testuser"
    user.first_name = "Test"
    user.last_name = "User"
    message.from_user = user

    voice = MagicMock()
    voice.file_id = file_id
    voice.duration = duration
    message.voice = voice
    message.audio = None

    return message


def _make_audio_message(
    chat_id: int = 12345,
    user_id: int = 67890,
    file_id: str = "audio_file_456",
    duration: int = 10,
    mime_type: str = "audio/mpeg",
) -> MagicMock:
    """Create a mock Telegram message with ContentType.AUDIO."""
    message = MagicMock()
    message.chat.id = chat_id
    message.answer = AsyncMock()

    user = MagicMock()
    user.id = user_id
    user.username = "testuser"
    user.first_name = "Test"
    user.last_name = "User"
    message.from_user = user

    message.voice = None
    audio = MagicMock()
    audio.file_id = file_id
    audio.duration = duration
    audio.mime_type = mime_type
    message.audio = audio

    return message


def _make_file_info(file_path: str = "voice/file.ogg") -> MagicMock:
    """Mock Telegram file info returned by bot.get_file()."""
    file_info = MagicMock()
    file_info.file_path = file_path
    return file_info


def _make_transcription(text: str = "Hello world", language: str = "en") -> TranscriptionResult:
    return TranscriptionResult(
        text=text,
        language=language,
        duration_seconds=3.5,
        processing_time_ms=500,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHandleVoiceDownloadsAndTranscribes:
    """Voice note happy path — downloads file, transcribes, calls agent."""

    @pytest.mark.asyncio
    async def test_handle_voice_downloads_and_transcribes(self):
        config = _make_config(voice_config=_make_voice_config(show_transcription=False))
        wrapper = _make_wrapper(config)

        message = _make_voice_message()
        file_info = _make_file_info("voice/abc.ogg")
        wrapper.bot.get_file.return_value = file_info

        mock_result = _make_transcription("Hello from voice")
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe_file = AsyncMock(return_value=mock_result)
        wrapper._transcriber = mock_transcriber

        with patch("tempfile.NamedTemporaryFile") as mock_ntf:
            tmp_mock = MagicMock()
            tmp_mock.name = "/tmp/tg_voice_test.ogg"
            mock_ntf.return_value = tmp_mock

            with patch("parrot.integrations.telegram.wrapper.Path") as mock_path_cls:
                path_instance = MagicMock()
                path_instance.exists.return_value = False  # skip cleanup
                mock_path_cls.return_value = path_instance
                mock_path_cls.side_effect = lambda x: (
                    MagicMock(suffix=".ogg") if isinstance(x, str) and "voice/abc.ogg" in x
                    else path_instance
                )

                await wrapper.handle_voice(message)

        wrapper.bot.get_file.assert_called_once_with("voice_file_123")
        wrapper.bot.download_file.assert_called_once()
        mock_transcriber.transcribe_file.assert_called_once()
        wrapper.agent.ask.assert_called_once()


class TestHandleVoiceTranscriptionReply:
    """Test show_transcription behavior."""

    @pytest.mark.asyncio
    async def test_handle_voice_sends_transcription_reply(self):
        """When show_transcription=True, an italic reply with transcription is sent."""
        config = _make_config(voice_config=_make_voice_config(show_transcription=True))
        wrapper = _make_wrapper(config)

        message = _make_voice_message()
        wrapper.bot.get_file.return_value = _make_file_info()

        mock_result = _make_transcription("I can hear you")
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe_file = AsyncMock(return_value=mock_result)
        wrapper._transcriber = mock_transcriber

        with patch("tempfile.NamedTemporaryFile") as mock_ntf:
            tmp_mock = MagicMock()
            tmp_mock.name = "/tmp/tg_voice_test.ogg"
            mock_ntf.return_value = tmp_mock

            with patch("parrot.integrations.telegram.wrapper.Path") as mock_path_cls:
                path_instance = MagicMock()
                path_instance.exists.return_value = False
                mock_path_cls.return_value = path_instance
                mock_path_cls.side_effect = lambda x: MagicMock(suffix="") if "/" in str(x) else path_instance

                await wrapper.handle_voice(message)

        # The answer with transcription text should have been sent
        calls = [str(c) for c in message.answer.call_args_list]
        transcription_replies = [c for c in calls if "I can hear you" in c]
        assert len(transcription_replies) >= 1

    @pytest.mark.asyncio
    async def test_handle_voice_skips_transcription_reply(self):
        """When show_transcription=False, no italic reply is sent."""
        config = _make_config(voice_config=_make_voice_config(show_transcription=False))
        wrapper = _make_wrapper(config)

        message = _make_voice_message()
        wrapper.bot.get_file.return_value = _make_file_info()

        mock_result = _make_transcription("Secret text")
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe_file = AsyncMock(return_value=mock_result)
        wrapper._transcriber = mock_transcriber

        with patch("tempfile.NamedTemporaryFile") as mock_ntf:
            tmp_mock = MagicMock()
            tmp_mock.name = "/tmp/tg_voice_test.ogg"
            mock_ntf.return_value = tmp_mock

            with patch("parrot.integrations.telegram.wrapper.Path") as mock_path_cls:
                path_instance = MagicMock()
                path_instance.exists.return_value = False
                mock_path_cls.return_value = path_instance
                mock_path_cls.side_effect = lambda x: MagicMock(suffix="") if "/" in str(x) else path_instance

                await wrapper.handle_voice(message)

        # transcription text should NOT appear in any answer call
        calls = [str(c) for c in message.answer.call_args_list]
        transcription_replies = [c for c in calls if "Secret text" in c]
        assert len(transcription_replies) == 0


class TestHandleVoiceDisabled:
    """Voice handler skips silently when voice is not configured."""

    @pytest.mark.asyncio
    async def test_handle_voice_disabled_ignores_message(self):
        """When voice_config=None, handle_voice returns without downloading."""
        config = _make_config(voice_config=None)
        wrapper = _make_wrapper(config)

        message = _make_voice_message()

        await wrapper.handle_voice(message)

        wrapper.bot.get_file.assert_not_called()
        wrapper.agent.ask.assert_not_called()
        # No answer sent (silent ignore)
        message.answer.assert_not_called()


class TestHandleVoiceEmptyTranscription:
    """Empty transcription result sends an error message."""

    @pytest.mark.asyncio
    async def test_handle_voice_empty_transcription(self):
        config = _make_config(voice_config=_make_voice_config(show_transcription=False))
        wrapper = _make_wrapper(config)

        message = _make_voice_message()
        wrapper.bot.get_file.return_value = _make_file_info()

        empty_result = _make_transcription(text="   ")  # whitespace only
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe_file = AsyncMock(return_value=empty_result)
        wrapper._transcriber = mock_transcriber

        with patch("tempfile.NamedTemporaryFile") as mock_ntf:
            tmp_mock = MagicMock()
            tmp_mock.name = "/tmp/tg_voice_test.ogg"
            mock_ntf.return_value = tmp_mock

            with patch("parrot.integrations.telegram.wrapper.Path") as mock_path_cls:
                path_instance = MagicMock()
                path_instance.exists.return_value = False
                mock_path_cls.return_value = path_instance
                mock_path_cls.side_effect = lambda x: MagicMock(suffix="") if "/" in str(x) else path_instance

                await wrapper.handle_voice(message)

        # Should send the "couldn't understand" error
        calls = [str(c) for c in message.answer.call_args_list]
        error_replies = [c for c in calls if "couldn't understand" in c or "❓" in c]
        assert len(error_replies) >= 1

        # Should NOT call agent
        wrapper.agent.ask.assert_not_called()


class TestHandleVoiceDurationExceeded:
    """Duration limit is enforced before downloading the file."""

    @pytest.mark.asyncio
    async def test_handle_voice_duration_exceeded(self):
        config = _make_config(
            voice_config=_make_voice_config(max_audio_duration_seconds=30)
        )
        wrapper = _make_wrapper(config)

        # Duration 60s > limit 30s
        message = _make_voice_message(duration=60)

        await wrapper.handle_voice(message)

        # Should NOT download
        wrapper.bot.get_file.assert_not_called()
        wrapper.agent.ask.assert_not_called()

        # Should send "too long" error
        calls = [str(c) for c in message.answer.call_args_list]
        duration_errors = [c for c in calls if "too long" in c or "⏱" in c]
        assert len(duration_errors) >= 1


class TestHandleVoiceAudioFile:
    """ContentType.AUDIO messages are handled via message.audio."""

    @pytest.mark.asyncio
    async def test_handle_voice_audio_file(self):
        config = _make_config(voice_config=_make_voice_config(show_transcription=False))
        wrapper = _make_wrapper(config)

        message = _make_audio_message(file_id="audio_mp3_789")
        wrapper.bot.get_file.return_value = _make_file_info("audio/file.mp3")

        mock_result = _make_transcription("Audio file text")
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe_file = AsyncMock(return_value=mock_result)
        wrapper._transcriber = mock_transcriber

        with patch("tempfile.NamedTemporaryFile") as mock_ntf:
            tmp_mock = MagicMock()
            tmp_mock.name = "/tmp/tg_voice_test.mp3"
            mock_ntf.return_value = tmp_mock

            with patch("parrot.integrations.telegram.wrapper.Path") as mock_path_cls:
                path_instance = MagicMock()
                path_instance.exists.return_value = False
                mock_path_cls.return_value = path_instance
                mock_path_cls.side_effect = lambda x: MagicMock(suffix=".mp3") if "mp3" in str(x) else path_instance

                await wrapper.handle_voice(message)

        # Should download the audio file by its file_id
        wrapper.bot.get_file.assert_called_once_with("audio_mp3_789")
        wrapper.bot.download_file.assert_called_once()
        wrapper.agent.ask.assert_called_once()


class TestHandleVoiceCleanupOnError:
    """Temp file is always deleted even when an error occurs."""

    @pytest.mark.asyncio
    async def test_handle_voice_cleanup_on_error(self):
        config = _make_config(voice_config=_make_voice_config(show_transcription=False))
        wrapper = _make_wrapper(config)

        tmp_file_path = "/tmp/tg_voice_test.ogg"

        message = _make_voice_message()
        wrapper.bot.get_file.return_value = _make_file_info("voice/file.ogg")

        # Transcriber raises an exception
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe_file = AsyncMock(
            side_effect=RuntimeError("Whisper backend unavailable")
        )
        wrapper._transcriber = mock_transcriber

        unlink_called = []

        # path_instance is the mock for Path(tmp.name) — the temp file
        path_instance = MagicMock()
        path_instance.exists.return_value = True  # file exists → should be deleted
        path_instance.unlink.side_effect = lambda: unlink_called.append(True)

        def path_side_effect(x):
            """Return path_instance for the temp file, a suffix-only mock otherwise."""
            if str(x) == tmp_file_path:
                return path_instance
            # For Telegram CDN path — only suffix matters
            ext = "." + str(x).rsplit(".", 1)[-1] if "." in str(x) else ""
            m = MagicMock()
            m.suffix = ext
            return m

        with patch("tempfile.NamedTemporaryFile") as mock_ntf:
            tmp_mock = MagicMock()
            tmp_mock.name = tmp_file_path
            mock_ntf.return_value = tmp_mock

            with patch("parrot.integrations.telegram.wrapper.Path", side_effect=path_side_effect):
                # Error should not propagate to caller
                await wrapper.handle_voice(message)

        # unlink must have been called on the temp file
        assert len(unlink_called) >= 1

        # Error message should be sent to user
        calls = [str(c) for c in message.answer.call_args_list]
        error_msgs = [c for c in calls if "❌" in c or "couldn't process" in c]
        assert len(error_msgs) >= 1
