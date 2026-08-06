"""Structural protocols for client capabilities (FEAT-416).

Defines type-check targets for cross-cutting client capabilities that are
not part of the ``AbstractClient`` ABC itself. Follows the same
``typing.Protocol`` + ``@runtime_checkable`` pattern used by
``AnthropicBackendProtocol`` (``parrot/clients/anthropic_backends.py``).
"""
from __future__ import annotations

from typing import AsyncIterator, Optional, Protocol, runtime_checkable

from .live import LiveVoiceResponse


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
    """

    async def stream_voice(
        self,
        audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]:
        ...
