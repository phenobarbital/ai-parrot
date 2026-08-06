"""Protocol satisfaction tests for VoiceCapable (FEAT-416, TASK-2145).

Verifies that ``GeminiLiveClient`` and ``NovaClient`` structurally satisfy
the ``VoiceCapable`` protocol, and that a plain ``AbstractClient`` subclass
without ``stream_voice()`` does not.
"""
from parrot.clients.protocols import VoiceCapable


class TestVoiceCapableProtocol:
    def test_gemini_satisfies_protocol(self):
        """GeminiLiveClient structurally satisfies VoiceCapable."""
        from parrot.clients.live import GeminiLiveClient
        assert issubclass(GeminiLiveClient, VoiceCapable)

    def test_nova_satisfies_protocol(self):
        """NovaClient (via NovaAudio mixin) satisfies VoiceCapable."""
        from parrot.clients.nova import NovaClient
        assert issubclass(NovaClient, VoiceCapable)

    def test_plain_client_rejected(self):
        """A client without stream_voice() does NOT satisfy VoiceCapable."""
        from parrot.clients.base import AbstractClient
        # AbstractClient itself does not define stream_voice()
        assert not issubclass(AbstractClient, VoiceCapable)
