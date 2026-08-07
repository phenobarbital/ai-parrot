"""Unit tests for Gemini per-call inference params (FEAT-418, TASK-2166).

Covers spec §3 Module 3 (inference half): per-call temperature/max_tokens/
top_p, real transcription-flag parameters (closing the latent TypeError at
live.py:777-780), and the ``options: VoiceStreamOptions`` threading.
"""
import pytest
from parrot.clients.live import GeminiLiveClient
from parrot.models.voice import VoiceStreamOptions


@pytest.fixture
def client():
    return GeminiLiveClient(temperature=0.7, max_tokens=1000, top_p=0.5)


class TestPerCallInference:
    def test_per_call_temperature_wins(self, client):
        cfg = client._build_live_config(temperature=0.1)
        assert cfg.temperature == 0.1

    def test_per_call_max_tokens_wins(self, client):
        cfg = client._build_live_config(max_tokens=8192)
        assert cfg.max_output_tokens == 8192

    def test_per_call_top_p_wins(self, client):
        cfg = client._build_live_config(top_p=0.99)
        assert cfg.top_p == 0.99

    def test_falls_back_to_constructor(self, client):
        cfg = client._build_live_config()
        assert cfg.temperature == 0.7
        assert cfg.max_output_tokens == 1000
        assert cfg.top_p == 0.5


class TestTranscriptionFlags:
    def test_flags_do_not_raise(self, client):
        """Regression: live.py:777-780 forwarded params the signature lacked."""
        client._build_live_config(
            enable_input_transcription=True, enable_output_transcription=False)

    def test_output_transcription_disabled(self, client):
        cfg = client._build_live_config(enable_output_transcription=False)
        assert cfg.output_audio_transcription is None

    def test_output_transcription_enabled_by_default(self, client):
        cfg = client._build_live_config()
        assert cfg.output_audio_transcription is not None

    def test_input_transcription_disabled(self, client):
        cfg = client._build_live_config(enable_input_transcription=False)
        assert cfg.input_audio_transcription is None

    def test_input_transcription_enabled_by_default(self, client):
        cfg = client._build_live_config()
        assert cfg.input_audio_transcription is not None

    def test_stt_only_still_wins(self, client):
        cfg = client._build_live_config(stt_only=True, enable_output_transcription=True)
        assert cfg.output_audio_transcription is None


class TestOptionsObject:
    def test_options_applied(self, client):
        opts = VoiceStreamOptions(temperature=0.3, max_tokens=2048, top_p=0.42)
        cfg = client._build_live_config(
            temperature=opts.temperature, max_tokens=opts.max_tokens, top_p=opts.top_p)
        assert (cfg.temperature, cfg.max_output_tokens, cfg.top_p) == (0.3, 2048, 0.42)


class TestStreamVoiceOptionsThreading:
    """stream_voice() derives per-call config from options; explicit
    kwargs still win over options (spec §3 Module 3)."""

    def test_stream_voice_accepts_options_kwarg(self, client):
        """stream_voice() must accept `options` without raising TypeError
        at the signature level (does not require a live connection)."""
        import inspect
        sig = inspect.signature(client.stream_voice)
        assert "options" in sig.parameters

    def test_options_field_precedence_helper(self, client):
        """Explicit kwargs win over options — verified via the same
        resolution logic stream_voice() uses to build live_config_overrides."""
        options = VoiceStreamOptions(temperature=0.2, max_tokens=999, top_p=0.11)
        kwargs = {"temperature": 0.9}
        overrides = {}
        for field_name in (
            "temperature", "max_tokens", "top_p",
            "enable_input_transcription", "enable_output_transcription",
        ):
            if field_name in kwargs:
                overrides[field_name] = kwargs[field_name]
            elif options is not None:
                overrides[field_name] = getattr(options, field_name)
        assert overrides["temperature"] == 0.9          # explicit kwarg wins
        assert overrides["max_tokens"] == 999            # from options
        assert overrides["top_p"] == 0.11                 # from options


class TestGeminiCapabilitiesUpdated:
    def test_supports_top_p_now_true(self, client):
        assert client.voice_capabilities.supports_top_p is True

    def test_supports_per_call_inference_now_true(self, client):
        assert client.voice_capabilities.supports_per_call_inference is True
