"""
Unit tests for Telegram TTS voice-reply wiring (TASK-1409 / FEAT-213).

Tests cover:
- TelegramAgentConfig gains tts_enabled, tts_backend, tts_voice, reply_in_kind
- from_dict reads all four new fields; missing keys use defaults (opt-in)
- voice input + tts_enabled + reply_in_kind → bot.send_voice called with audio bytes
- Synth raises → text reply still sent, no exception propagates (degradation)
- tts_enabled=False → synth never invoked
- _get_synthesizer creates a VoiceSynthesizer with TTSConfig from config
- close() releases the synthesizer
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.integrations.telegram.models import TelegramAgentConfig
from parrot.voice.tts.models import SynthesisResult, TTSConfig
from parrot.voice.transcriber import VoiceTranscriberConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_voice_config(**kwargs) -> VoiceTranscriberConfig:
    defaults = dict(enabled=True, max_audio_duration_seconds=60, show_transcription=False)
    defaults.update(kwargs)
    return VoiceTranscriberConfig(**defaults)


def _make_config(**kwargs) -> TelegramAgentConfig:
    """Return a TelegramAgentConfig with sensible test defaults."""
    defaults = dict(
        name="TTSBot",
        chatbot_id="tts_bot",
        bot_token="test:token",
        voice_config=_make_voice_config(),
    )
    defaults.update(kwargs)
    return TelegramAgentConfig(**defaults)


def _make_wrapper(config: TelegramAgentConfig):
    """Create a TelegramAgentWrapper with mocked agent and bot."""
    mock_agent = MagicMock()
    mock_agent.get_available_tools = MagicMock(return_value=[])
    mock_agent.ask = AsyncMock(return_value="Agent reply text")

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


def _make_voice_message(chat_id: int = 12345, file_id: str = "vf_001") -> MagicMock:
    """Return a minimal mocked Telegram voice message."""
    msg = MagicMock()
    msg.chat.id = chat_id
    msg.answer = AsyncMock()
    msg.message_id = 999

    user = MagicMock()
    user.id = 67890
    user.username = "tester"
    user.first_name = "Test"
    user.last_name = "User"
    msg.from_user = user

    voice = MagicMock()
    voice.file_id = file_id
    voice.duration = 3
    msg.voice = voice
    msg.audio = None

    msg.reply_to_message = None
    return msg


def _make_synth_mock(audio: bytes = b"OGG...") -> MagicMock:
    """Return a MagicMock acting as a VoiceSynthesizer."""
    s = MagicMock()
    s.synthesize = AsyncMock(
        return_value=SynthesisResult(audio=audio, mime_format="audio/ogg")
    )
    s.close = AsyncMock()
    return s


# ---------------------------------------------------------------------------
# TelegramAgentConfig field tests
# ---------------------------------------------------------------------------


def test_config_defaults_opt_in():
    """New TTS fields default to False/safe values (opt-in)."""
    cfg = TelegramAgentConfig(name="b", chatbot_id="b")
    assert cfg.tts_enabled is False
    assert cfg.tts_backend == "google"
    assert cfg.tts_voice is None
    assert cfg.reply_in_kind is True


def test_config_from_dict_defaults():
    """from_dict with no tts_* keys uses the opt-in defaults."""
    cfg = TelegramAgentConfig.from_dict("bot", {"chatbot_id": "x"})
    assert cfg.tts_enabled is False
    assert cfg.tts_backend == "google"
    assert cfg.tts_voice is None
    assert cfg.reply_in_kind is True


def test_config_from_dict_reads_all_tts_fields():
    """from_dict reads all four new TTS fields."""
    cfg = TelegramAgentConfig.from_dict(
        "bot",
        {
            "chatbot_id": "x",
            "tts_enabled": True,
            "tts_backend": "google",
            "tts_voice": "Kore",
            "reply_in_kind": False,
        },
    )
    assert cfg.tts_enabled is True
    assert cfg.tts_backend == "google"
    assert cfg.tts_voice == "Kore"
    assert cfg.reply_in_kind is False


def test_config_from_dict_without_tts_keys_still_loads():
    """Existing configs (no tts_* keys) load fine — no KeyError."""
    cfg = TelegramAgentConfig.from_dict("legacy_bot", {"chatbot_id": "abc"})
    assert cfg.tts_enabled is False


# ---------------------------------------------------------------------------
# _get_synthesizer
# ---------------------------------------------------------------------------


def test_get_synthesizer_creates_voice_synthesizer():
    """_get_synthesizer returns a VoiceSynthesizer with TTSConfig from config."""
    cfg = _make_config(tts_enabled=True, tts_backend="google", tts_voice="Puck")
    wrapper = _make_wrapper(cfg)

    from parrot.voice.tts.synthesizer import VoiceSynthesizer

    synth = wrapper._get_synthesizer()
    assert isinstance(synth, VoiceSynthesizer)
    assert synth.config.backend == "google"
    assert synth.config.voice == "Puck"


def test_get_synthesizer_cached():
    """_get_synthesizer returns the same instance on repeated calls."""
    cfg = _make_config()
    wrapper = _make_wrapper(cfg)

    s1 = wrapper._get_synthesizer()
    s2 = wrapper._get_synthesizer()
    assert s1 is s2


# ---------------------------------------------------------------------------
# TTS branch in handle_voice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_voice_replies_with_voice():
    """Voice input + tts_enabled + reply_in_kind → bot.send_voice called.

    We mock _invoke_agent and _send_parsed_response at the wrapper level to
    isolate the TTS wiring from the agent execution machinery.
    """
    cfg = _make_config(tts_enabled=True, reply_in_kind=True)
    wrapper = _make_wrapper(cfg)

    synth_mock = _make_synth_mock(b"OGG_BYTES")
    wrapper._synthesizer = synth_mock

    message = _make_voice_message()
    file_info = MagicMock()
    file_info.file_path = "voice/abc.ogg"
    wrapper.bot.get_file = AsyncMock(return_value=file_info)

    from parrot.voice.transcriber import TranscriptionResult

    mock_transcriber = MagicMock()
    mock_transcriber.transcribe_file = AsyncMock(
        return_value=TranscriptionResult(
            text="Hello from voice",
            language="en",
            duration_seconds=3.0,
            processing_time_ms=500,
        )
    )
    wrapper._transcriber = mock_transcriber

    # Mock the agent invocation and response parsing to isolate TTS wiring
    from parrot.integrations.telegram.wrapper import ParsedResponse
    fake_parsed = MagicMock(spec=ParsedResponse)
    fake_parsed.text = "Agent reply text"

    with patch.object(wrapper, "_invoke_agent", new=AsyncMock(return_value="Agent reply text")), \
         patch.object(wrapper, "_parse_response", return_value=fake_parsed), \
         patch.object(wrapper, "_send_parsed_response", new=AsyncMock(return_value=MagicMock(message_id=42))), \
         patch.object(wrapper, "_store_telegram_metadata", new=AsyncMock()), \
         patch("tempfile.NamedTemporaryFile") as mock_ntf, \
         patch("parrot.integrations.telegram.wrapper.Path") as mock_path:
        tmp = MagicMock()
        tmp.name = "/tmp/tg_tts_test.ogg"
        mock_ntf.return_value = tmp

        path_inst = MagicMock()
        path_inst.exists.return_value = False
        path_inst.suffix = ".ogg"
        mock_path.return_value = path_inst
        mock_path.side_effect = lambda x: (
            MagicMock(suffix=".ogg")
            if isinstance(x, str) and "abc.ogg" in x
            else path_inst
        )

        await wrapper.handle_voice(message)

    synth_mock.synthesize.assert_awaited_once()
    wrapper.bot.send_voice.assert_awaited_once()

    # Verify the audio bytes were passed via BufferedInputFile
    call_args = wrapper.bot.send_voice.call_args
    buf_file = call_args[0][1]  # second positional arg is the BufferedInputFile
    assert buf_file.data == b"OGG_BYTES"


@pytest.mark.asyncio
async def test_handle_voice_degrades_on_tts_error():
    """If synth raises, the text reply was already sent — no exception propagates."""
    cfg = _make_config(tts_enabled=True, reply_in_kind=True)
    wrapper = _make_wrapper(cfg)

    failing_synth = MagicMock()
    failing_synth.synthesize = AsyncMock(side_effect=RuntimeError("TTS boom"))
    wrapper._synthesizer = failing_synth

    message = _make_voice_message()
    file_info = MagicMock()
    file_info.file_path = "voice/abc.ogg"
    wrapper.bot.get_file = AsyncMock(return_value=file_info)

    from parrot.voice.transcriber import TranscriptionResult
    from parrot.integrations.telegram.wrapper import ParsedResponse

    mock_transcriber = MagicMock()
    mock_transcriber.transcribe_file = AsyncMock(
        return_value=TranscriptionResult(
            text="Degrade test",
            language="en",
            duration_seconds=2.0,
            processing_time_ms=400,
        )
    )
    wrapper._transcriber = mock_transcriber

    fake_parsed = MagicMock(spec=ParsedResponse)
    fake_parsed.text = "Text reply"

    with patch.object(wrapper, "_invoke_agent", new=AsyncMock(return_value="Text reply")), \
         patch.object(wrapper, "_parse_response", return_value=fake_parsed), \
         patch.object(wrapper, "_send_parsed_response", new=AsyncMock(return_value=MagicMock(message_id=42))), \
         patch.object(wrapper, "_store_telegram_metadata", new=AsyncMock()), \
         patch("tempfile.NamedTemporaryFile") as mock_ntf, \
         patch("parrot.integrations.telegram.wrapper.Path") as mock_path:
        tmp = MagicMock()
        tmp.name = "/tmp/tg_degrade_test.ogg"
        mock_ntf.return_value = tmp

        path_inst = MagicMock()
        path_inst.exists.return_value = False
        path_inst.suffix = ".ogg"
        mock_path.return_value = path_inst
        mock_path.side_effect = lambda x: (
            MagicMock(suffix=".ogg")
            if isinstance(x, str) and "abc.ogg" in x
            else path_inst
        )

        # Must complete without raising — TTS error is swallowed
        await wrapper.handle_voice(message)

    # send_voice should NOT have been awaited (synth failed)
    wrapper.bot.send_voice.assert_not_awaited()


@pytest.mark.asyncio
async def test_tts_disabled_synth_never_invoked():
    """With tts_enabled=False, the synthesizer is never called."""
    cfg = _make_config(tts_enabled=False)
    wrapper = _make_wrapper(cfg)

    synth_mock = _make_synth_mock()
    wrapper._synthesizer = synth_mock

    message = _make_voice_message()
    file_info = MagicMock()
    file_info.file_path = "voice/abc.ogg"
    wrapper.bot.get_file = AsyncMock(return_value=file_info)

    from parrot.voice.transcriber import TranscriptionResult
    from parrot.integrations.telegram.wrapper import ParsedResponse

    mock_transcriber = MagicMock()
    mock_transcriber.transcribe_file = AsyncMock(
        return_value=TranscriptionResult(
            text="Text only",
            language="en",
            duration_seconds=1.5,
            processing_time_ms=300,
        )
    )
    wrapper._transcriber = mock_transcriber

    fake_parsed = MagicMock(spec=ParsedResponse)
    fake_parsed.text = "Text only reply"

    with patch.object(wrapper, "_invoke_agent", new=AsyncMock(return_value="Text only reply")), \
         patch.object(wrapper, "_parse_response", return_value=fake_parsed), \
         patch.object(wrapper, "_send_parsed_response", new=AsyncMock(return_value=MagicMock(message_id=42))), \
         patch.object(wrapper, "_store_telegram_metadata", new=AsyncMock()), \
         patch("tempfile.NamedTemporaryFile") as mock_ntf, \
         patch("parrot.integrations.telegram.wrapper.Path") as mock_path:
        tmp = MagicMock()
        tmp.name = "/tmp/tg_disabled_test.ogg"
        mock_ntf.return_value = tmp

        path_inst = MagicMock()
        path_inst.exists.return_value = False
        path_inst.suffix = ".ogg"
        mock_path.return_value = path_inst
        mock_path.side_effect = lambda x: (
            MagicMock(suffix=".ogg")
            if isinstance(x, str) and "abc.ogg" in x
            else path_inst
        )

        await wrapper.handle_voice(message)

    synth_mock.synthesize.assert_not_awaited()
    wrapper.bot.send_voice.assert_not_awaited()


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_releases_synthesizer():
    """close() calls synth.close() and sets _synthesizer to None."""
    cfg = _make_config()
    wrapper = _make_wrapper(cfg)
    synth_mock = _make_synth_mock()
    wrapper._synthesizer = synth_mock
    # Prevent transcriber close from failing
    wrapper._transcriber = None

    await wrapper.close()

    synth_mock.close.assert_awaited_once()
    assert wrapper._synthesizer is None
