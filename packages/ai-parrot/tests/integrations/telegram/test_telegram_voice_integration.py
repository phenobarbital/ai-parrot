"""Integration tests for TelegramAgentWrapper voice message handling (TASK-267).

Tests the full flow:
- voice note → download → transcription → agent response
- audio file → download → transcription → agent response
- voice message with no voice_config → silently ignored
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.telegram.models import TelegramAgentConfig
from parrot.voice.transcriber import TranscriptionResult, VoiceTranscriberConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_voice_config(**kwargs) -> VoiceTranscriberConfig:
    defaults = dict(
        enabled=True,
        max_audio_duration_seconds=60,
        show_transcription=True,
        language=None,
    )
    defaults.update(kwargs)
    return VoiceTranscriberConfig(**defaults)


def _make_wrapper(config: TelegramAgentConfig):
    mock_agent = MagicMock()
    mock_agent.get_available_tools = MagicMock(return_value=[])
    mock_agent.ask = AsyncMock(return_value="Here is my response to your voice message.")

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
    chat_id: int = 111,
    user_id: int = 222,
    file_id: str = "voice_integration_test",
    duration: int = 8,
) -> MagicMock:
    message = MagicMock()
    message.chat.id = chat_id
    message.answer = AsyncMock()

    user = MagicMock()
    user.id = user_id
    user.username = "integration_user"
    user.first_name = "Integration"
    user.last_name = "Tester"
    message.from_user = user

    voice = MagicMock()
    voice.file_id = file_id
    voice.duration = duration
    message.voice = voice
    message.audio = None

    return message


def _make_audio_message(
    chat_id: int = 111,
    user_id: int = 222,
    file_id: str = "audio_integration_test",
    duration: int = 12,
    mime_type: str = "audio/mpeg",
) -> MagicMock:
    message = MagicMock()
    message.chat.id = chat_id
    message.answer = AsyncMock()

    user = MagicMock()
    user.id = user_id
    user.username = "integration_user"
    user.first_name = "Integration"
    user.last_name = "Tester"
    message.from_user = user

    message.voice = None
    audio = MagicMock()
    audio.file_id = file_id
    audio.duration = duration
    audio.mime_type = mime_type
    message.audio = audio

    return message


def _make_file_info(file_path: str = "voice/integration.ogg") -> MagicMock:
    info = MagicMock()
    info.file_path = file_path
    return info


def _make_transcription(text: str, language: str = "en") -> TranscriptionResult:
    return TranscriptionResult(
        text=text,
        language=language,
        duration_seconds=5.0,
        processing_time_ms=600,
    )


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestVoiceMessageFullFlow:
    """Full flow: voice note → transcription → agent response."""

    @pytest.mark.asyncio
    async def test_voice_message_full_flow(self):
        """Voice note message triggers download, transcription, and agent response."""
        config = TelegramAgentConfig(
            name="IntegrationVoiceBot",
            chatbot_id="integration_voice_bot",
            bot_token="integration:token",
            voice_config=_make_voice_config(show_transcription=True),
        )
        wrapper = _make_wrapper(config)

        message = _make_voice_message()
        wrapper.bot.get_file.return_value = _make_file_info("voice/integration.ogg")

        transcription_text = "Tell me about the project status"
        mock_result = _make_transcription(transcription_text)
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe_file = AsyncMock(return_value=mock_result)
        wrapper._transcriber = mock_transcriber

        with patch("tempfile.NamedTemporaryFile") as mock_ntf:
            tmp_mock = MagicMock()
            tmp_mock.name = "/tmp/tg_voice_integration.ogg"
            mock_ntf.return_value = tmp_mock

            with patch("parrot.integrations.telegram.wrapper.Path") as mock_path_cls:
                path_instance = MagicMock()
                path_instance.exists.return_value = False
                mock_path_cls.return_value = path_instance
                mock_path_cls.side_effect = (
                    lambda x: MagicMock(suffix=".ogg") if "integration.ogg" in str(x) else path_instance
                )

                await wrapper.handle_voice(message)

        # 1. File was fetched from Telegram CDN
        wrapper.bot.get_file.assert_called_once()

        # 2. File was downloaded
        wrapper.bot.download_file.assert_called_once()

        # 3. Transcription was performed
        mock_transcriber.transcribe_file.assert_called_once()

        # 4. Transcription text was shown to user (show_transcription=True)
        all_answers = [str(c) for c in message.answer.call_args_list]
        transcription_shown = [c for c in all_answers if transcription_text in c]
        assert len(transcription_shown) >= 1

        # 5. Agent was asked with the transcribed text
        wrapper.agent.ask.assert_called_once()
        ask_call_args = wrapper.agent.ask.call_args
        asked_text = ask_call_args.args[0] if ask_call_args.args else ask_call_args.kwargs.get("question", "")
        assert transcription_text in asked_text

        # 6. Agent response was sent to user
        agent_response_shown = [c for c in all_answers if "response" in c.lower()]
        assert len(agent_response_shown) >= 1


class TestAudioMessageFullFlow:
    """Full flow: audio file → transcription → agent response."""

    @pytest.mark.asyncio
    async def test_audio_message_full_flow(self):
        """Audio file message triggers download, transcription, and agent response."""
        config = TelegramAgentConfig(
            name="IntegrationAudioBot",
            chatbot_id="integration_audio_bot",
            bot_token="integration:token",
            voice_config=_make_voice_config(show_transcription=False),
        )
        wrapper = _make_wrapper(config)

        message = _make_audio_message(file_id="mp3_audio_file_999", mime_type="audio/mpeg")
        wrapper.bot.get_file.return_value = _make_file_info("audio/integration.mp3")

        transcription_text = "Monthly report summary goes here"
        mock_result = _make_transcription(transcription_text)
        mock_transcriber = MagicMock()
        mock_transcriber.transcribe_file = AsyncMock(return_value=mock_result)
        wrapper._transcriber = mock_transcriber

        with patch("tempfile.NamedTemporaryFile") as mock_ntf:
            tmp_mock = MagicMock()
            tmp_mock.name = "/tmp/tg_audio_integration.mp3"
            mock_ntf.return_value = tmp_mock

            with patch("parrot.integrations.telegram.wrapper.Path") as mock_path_cls:
                path_instance = MagicMock()
                path_instance.exists.return_value = False
                mock_path_cls.return_value = path_instance
                mock_path_cls.side_effect = (
                    lambda x: MagicMock(suffix=".mp3") if "mp3" in str(x) else path_instance
                )

                await wrapper.handle_voice(message)

        # Audio file fetched by its file_id
        wrapper.bot.get_file.assert_called_once_with("mp3_audio_file_999")
        wrapper.bot.download_file.assert_called_once()
        mock_transcriber.transcribe_file.assert_called_once()

        # show_transcription=False → transcription text NOT shown
        all_answers = [str(c) for c in message.answer.call_args_list]
        transcription_shown = [c for c in all_answers if transcription_text in c]
        assert len(transcription_shown) == 0

        # Agent was still called with the transcribed text
        wrapper.agent.ask.assert_called_once()
        ask_call_args = wrapper.agent.ask.call_args
        asked_text = ask_call_args.args[0] if ask_call_args.args else ask_call_args.kwargs.get("question", "")
        assert transcription_text in asked_text


class TestVoiceWithNoConfigIgnored:
    """When voice_config is None, voice messages are silently ignored."""

    @pytest.mark.asyncio
    async def test_voice_with_no_config_ignored(self):
        """Voice message with no voice_config silently returns without processing."""
        config = TelegramAgentConfig(
            name="NoVoiceBot",
            chatbot_id="no_voice_bot",
            bot_token="no:voice:token",
            voice_config=None,  # Voice NOT configured
        )
        wrapper = _make_wrapper(config)

        # Both VOICE and AUDIO types tested
        voice_message = _make_voice_message()
        audio_message = _make_audio_message()

        await wrapper.handle_voice(voice_message)
        await wrapper.handle_voice(audio_message)

        # No network activity
        wrapper.bot.get_file.assert_not_called()
        wrapper.bot.download_file.assert_not_called()

        # No agent activity
        wrapper.agent.ask.assert_not_called()

        # No user-facing messages (completely silent)
        voice_message.answer.assert_not_called()
        audio_message.answer.assert_not_called()
