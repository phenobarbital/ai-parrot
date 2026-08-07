"""Protocol satisfaction tests for VoiceCapable (FEAT-416, TASK-2145).

Verifies that ``GeminiLiveClient`` and ``NovaClient`` structurally satisfy
the ``VoiceCapable`` protocol, and that a plain ``AbstractClient`` subclass
without ``stream_voice()`` does not.

FEAT-418 (TASK-2165) added the ``voice_capabilities`` property to the
Protocol. A ``@runtime_checkable`` ``Protocol`` with a non-method member
(a property, as opposed to a plain method) no longer supports
``issubclass()`` — Python's ``typing`` module raises ``TypeError:
Protocols with non-method members don't support issubclass()`` — while
``isinstance()`` checks remain fully supported. This mirrors the actual
runtime gate at ``bots/voice.py:273``
(``if not isinstance(client, VoiceCapable):``), which already used
``isinstance()``, not ``issubclass()``. These assertions were converted
from ``issubclass(Class, ...)`` to ``isinstance(Class(), ...)`` for that
reason — no behavioral coverage is lost.
"""
from parrot.clients.protocols import VoiceCapable


class TestVoiceCapableProtocol:
    def test_gemini_satisfies_protocol(self):
        """GeminiLiveClient structurally satisfies VoiceCapable."""
        from parrot.clients.live import GeminiLiveClient
        assert isinstance(GeminiLiveClient(), VoiceCapable)

    def test_nova_satisfies_protocol(self):
        """NovaClient (via NovaAudio mixin) satisfies VoiceCapable."""
        from parrot.clients.nova import NovaClient
        assert isinstance(NovaClient(), VoiceCapable)

    def test_plain_client_rejected(self):
        """A client without stream_voice() does NOT satisfy VoiceCapable.

        ``AbstractClient`` is abstract and cannot be instantiated directly
        (``ask``/``ask_stream``/``get_client``/``invoke``/``resume`` are
        all abstract methods); a minimal concrete stub that implements
        those but deliberately omits ``stream_voice()``/
        ``voice_capabilities`` demonstrates the same negative case.
        """

        class _PlainClient:
            async def ask(self, *args, **kwargs):
                ...

            async def ask_stream(self, *args, **kwargs):
                ...

            async def get_client(self):
                ...

            async def invoke(self, *args, **kwargs):
                ...

            async def resume(self, *args, **kwargs):
                ...

        assert not isinstance(_PlainClient(), VoiceCapable)
