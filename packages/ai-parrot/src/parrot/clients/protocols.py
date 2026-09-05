"""Structural protocols for client capabilities (FEAT-416).

Defines type-check targets for cross-cutting client capabilities that are
not part of the ``AbstractClient`` ABC itself. Follows the same
``typing.Protocol`` + ``@runtime_checkable`` pattern used by
``AnthropicBackendProtocol`` (``parrot/clients/anthropic_backends.py``).
"""

from __future__ import annotations

from typing import AsyncIterator, Optional, Protocol, runtime_checkable

from ..models.voice import LiveVoiceResponse, VoiceCapabilities, VoiceStreamOptions


@runtime_checkable
class VoiceCapable(Protocol):
    """Protocol for clients that support bidirectional voice streaming.

    ``GeminiLiveClient`` and ``NovaClient`` (via the ``NovaAudio`` mixin)
    both implement ``stream_voice()`` with a compatible signature; this
    Protocol makes that compatibility explicit and type-checkable, and
    enables ``isinstance(client, VoiceCapable)`` runtime checks.

    Only the common parameter set is declared here — provider-specific
    parameters (e.g. Gemini's ``stt_only``) are passed via ``**kwargs`` by
    callers that need them and are not part of the structural contract.

    FEAT-418 adds ``options`` (the single ``VoiceStreamOptions`` projection
    every ``VoiceCapable`` implementation must honor identically) and the
    ``voice_capabilities`` descriptor property. Because this Protocol is
    ``@runtime_checkable``, ``isinstance()`` checks member *presence* only:
    any client lacking ``voice_capabilities`` now fails
    ``isinstance(client, VoiceCapable)`` — both ``GeminiLiveClient`` and
    ``NovaClient`` gain the property in this same change so the
    ``VoiceBot._create_llm_client()`` gate (``bots/voice.py:273``) never
    breaks.
    """

    @property
    def voice_capabilities(self) -> VoiceCapabilities:
        """Describe what this provider natively supports (FEAT-418)."""
        ...

    async def stream_voice(
        self,
        audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        options: Optional[VoiceStreamOptions] = None,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]: ...
