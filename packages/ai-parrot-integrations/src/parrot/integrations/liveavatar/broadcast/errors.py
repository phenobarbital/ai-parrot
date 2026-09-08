"""Typed broadcast errors (FEAT-537 — Module 2).

Every error carries an optional **sanitized** :class:`BroadcastReason` — the
only failure string that may cross the API boundary — plus the HTTP status the
spec §2 API table assigns to it, so the transport layer never has to re-derive
the mapping from an exception's message.

Authorization failures (:class:`NotModerator`, :class:`NotSpeaker`) carry no
public reason at all: they map to a bare ``403`` and must not tell the caller
who the moderator or speaker actually is.
"""

from __future__ import annotations

from typing import ClassVar, Optional

from parrot.integrations.liveavatar.broadcast.models import BroadcastReason


class BroadcastError(Exception):
    """Base class for every broadcast-registry failure.

    Args:
        reason: Sanitized public reason code.  Falls back to the subclass's
            :attr:`default_reason`; may legitimately be ``None`` for pure
            authorization failures.
        message: Optional operator-facing detail.  Never returned to a client
            verbatim — the client sees :attr:`reason` and :attr:`status`.

    Attributes:
        reason: Sanitized public reason code, or ``None``.
        status: HTTP status this error maps to (spec §2 API table).
    """

    default_reason: ClassVar[Optional[BroadcastReason]] = None
    status: ClassVar[int] = 409

    def __init__(
        self,
        reason: Optional[BroadcastReason] = None,
        *,
        message: Optional[str] = None,
    ) -> None:
        self.reason: Optional[BroadcastReason] = reason or self.default_reason
        detail = message or (self.reason.value if self.reason else self.__class__.__name__)
        super().__init__(detail)


class ViewerLimitReached(BroadcastError):
    """All :data:`~.models.MAX_VIEWERS` seats are reserved (HTTP 409)."""

    default_reason: ClassVar[Optional[BroadcastReason]] = BroadcastReason.VIEWER_LIMIT_REACHED
    status: ClassVar[int] = 409


class IdentityTombstoned(BroadcastError):
    """A departed browser's LiveKit identity is still tombstoned (HTTP 409).

    Spec §2: an explicit leave keeps an identity tombstone through token
    validity and retains the reservation until reuse cannot over-admit the
    room.  Re-entry with the same identity is refused; the browser must obtain
    a fresh lease and a fresh identity.

    Publicly indistinguishable from :class:`ViewerLimitReached` on purpose —
    both mean "no seat is available to you right now" and neither reveals who
    else is in the room.
    """

    default_reason: ClassVar[Optional[BroadcastReason]] = BroadcastReason.VIEWER_LIMIT_REACHED
    status: ClassVar[int] = 409


class BroadcastTerminal(BroadcastError):
    """The broadcast has ended or failed and cannot be rejoined (HTTP 410)."""

    status: ClassVar[int] = 410


class StaleVersion(BroadcastError):
    """A compare-and-set moderator control lost the race (HTTP 409)."""

    default_reason: ClassVar[Optional[BroadcastReason]] = BroadcastReason.STALE_VERSION
    status: ClassVar[int] = 409


class FloorNotGranted(BroadcastError):
    """The participant does not hold the speaking floor (HTTP 403)."""

    default_reason: ClassVar[Optional[BroadcastReason]] = BroadcastReason.FLOOR_NOT_GRANTED
    status: ClassVar[int] = 403


class StaleFloorEpoch(BroadcastError):
    """Input or a barrier acknowledgement arrived for a superseded floor epoch."""

    default_reason: ClassVar[Optional[BroadcastReason]] = BroadcastReason.STALE_FLOOR_EPOCH
    status: ClassVar[int] = 409


class SpeakerConnectionExists(BroadcastError):
    """A different microphone socket is already bound to the floor (HTTP 409)."""

    default_reason: ClassVar[Optional[BroadcastReason]] = BroadcastReason.SPEAKER_CONNECTION_EXISTS
    status: ClassVar[int] = 409


class NotModerator(BroadcastError):
    """The caller is not the current moderator (HTTP 403, no public reason)."""

    status: ClassVar[int] = 403


class NotSpeaker(BroadcastError):
    """The caller is not the current speaker (HTTP 403, no public reason)."""

    status: ClassVar[int] = 403


class NotOwner(BroadcastError):
    """The caller's producer-ownership lease is expired or was fenced."""

    default_reason: ClassVar[Optional[BroadcastReason]] = BroadcastReason.OWNER_LOST
    status: ClassVar[int] = 409


__all__ = [
    "BroadcastError",
    "BroadcastTerminal",
    "FloorNotGranted",
    "IdentityTombstoned",
    "NotModerator",
    "NotOwner",
    "NotSpeaker",
    "SpeakerConnectionExists",
    "StaleFloorEpoch",
    "StaleVersion",
    "ViewerLimitReached",
]
