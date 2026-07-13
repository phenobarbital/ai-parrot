"""Unit tests for Nova Sonic voice-provider registration (FEAT-302,
TASK-1749).

``aws_sdk_bedrock_runtime`` (Pre-Alpha) is not installed in this
environment, so tests that resolve ``VoiceProvider.NOVA_SONIC`` to a real
``NovaSonicClient`` class stub the SDK presence check via ``sys.modules``
(same pattern as ``packages/ai-parrot/tests/clients/test_nova_sonic.py``).
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

from parrot.voice.models import VoiceProvider
from parrot.voice.handler import VoiceChatHandler, resolve_voice_client_class


class TestNovaSonicProvider:
    def test_enum_exists(self):
        assert VoiceProvider.NOVA_SONIC.value == "nova_sonic"

    def test_all_providers_present(self):
        providers = [p.value for p in VoiceProvider]
        assert "nova_sonic" in providers
        assert "google_live" in providers
        assert "openai_realtime" in providers


class TestProviderResolution:
    def test_resolve_google_live_returns_gemini_live_client(self):
        from parrot.clients.live import GeminiLiveClient
        assert resolve_voice_client_class(VoiceProvider.GOOGLE_LIVE) is GeminiLiveClient

    def test_resolve_nova_sonic_returns_nova_sonic_client(self):
        with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}):
            from parrot.clients.nova_sonic import NovaSonicClient
            assert resolve_voice_client_class(VoiceProvider.NOVA_SONIC) is NovaSonicClient

    def test_resolve_nova_sonic_raises_import_error_when_sdk_missing(self):
        if 'aws_sdk_bedrock_runtime' in sys.modules:
            del sys.modules['aws_sdk_bedrock_runtime']
        # nova_sonic module import itself doesn't need the SDK, only
        # NovaSonicClient's constructor does — resolve_voice_client_class
        # only imports the class, so this should succeed; verify it does
        # (no crash) and the SDK check is deferred to instantiation.
        client_cls = resolve_voice_client_class(VoiceProvider.NOVA_SONIC)
        with pytest.raises(ImportError):
            client_cls()

    def test_voice_chat_handler_recognizes_nova_sonic(self):
        """VoiceChatHandler.resolve_provider_client() recognizes NOVA_SONIC."""
        with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}):
            from parrot.clients.nova_sonic import NovaSonicClient
            assert VoiceChatHandler.resolve_provider_client(
                VoiceProvider.NOVA_SONIC
            ) is NovaSonicClient

    def test_voice_chat_handler_default_provider_unchanged(self):
        """Non-Nova-Sonic providers still resolve to GeminiLiveClient — no
        regression for the existing (only fully-wired) voice provider."""
        from parrot.clients.live import GeminiLiveClient
        assert VoiceChatHandler.resolve_provider_client(
            VoiceProvider.GOOGLE_LIVE
        ) is GeminiLiveClient
