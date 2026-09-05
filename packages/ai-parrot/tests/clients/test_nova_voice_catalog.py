"""Nova voice catalog + validation tests (FEAT-418, TASK-2169).

Covers spec §3 Module 4 (voice half): the NOVA_VOICE_CATALOG constant,
NovaAudio._resolve_voice() validation with a warned fallback, and the
descriptor sourcing voice_catalog/default_voice from that constant.
"""

from parrot.clients.amazon.nova import NovaClient
from parrot.clients.amazon.nova.audio import NOVA_VOICE_CATALOG


class TestVoiceValidation:
    def test_catalog_voice_passes_through(self):
        client = NovaClient(voice_id="tiffany")
        assert client._resolve_voice("tiffany") == "tiffany"

    def test_gemini_voice_falls_back_warned(self, caplog):
        """bots/voice.py:198 sends 'Puck' (a Gemini voice) into Nova today."""
        client = NovaClient()
        with caplog.at_level("WARNING"):
            assert client._resolve_voice("Puck") == "matthew"
        assert any("Puck" in r.message for r in caplog.records)

    def test_case_insensitive(self):
        assert NovaClient()._resolve_voice("Matthew") == "matthew"

    def test_never_raises(self):
        NovaClient()._resolve_voice("definitely-not-a-voice")

    def test_none_uses_constructor_default(self):
        client = NovaClient(voice_id="amy")
        assert client._resolve_voice(None) == "amy"

    def test_does_not_mutate_voice_id(self):
        client = NovaClient(voice_id="matthew")
        client._resolve_voice("Puck")
        assert client.voice_id == "matthew"

    def test_whitespace_and_case_normalized(self):
        assert NovaClient()._resolve_voice("  Tiffany  ") == "tiffany"


class TestVoiceCatalogConstant:
    def test_catalog_is_frozenset(self):
        assert isinstance(NOVA_VOICE_CATALOG, frozenset)

    def test_catalog_contains_documented_voices(self):
        assert NOVA_VOICE_CATALOG == frozenset({"matthew", "tiffany", "amy"})


class TestDescriptorUsesCatalog:
    def test_voice_catalog_matches_constant(self):
        assert NovaClient().voice_capabilities.voice_catalog == NOVA_VOICE_CATALOG

    def test_default_voice_matches_constructor_voice_id(self):
        assert NovaClient(voice_id="tiffany").voice_capabilities.default_voice == "tiffany"

    def test_default_voice_id_is_matthew(self):
        assert NovaClient().voice_capabilities.default_voice == "matthew"
