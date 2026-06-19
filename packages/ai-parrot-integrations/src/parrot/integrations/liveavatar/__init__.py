"""LiveAvatar integration for AI-Parrot (FEAT-242 — Phase A).

Public re-exports for the ``parrot.integrations.liveavatar`` package.
Downstream modules import from here; implementation details live in
the individual submodules.
"""
from __future__ import annotations

from .avatar_ws import AvatarWebSocket
from .client import LiveAvatarClient
from .fullmode_observer import FullModeRoomObserver
from .models import (
    AvatarSessionHandle,
    FullModeConfig,
    FullModeSessionHandle,
    LiveAvatarConfig,
    LiveKitRoomTokens,
    StructuredOutputMessage,
    TenantAvatarConfig,
)
from .orchestrator import AvatarSessionOrchestrator
from .room_manager import LiveKitRoomManager
from .speakable import SpeakableFlattener
from .speaker import AvatarTurnSpeaker
from .tenant_config import resolve_fullmode_config
from .voice_provider import AVATAR_PCM_SAMPLE_RATE, AvatarVoiceProvider
from .voice_session import VoiceAvatarSession

__all__ = [
    "AVATAR_PCM_SAMPLE_RATE",
    "AvatarSessionHandle",
    "AvatarSessionOrchestrator",
    "AvatarTurnSpeaker",
    "AvatarVoiceProvider",
    "AvatarWebSocket",
    "FullModeConfig",
    "FullModeRoomObserver",
    "FullModeSessionHandle",
    "LiveAvatarClient",
    "LiveAvatarConfig",
    "LiveKitRoomManager",
    "LiveKitRoomTokens",
    "SpeakableFlattener",
    "StructuredOutputMessage",
    "TenantAvatarConfig",
    "VoiceAvatarSession",
    "resolve_fullmode_config",
]
