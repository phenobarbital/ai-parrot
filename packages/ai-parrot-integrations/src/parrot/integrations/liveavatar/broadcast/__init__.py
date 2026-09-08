"""Moderated multi-browser broadcast for the Nova VoiceBot avatar (FEAT-537).

One Nova VoiceBot conversation, one LiveAvatar LITE generation session and one
LiveKit room, fanned out to up to ten receiving browsers.  The first admitted
participant becomes moderator and can grant a single exclusive speaking floor
to another participant.

Public re-exports for ``parrot.integrations.liveavatar.broadcast``.
Implementation lives in the individual submodules.

``RedisBroadcastRegistry`` is exported **lazily** through ``__getattr__``: the
``redis`` driver is an optional dependency (the ``broadcast`` extra), and
importing this package must keep working — for the models, the in-memory
registry and every deterministic unit test — on an installation that has no
``redis`` at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
from .errors import (
    BroadcastError,
    BroadcastTerminal,
    FloorNotGranted,
    IdentityTombstoned,
    NotModerator,
    NotOwner,
    NotSpeaker,
    SpeakerConnectionExists,
    StaleFloorEpoch,
    StaleVersion,
    ViewerLimitReached,
)
from .floor import FloorCoordinator, HandoffResult
from .service import (
    BroadcastNotReady,
    BroadcastService,
    ReconcileReport,
)
from .session import BroadcastSession
from .voice_relay import BroadcastVoiceSession
from .worker_transport import (
    LocalSpeakerInput,
    RemoteSpeakerInput,
    SpeakerInput,
    WorkerAddressRegistry,
    WorkerRelayServer,
)
from .registry import (
    Admission,
    BroadcastRegistry,
    ExpiryEvent,
    ExpiryKind,
    InMemoryBroadcastRegistry,
    ReleaseOutcome,
    validate_audio_authority,
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
    "Admission",
    "BroadcastAudioFrame",
    "BroadcastDescriptor",
    "BroadcastError",
    "BroadcastPublicState",
    "BroadcastReason",
    "BroadcastRegistry",
    "BroadcastSession",
    "BroadcastState",
    "BroadcastTerminal",
    "ExpiryEvent",
    "ExpiryKind",
    "FloorNotGranted",
    "FloorState",
    "HandRequest",
    "IdentityTombstoned",
    "InMemoryBroadcastRegistry",
    "LeaseState",
    "NotModerator",
    "NotOwner",
    "NotSpeaker",
    "ParticipantPrincipal",
    "ReleaseOutcome",
    "SpeakerConnectionExists",
    "StaleFloorEpoch",
    "StaleVersion",
    "ViewerJoinResponse",
    "ViewerLease",
    "ViewerLimitReached",
    "RedisBroadcastRegistry",
    "BroadcastNotReady",
    "BroadcastService",
    "BroadcastVoiceSession",
    "FloorCoordinator",
    "HandoffResult",
    "LocalSpeakerInput",
    "ReconcileReport",
    "RemoteSpeakerInput",
    "SpeakerInput",
    "WorkerAddressRegistry",
    "WorkerRelayServer",
    "public_payload",
    "validate_audio_authority",
]

if TYPE_CHECKING:  # pragma: no cover — import-time typing only
    from .redis_registry import RedisBroadcastRegistry


def __getattr__(name: str) -> Any:
    """Resolve the optional Redis-backed registry on first access.

    Args:
        name: Attribute being looked up.

    Returns:
        The requested attribute.

    Raises:
        AttributeError: For any name this package does not export.
    """
    if name == "RedisBroadcastRegistry":
        from .redis_registry import RedisBroadcastRegistry as _RedisBroadcastRegistry

        return _RedisBroadcastRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
