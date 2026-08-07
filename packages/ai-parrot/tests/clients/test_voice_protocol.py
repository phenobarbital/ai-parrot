"""Protocol conformance tests for the FEAT-418 ``VoiceCapable`` extension.

Covers spec §3 Module 2: the ``options`` parameter and ``voice_capabilities``
property on the Protocol, and both clients' descriptors.
"""
from collections.abc import AsyncIterator

from parrot.clients.protocols import VoiceCapable
from parrot.models.voice import AudioFormat, VoiceProvider


class _NoCapabilities:
    """A stream_voice()-only stub — deliberately lacks voice_capabilities."""

    async def stream_voice(
        self, audio_iterator, system_prompt=None, session_id=None, user_id=None,
        **kwargs,
    ) -> AsyncIterator:
        yield None


def test_stub_without_capabilities_is_not_voice_capable():
    assert not isinstance(_NoCapabilities(), VoiceCapable)


def test_gemini_satisfies_protocol():
    from parrot.clients.live import GeminiLiveClient
    assert isinstance(GeminiLiveClient(), VoiceCapable)


def test_nova_satisfies_protocol():
    from parrot.clients.nova import NovaClient
    assert isinstance(NovaClient(), VoiceCapable)


def test_descriptors_tell_current_truth():
    from parrot.clients.live import GeminiLiveClient
    from parrot.clients.nova import NovaClient
    gemini = GeminiLiveClient().voice_capabilities
    nova = NovaClient().voice_capabilities
    assert gemini.provider is VoiceProvider.GOOGLE_LIVE
    assert gemini.native_stt_only is True
    assert gemini.supports_top_p is False          # flipped by TASK-2166
    assert gemini.supports_per_call_voice is False  # flipped by TASK-2167
    assert gemini.emits_reconnect_signal is False   # flipped by TASK-2168
    assert nova.provider is VoiceProvider.NOVA
    assert nova.native_stt_only is False           # Nova always generates
    assert nova.emits_reconnect_signal is True     # 465 s limit


class TestGeminiVoiceCapabilities:
    def test_audio_formats_pcm(self):
        from parrot.clients.live import GeminiLiveClient
        caps = GeminiLiveClient().voice_capabilities
        assert caps.input_formats == frozenset({AudioFormat.PCM_16K})
        assert caps.output_formats == frozenset({AudioFormat.PCM_24K})
        assert caps.input_sample_rates == frozenset({16000})
        assert caps.output_sample_rates == frozenset({24000})

    def test_default_voice_is_puck(self):
        from parrot.clients.live import GeminiLiveClient
        assert GeminiLiveClient().voice_capabilities.default_voice == "Puck"

    def test_voice_catalog_uses_real_profiles(self):
        from parrot.clients.live import GeminiLiveClient
        from parrot.models.google import ALL_VOICE_PROFILES
        caps = GeminiLiveClient().voice_capabilities
        assert caps.voice_catalog == frozenset(
            p.voice_name for p in ALL_VOICE_PROFILES
        )
        assert "Puck" in caps.voice_catalog
        assert "Charon" in caps.voice_catalog

    def test_parallel_tool_execution_already_true(self):
        from parrot.clients.live import GeminiLiveClient
        assert GeminiLiveClient().voice_capabilities.parallel_tool_execution is True


class TestNovaVoiceCapabilities:
    def test_audio_formats_pcm(self):
        from parrot.clients.nova import NovaClient
        caps = NovaClient().voice_capabilities
        assert caps.input_formats == frozenset({AudioFormat.PCM_16K})
        assert caps.output_formats == frozenset({AudioFormat.PCM_24K})

    def test_default_voice_is_matthew(self):
        from parrot.clients.nova import NovaClient
        assert NovaClient().voice_capabilities.default_voice == "matthew"

    def test_voice_catalog_has_three_documented_voices(self):
        from parrot.clients.nova import NovaClient
        caps = NovaClient().voice_capabilities
        assert caps.voice_catalog == frozenset({"matthew", "tiffany", "amy"})

    def test_max_session_seconds_matches_connection_limit(self):
        from parrot.clients.nova import NovaClient
        from parrot.clients.nova.audio import NovaAudio
        caps = NovaClient().voice_capabilities
        assert caps.max_session_seconds == NovaAudio._CONNECTION_LIMIT_SECONDS

    def test_supports_per_call_inference_already_true(self):
        from parrot.clients.nova import NovaClient
        assert NovaClient().voice_capabilities.supports_per_call_inference is True

    def test_supports_session_resumption_false(self):
        from parrot.clients.nova import NovaClient
        assert NovaClient().voice_capabilities.supports_session_resumption is False
