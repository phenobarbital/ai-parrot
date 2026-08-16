"""Tests for ``VoiceConfig.provider`` (FEAT-302/FEAT-315, TASK-1812
migration — provider literal renamed from ``'nova_sonic'`` to ``'nova'``)
and for the unified ``VoiceConfig``/``VoiceProvider`` merge (FEAT-416,
TASK-2146).

``parrot.models.voice`` has no import chain into ``parrot.bots`` (unlike
``parrot.bots.voice.VoiceBot`` itself, which cannot be imported in this
environment — the Cython extension ``parrot.utils.types`` is not built
here, a pre-existing, unrelated environment limitation), so this is tested
directly rather than via source inspection.

Note: ``VoiceProvider`` inherits from ``str`` (FEAT-416), so a coerced
``VoiceConfig.provider`` still compares equal to its plain-string value —
``TestVoiceConfigProvider`` below (pre-existing, string-based assertions)
and ``TestVoiceConfigUnified`` (enum-based assertions) both hold.
"""
import warnings

from parrot.models.voice import VoiceConfig, VoiceProvider


class TestVoiceConfigProvider:
    def test_default_provider_is_google_live(self):
        """Default behavior is unchanged: GeminiLiveClient via google_live."""
        assert VoiceConfig().provider == "google_live"

    def test_provider_can_be_set_to_nova(self):
        assert VoiceConfig(provider="nova").provider == "nova"


class TestVoiceConfigUnified:
    def test_all_fields_exist(self):
        config = VoiceConfig()
        assert hasattr(config, 'provider')
        assert hasattr(config, 'top_p')
        assert hasattr(config, 'parallel_tool_execution')
        assert hasattr(config, 'reconnect_on_limit')
        assert hasattr(config, 'max_reconnects')
        assert hasattr(config, 'vad_mode')

    def test_provider_string_coercion(self):
        config = VoiceConfig(provider="nova")
        assert config.provider == VoiceProvider.NOVA

    def test_provider_enum_direct(self):
        config = VoiceConfig(provider=VoiceProvider.GOOGLE_LIVE)
        assert config.provider == VoiceProvider.GOOGLE_LIVE

    def test_defaults(self):
        config = VoiceConfig()
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.top_p == 0.9
        assert config.max_reconnects == 3
        assert config.parallel_tool_execution is False
        assert config.reconnect_on_limit is True

    def test_backward_compat_import(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from parrot.voice.models import VoiceConfig as IntegVoiceConfig
            assert issubclass(IntegVoiceConfig, type(VoiceConfig()))
            assert any(
                issubclass(warning.category, DeprecationWarning) for warning in w
            )
