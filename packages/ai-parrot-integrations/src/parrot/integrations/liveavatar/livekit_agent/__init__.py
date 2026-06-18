"""LiveAvatar Phase C — voice-native LiveKit Agents bridge (FEAT-243).

This sub-package hosts the LiveKit Agents worker, the ``llm_node`` ai-parrot
bridge and the Pydantic contracts they exchange. The voice pipeline itself
requires the optional ``liveavatar-voice`` extra (``livekit-agents`` and
plugins); the data models in :mod:`.models` are pure Pydantic and import
cleanly even when that extra is not installed.
"""

from .models import AvatarJobMetadata, StructuredOutputMessage

__all__ = ["AvatarJobMetadata", "StructuredOutputMessage"]
