"""LiveAvatar Phase C — voice-native LiveKit Agents bridge (FEAT-243).

This sub-package hosts the LiveKit Agents worker, the ``llm_node`` ai-parrot
bridge and the Pydantic contracts they exchange. The voice pipeline itself
requires the optional ``liveavatar-voice`` extra (``livekit-agents`` and
plugins); the data models in :mod:`.models` are pure Pydantic and import
cleanly even when that extra is not installed.

Note: ``StructuredOutputMessage`` has been relocated to
``parrot.integrations.liveavatar.models`` (FEAT-249 §3.4).
"""

from .models import AvatarJobMetadata

__all__ = ["AvatarJobMetadata"]
