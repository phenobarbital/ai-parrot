"""Moderated multi-browser broadcast for the Nova VoiceBot avatar (FEAT-537).

One Nova VoiceBot conversation, one LiveAvatar LITE generation session and one
LiveKit room, fanned out to up to ten receiving browsers.  The first admitted
participant becomes moderator and can grant a single exclusive speaking floor
to another participant.

Public re-exports for ``parrot.integrations.liveavatar.broadcast``.
Implementation lives in the individual submodules.
"""
from __future__ import annotations

from .models import (
    AVATAR_STARTUP_DEADLINE_S,
    CONTROL_EXPIRY_S,
    CONTROL_HEARTBEAT_S,
    HANDOFF_BARRIER_TIMEOUT_S,
    INPUT_SAMPLE_RATE,
    MAX_QUEUED_PCM_BYTES,
    MAX_VIEWERS,
    OUTPUT_SAMPLE_RATE,
    OWNER_LEASE_TTL_S,
    OWNER_RENEW_S,
    PENDING_TTL_S,
    TERMINAL_RETENTION_S,
    VIEWER_CREDENTIAL_TTL_S,
    BroadcastAudioFrame,
    BroadcastDescriptor,
    BroadcastPublicState,
    BroadcastReason,
    BroadcastState,
    FloorState,
    HandRequest,
    LeaseState,
    ParticipantPrincipal,
    ViewerJoinResponse,
    ViewerLease,
    public_payload,
)

__all__ = [
    "AVATAR_STARTUP_DEADLINE_S",
    "CONTROL_EXPIRY_S",
    "CONTROL_HEARTBEAT_S",
    "HANDOFF_BARRIER_TIMEOUT_S",
    "INPUT_SAMPLE_RATE",
    "MAX_QUEUED_PCM_BYTES",
    "MAX_VIEWERS",
    "OUTPUT_SAMPLE_RATE",
    "OWNER_LEASE_TTL_S",
    "OWNER_RENEW_S",
    "PENDING_TTL_S",
    "TERMINAL_RETENTION_S",
    "VIEWER_CREDENTIAL_TTL_S",
    "BroadcastAudioFrame",
    "BroadcastDescriptor",
    "BroadcastPublicState",
    "BroadcastReason",
    "BroadcastState",
    "FloorState",
    "HandRequest",
    "LeaseState",
    "ParticipantPrincipal",
    "ViewerJoinResponse",
    "ViewerLease",
    "public_payload",
]
