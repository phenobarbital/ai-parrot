"""Unit tests for Nova voice-provider registration (FEAT-302/FEAT-315 —
migrated from test_nova_sonic_provider.py, TASK-1812).

Unlike the deleted ``NovaSonicClient``, constructing ``NovaClient`` never
requires the Pre-Alpha ``aws_sdk_bedrock_runtime`` package — the guard
moved to the first ``stream_voice()`` call (TASK-1807/FEAT-315). No
``sys.modules`` stubbing is needed here for construction; it would only be
needed around a real ``stream_voice()`` call (see
``packages/ai-parrot/tests/clients/test_nova.py`` for that coverage).
"""
from parrot.voice.models import VoiceProvider
from parrot.voice.handler import VoiceChatHandler, resolve_voice_client_class


class TestNovaProvider:
    def test_enum_exists(self):
        assert VoiceProvider.NOVA.value == "nova"

    def test_all_providers_present(self):
        providers = [p.value for p in VoiceProvider]
        assert "nova" in providers
        assert "google_live" in providers
        assert "openai_realtime" in providers

    def test_voice_provider_renamed(self):
        """spec §5 acceptance criterion: NOVA_SONIC is fully removed, no alias."""
        assert not any(m.value == "nova_sonic" for m in VoiceProvider)
        assert not hasattr(VoiceProvider, "NOVA_SONIC")


class TestProviderResolution:
    def test_resolve_google_live_returns_gemini_live_client(self):
        from parrot.clients.live import GeminiLiveClient
        assert resolve_voice_client_class(VoiceProvider.GOOGLE_LIVE) is GeminiLiveClient

    def test_resolve_nova_returns_nova_client(self):
        from parrot.clients.nova import NovaClient
        assert resolve_voice_client_class(VoiceProvider.NOVA) is NovaClient

    def test_resolve_nova_does_not_require_sdk_to_construct(self):
        """FEAT-315: constructing NovaClient never requires the Pre-Alpha
        SDK — only stream_voice() does (guard moved, TASK-1807)."""
        client_cls = resolve_voice_client_class(VoiceProvider.NOVA)
        client_cls()  # must not raise

    def test_voice_chat_handler_recognizes_nova(self):
        """VoiceChatHandler.resolve_provider_client() recognizes NOVA."""
        from parrot.clients.nova import NovaClient
        assert VoiceChatHandler.resolve_provider_client(
            VoiceProvider.NOVA
        ) is NovaClient

    def test_voice_chat_handler_default_provider_unchanged(self):
        """Non-Nova providers still resolve to GeminiLiveClient — no
        regression for the existing (only fully-wired) voice provider."""
        from parrot.clients.live import GeminiLiveClient
        assert VoiceChatHandler.resolve_provider_client(
            VoiceProvider.GOOGLE_LIVE
        ) is GeminiLiveClient
