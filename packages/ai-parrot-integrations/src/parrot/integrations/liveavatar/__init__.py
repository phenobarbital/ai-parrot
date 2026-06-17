"""LiveAvatar integration for AI-Parrot (FEAT-242 — Phase A).

Public re-exports for the ``parrot.integrations.liveavatar`` package.
Downstream modules import from here; implementation details live in
the individual submodules.
"""
from __future__ import annotations

from .models import AvatarSessionHandle, LiveAvatarConfig, LiveKitRoomTokens

__all__ = [
    "AvatarSessionHandle",
    "LiveAvatarConfig",
    "LiveKitRoomTokens",
]
