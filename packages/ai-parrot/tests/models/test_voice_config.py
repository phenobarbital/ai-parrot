"""Tests for ``VoiceConfig.provider`` (FEAT-302, code review follow-up).

``parrot.models.voice`` has no import chain into ``parrot.bots`` (unlike
``parrot.bots.voice.VoiceBot`` itself, which cannot be imported in this
environment — the Cython extension ``parrot.utils.types`` is not built
here, a pre-existing, unrelated environment limitation), so this is tested
directly rather than via source inspection.
"""
from parrot.models.voice import VoiceConfig


class TestVoiceConfigProvider:
    def test_default_provider_is_google_live(self):
        """Default behavior is unchanged: GeminiLiveClient via google_live."""
        assert VoiceConfig().provider == "google_live"

    def test_provider_can_be_set_to_nova_sonic(self):
        assert VoiceConfig(provider="nova_sonic").provider == "nova_sonic"
