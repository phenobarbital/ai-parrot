"""LiveAvatar integration for AI-Parrot (FEAT-242 — Phase A).

Public re-exports for the ``parrot.integrations.liveavatar`` package.
Downstream modules import from here; implementation details live in
the individual submodules.
"""
from __future__ import annotations

from .avatar_ws import AvatarWebSocket
from .client import LiveAvatarClient
from .models import AvatarSessionHandle, LiveAvatarConfig, LiveKitRoomTokens
from .orchestrator import AvatarSessionOrchestrator
from .room_manager import LiveKitRoomManager
from .speakable import SpeakableFlattener
from .voice_session import VoiceAvatarSession

__all__ = [
    "AvatarSessionHandle",
    "AvatarSessionOrchestrator",
    "AvatarWebSocket",
    "LiveAvatarClient",
    "LiveAvatarConfig",
    "LiveKitRoomManager",
    "LiveKitRoomTokens",
    "SpeakableFlattener",
    "VoiceAvatarSession",
]
