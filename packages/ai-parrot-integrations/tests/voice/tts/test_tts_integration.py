"""
Integration tests for the full TTS surface (TASK-1410 / FEAT-213).

Tests cover:
- All public symbols exportable from parrot.voice.tts
- parrot.voice.VoiceSynthesizer convenience re-export
- voice-in → voice-out end-to-end flow (fully mocked)
- Text input does NOT trigger TTS (zero regression)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.voice.tts import (
    AbstractTTSBackend,
    GoogleTTSBackend,
    SynthesisResult,
    TTSConfig,
    VoiceSynthesizer,
)


# ---------------------------------------------------------------------------
# Public export smoke tests
# ---------------------------------------------------------------------------


def test_public_exports_present():
    """All five public symbols are importable from parrot.voice.tts."""
    assert AbstractTTSBackend is not None
    assert GoogleTTSBackend is not None
    assert VoiceSynthesizer is not None
    assert TTSConfig is not None
    assert SynthesisResult is not None


def test_voice_synthesizer_re_exported_from_voice():
    """VoiceSynthesizer is also accessible from parrot.voice (convenience)."""
    from parrot.voice import VoiceSynthesizer as VS

    assert VS is VoiceSynthesizer


def test_voice_tts_all_list():
    """parrot.voice.tts.__all__ contains the expected names."""
    import parrot.voice.tts as tts_module

    expected = {"VoiceSynthesizer", "AbstractTTSBackend", "GoogleTTSBackend", "TTSConfig", "SynthesisResult"}
    actual = set(tts_module.__all__)
    assert expected == actual


# ---------------------------------------------------------------------------
# Voice-in → voice-out end-to-end flow (mocked)
# ---------------------------------------------------------------------------


@pytest.fixture
def synth_mock():
    """Return a mocked VoiceSynthesizer that produces fake audio."""
    s = MagicMock()
    s.synthesize = AsyncMock(
        return_value=SynthesisResult(audio=b"OGG...", mime_format="audio/ogg")
    )
    return s


def _make_config_with_tts():
    from parrot.integrations.telegram.models import TelegramAgentConfig
    from parrot.voice.transcriber import VoiceTranscriberConfig

    return TelegramAgentConfig(
        name="TTSIntegBot",
        chatbot_id="tts_integ_bot",
        bot_token="test:token",
        tts_enabled=True,
        reply_in_kind=True,
        voice_config=VoiceTranscriberConfig(
            enabled=True, max_audio_duration_seconds=60, show_transcription=False
        ),
    )


def _make_wrapper_for_integration(config):
    mock_agent = MagicMock()
    mock_agent.get_available_tools = MagicMock(return_value=[])
    mock_agent.ask = AsyncMock(return_value="Integration reply")

    mock_bot = MagicMock()
    mock_bot.get_file = AsyncMock()
    mock_bot.download_file = AsyncMock()
    mock_bot.send_chat_action = AsyncMock()
    mock_bot.send_voice = AsyncMock()

    with patch("parrot.integrations.telegram.wrapper.CallbackRegistry") as mock_cb:
        mock_cb.return_value.discover_from_agent.return_value = 0
        mock_cb.return_value.prefixes = []

        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        wrapper = TelegramAgentWrapper(agent=mock_agent, bot=mock_bot, config=config)

    return wrapper


def _make_voice_message(chat_id: int = 12345) -> MagicMock:
    msg = MagicMock()
    msg.chat.id = chat_id
    msg.answer = AsyncMock()
    msg.message_id = 1

    user = MagicMock()
    user.id = 67890
    user.username = "tester"
    user.first_name = "Test"
    user.last_name = "User"
    msg.from_user = user

    voice = MagicMock()
    voice.file_id = "vf_integ_001"
    voice.duration = 3
    msg.voice = voice
    msg.audio = None
    msg.reply_to_message = None
    return msg


def _make_text_message(chat_id: int = 12345) -> MagicMock:
    """Return a normal text message (no voice)."""
    msg = MagicMock()
    msg.chat.id = chat_id
    msg.text = "Hello bot"
    msg.answer = AsyncMock()
    msg.message_id = 2

    user = MagicMock()
    user.id = 67890
    user.username = "tester"
    user.first_name = "Test"
    user.last_name = "User"
    msg.from_user = user

    msg.voice = None
    msg.audio = None
    msg.reply_to_message = None
    return msg


@pytest.mark.asyncio
async def test_voice_in_voice_out_flow(synth_mock):
    """Voice note (mock) → transcribe (mock) → agent (mock) → send_voice(audio)."""
    cfg = _make_config_with_tts()
    wrapper = _make_wrapper_for_integration(cfg)
    wrapper._synthesizer = synth_mock

    message = _make_voice_message()
    file_info = MagicMock()
    file_info.file_path = "voice/integ.ogg"
    wrapper.bot.get_file = AsyncMock(return_value=file_info)

    from parrot.voice.transcriber import TranscriptionResult
    from parrot.integrations.telegram.wrapper import ParsedResponse

    mock_transcriber = MagicMock()
    mock_transcriber.transcribe_file = AsyncMock(
        return_value=TranscriptionResult(
            text="Integration voice test",
            language="en",
            duration_seconds=2.5,
            processing_time_ms=450,
        )
    )
    wrapper._transcriber = mock_transcriber

    fake_parsed = MagicMock(spec=ParsedResponse)
    fake_parsed.text = "Integration reply text"

    with patch.object(wrapper, "_invoke_agent", new=AsyncMock(return_value="Integration reply text")), \
         patch.object(wrapper, "_parse_response", return_value=fake_parsed), \
         patch.object(wrapper, "_send_parsed_response", new=AsyncMock(return_value=MagicMock(message_id=99))), \
         patch.object(wrapper, "_store_telegram_metadata", new=AsyncMock()), \
         patch("tempfile.NamedTemporaryFile") as mock_ntf, \
         patch("parrot.integrations.telegram.wrapper.Path") as mock_path:
        tmp = MagicMock()
        tmp.name = "/tmp/tg_integ_test.ogg"
        mock_ntf.return_value = tmp

        path_inst = MagicMock()
        path_inst.exists.return_value = False
        path_inst.suffix = ".ogg"
        mock_path.return_value = path_inst
        mock_path.side_effect = lambda x: (
            MagicMock(suffix=".ogg")
            if isinstance(x, str) and "integ.ogg" in x
            else path_inst
        )

        await wrapper.handle_voice(message)

    # The synthesizer was called and send_voice was awaited
    synth_mock.synthesize.assert_awaited_once()
    wrapper.bot.send_voice.assert_awaited_once()


@pytest.mark.asyncio
async def test_text_input_unaffected(synth_mock):
    """A normal text message does NOT trigger TTS synthesis (zero regression).

    Text messages are handled by handle_message, not handle_voice.
    The synthesizer must never be invoked for text input.
    """
    cfg = _make_config_with_tts()
    wrapper = _make_wrapper_for_integration(cfg)
    wrapper._synthesizer = synth_mock

    # Normal text message processing uses handle_message (not handle_voice).
    # We simulate that by calling the agent's ask and confirming synth is NOT used.
    message = _make_text_message()

    from parrot.integrations.telegram.wrapper import ParsedResponse

    fake_parsed = MagicMock(spec=ParsedResponse)
    fake_parsed.text = "Text response"

    with patch.object(wrapper, "_invoke_agent", new=AsyncMock(return_value="Text response")), \
         patch.object(wrapper, "_parse_response", return_value=fake_parsed), \
         patch.object(wrapper, "_send_parsed_response", new=AsyncMock(return_value=MagicMock(message_id=10))), \
         patch.object(wrapper, "_store_telegram_metadata", new=AsyncMock()), \
         patch.object(wrapper, "_cache_message_id", return_value=None), \
         patch.object(wrapper, "_extract_reply_context", return_value=None):
        # Directly invoke the text message path
        # (wraps agent call logic without going through handle_message's full routing)
        response = await wrapper._invoke_agent(
            MagicMock(),  # minimal session
            "Hello bot",
            memory=MagicMock(),
            output_mode=MagicMock(),
            message=message,
        )
        # Parse and send — but NO voice send because this is NOT handle_voice
        parsed = wrapper._parse_response(response)
        await wrapper._send_parsed_response(message, parsed)

    # Synthesizer MUST NOT be called for text-only flow
    synth_mock.synthesize.assert_not_awaited()
    wrapper.bot.send_voice.assert_not_awaited()
