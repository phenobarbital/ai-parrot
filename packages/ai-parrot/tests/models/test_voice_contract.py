"""Unit tests for the FEAT-418 voice contract types.

Covers ``VoiceStreamOptions``, ``VoiceCapabilities`` and
``VoiceConfig.to_stream_options()`` (spec §3 Module 1).
"""
import dataclasses

import pytest
from parrot.models.voice import (
    AudioFormat,
    VoiceCapabilities,
    VoiceConfig,
    VoiceProvider,
    VoiceStreamOptions,
)


class TestVoiceStreamOptions:
    def test_defaults_match_voice_config(self):
        opts, cfg = VoiceStreamOptions(), VoiceConfig()
        assert (opts.temperature, opts.max_tokens, opts.top_p) == (
            cfg.temperature, cfg.max_tokens, cfg.top_p)

    def test_voice_defaults_to_none_not_puck(self):
        """'Puck' is Gemini-specific; leaking it into Nova is the bug we fix."""
        assert VoiceStreamOptions().voice is None

    def test_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            VoiceStreamOptions().temperature = 0.1

    def test_all_nine_fields_present_with_documented_defaults(self):
        opts = VoiceStreamOptions()
        assert opts.temperature == 0.7
        assert opts.max_tokens == 4096
        assert opts.top_p == 0.9
        assert opts.voice is None
        assert opts.language == "en-US"
        assert opts.stt_only is False
        assert opts.parallel_tool_execution is False
        assert opts.enable_input_transcription is True
        assert opts.enable_output_transcription is True

    def test_field_count_is_nine(self):
        assert len(dataclasses.fields(VoiceStreamOptions)) == 9


class TestProjection:
    def test_projects_config_values(self):
        cfg = VoiceConfig(temperature=0.2, max_tokens=8192, top_p=0.5)
        opts = cfg.to_stream_options()
        assert (opts.temperature, opts.max_tokens, opts.top_p) == (0.2, 8192, 0.5)

    def test_overrides_win(self):
        cfg = VoiceConfig(temperature=0.2)
        assert cfg.to_stream_options(temperature=0.9).temperature == 0.9

    def test_projects_voice_name(self):
        cfg = VoiceConfig(voice_name="Charon")
        assert cfg.to_stream_options().voice == "Charon"

    def test_voice_override_wins(self):
        cfg = VoiceConfig(voice_name="Charon")
        assert cfg.to_stream_options(voice="matthew").voice == "matthew"

    def test_projects_language_and_flags(self):
        cfg = VoiceConfig(
            language="es-ES",
            parallel_tool_execution=True,
            enable_input_transcription=False,
            enable_output_transcription=False,
        )
        opts = cfg.to_stream_options()
        assert opts.language == "es-ES"
        assert opts.parallel_tool_execution is True
        assert opts.enable_input_transcription is False
        assert opts.enable_output_transcription is False

    def test_stt_only_override(self):
        cfg = VoiceConfig()
        assert cfg.to_stream_options(stt_only=True).stt_only is True

    def test_returns_voice_stream_options_instance(self):
        assert isinstance(VoiceConfig().to_stream_options(), VoiceStreamOptions)


class TestVoiceConfigUnchanged:
    def test_existing_fields_and_defaults_untouched(self):
        cfg = VoiceConfig()
        assert cfg.provider == VoiceProvider.GOOGLE_LIVE
        assert cfg.input_format == AudioFormat.PCM_16K
        assert cfg.output_format == AudioFormat.PCM_24K
        assert cfg.input_sample_rate == 16000
        assert cfg.output_sample_rate == 24000
        assert cfg.model is None
        assert cfg.voice_name == "Puck"
        assert cfg.language == "en-US"
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 4096
        assert cfg.top_p == 0.9
        assert cfg.enable_input_transcription is True
        assert cfg.enable_output_transcription is True
        assert cfg.reconnect_on_limit is True
        assert cfg.max_reconnects == 3
        assert cfg.parallel_tool_execution is False

    def test_voice_config_still_mutable(self):
        cfg = VoiceConfig()
        cfg.temperature = 0.1
        assert cfg.temperature == 0.1


class TestVoiceCapabilities:
    def test_declares_audio_formats(self):
        caps = VoiceCapabilities(
            provider=VoiceProvider.NOVA, native_stt_only=False, supports_top_p=True,
            supports_per_call_voice=True, supports_per_call_inference=True,
            parallel_tool_execution=True, emits_reconnect_signal=True,
            supports_session_resumption=False, max_session_seconds=465.0,
            max_output_tokens=4096,
            input_formats=frozenset({AudioFormat.PCM_16K}),
            output_formats=frozenset({AudioFormat.PCM_24K}),
            input_sample_rates=frozenset({16000}), output_sample_rates=frozenset({24000}),
            voice_catalog=frozenset({"matthew"}), default_voice="matthew",
        )
        assert caps.input_formats and caps.output_formats
        assert caps.input_sample_rates and caps.output_sample_rates

    def test_frozen(self):
        caps = VoiceCapabilities(
            provider=VoiceProvider.GOOGLE_LIVE, native_stt_only=True, supports_top_p=False,
            supports_per_call_voice=False, supports_per_call_inference=False,
            parallel_tool_execution=False, emits_reconnect_signal=False,
            supports_session_resumption=False, max_session_seconds=None,
            max_output_tokens=4096,
            input_formats=frozenset({AudioFormat.PCM_16K}),
            output_formats=frozenset({AudioFormat.PCM_24K}),
            input_sample_rates=frozenset({16000}), output_sample_rates=frozenset({24000}),
            voice_catalog=frozenset({"Puck"}), default_voice="Puck",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            caps.native_stt_only = False

    def test_max_session_seconds_optional(self):
        caps = VoiceCapabilities(
            provider=VoiceProvider.GOOGLE_LIVE, native_stt_only=True, supports_top_p=False,
            supports_per_call_voice=False, supports_per_call_inference=False,
            parallel_tool_execution=False, emits_reconnect_signal=False,
            supports_session_resumption=False, max_session_seconds=None,
            max_output_tokens=4096,
            input_formats=frozenset({AudioFormat.PCM_16K}),
            output_formats=frozenset({AudioFormat.PCM_24K}),
            input_sample_rates=frozenset({16000}), output_sample_rates=frozenset({24000}),
            voice_catalog=frozenset({"Puck"}), default_voice="Puck",
        )
        assert caps.max_session_seconds is None
