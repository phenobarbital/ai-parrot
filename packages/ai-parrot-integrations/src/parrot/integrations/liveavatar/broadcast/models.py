"""Broadcast data contracts (FEAT-537 — Module 2 foundation).

Implements spec §2 "Data Models" of
``sdd/specs/voicebot-multiroom-heygen-avatar.spec.md``.

These are **new** contracts: one Nova VoiceBot conversation fanned out to up to
ten receiving browsers through a single LiveKit room, with a server-enforced
moderator and a single exclusive speaking floor.

The single most important invariant in this module is the split between:

* :class:`BroadcastDescriptor` — the full server-side record.  It may reference
  a vendor session id for audit, but it never holds a token, secret, publisher
  JWT, ``ws_url`` or worker address.
* :class:`BroadcastPublicState` — the **only** projection a browser may ever
  receive.  A ``model_validator`` fails the model at construction time if any
  of its own field names looks credential-bearing, so a future field that leaks
  breaks loudly in every test rather than silently in production (AC3).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from parrot.core.ws_auth import AuthenticatedUser
from parrot.integrations.liveavatar.models import LiveKitRoomTokens

# ── Operational constants (spec §2 "Ownership, admission and cleanup") ──────

#: Hard ceiling on receiving browsers, counting the moderator and the current
#: speaker.  Enforced by application reservations, never by LiveKit's own
#: ``max_participants`` (publishers do not consume viewer seats).
MAX_VIEWERS: int = 10

#: A ``pending`` broadcast with no admission expires after this many seconds
#: without ever allocating media resources.
PENDING_TTL_S: int = 60

#: Producer-ownership lease expiry and its renewal period.
OWNER_LEASE_TTL_S: int = 15
OWNER_RENEW_S: int = 5

#: Participant control-socket heartbeat period and expiry.
CONTROL_HEARTBEAT_S: int = 5
CONTROL_EXPIRY_S: int = 15

#: How long a sanitized terminal state stays readable by polling clients.
TERMINAL_RETENTION_S: int = 300

#: Viewer LiveKit credentials are only valid for admission this long.  Expiry
#: is not revocation — an already-joined participant stays connected.
VIEWER_CREDENTIAL_TTL_S: int = 60

#: Maximum time the producer may take to acknowledge a floor-switch barrier
#: before the floor is left idle with a retryable error (spec §2 moderation).
HANDOFF_BARRIER_TIMEOUT_S: float = 3.0

#: Deadline for LiveAvatar readiness before the broadcast selects audio-only.
AVATAR_STARTUP_DEADLINE_S: float = 15.0

#: Two seconds of 24 kHz mono PCM16 — the bounded output queue budget.
MAX_QUEUED_PCM_BYTES: int = 96_000

#: Nova wire formats.  Input is microphone-side, output is bot-side.
INPUT_SAMPLE_RATE: int = 16_000
OUTPUT_SAMPLE_RATE: int = 24_000

_BYTES_PER_SAMPLE: int = 2

#: Field-name fragments that must never appear on a browser-facing projection.
_FORBIDDEN_PUBLIC_FIELD_FRAGMENTS: tuple[str, ...] = (
    "token",
    "secret",
    "ws_url",
    "api_key",
    "worker",
    "credential",
    "password",
)

_MAX_DISPLAY_NAME_CHARS: int = 64
_FALLBACK_DISPLAY_NAME: str = "participant"


def _utcnow() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _safe_display_name(raw: Optional[str]) -> str:
    """Normalise a participant display name to a safe, bounded label.

    Args:
        raw: Untrusted or missing display name.

    Returns:
        A stripped name of at most 64 characters, or ``"participant"`` when the
        input is empty after stripping.
    """
    cleaned = (raw or "").strip()[:_MAX_DISPLAY_NAME_CHARS]
    return cleaned or _FALLBACK_DISPLAY_NAME


# ── Enums ──────────────────────────────────────────────────────────────────


class BroadcastState(str, Enum):
    """Lifecycle of one broadcast.

    ``pending → starting → avatar | audio_only → stopping → ended``.  The
    ``avatar → audio_only`` edge is one-way: fallback is sticky for the
    lifetime of the broadcast.  A fatal Nova, LiveKit or ownership failure
    routes through cleanup to ``failed``.
    """

    PENDING = "pending"
    STARTING = "starting"
    AVATAR = "avatar"
    AUDIO_ONLY = "audio_only"
    STOPPING = "stopping"
    ENDED = "ended"
    FAILED = "failed"


class FloorState(str, Enum):
    """State of the single exclusive speaking floor.

    ``switching`` is the barrier state: the previous speaker has been cleared
    and the floor epoch incremented, but no new speaker is permitted yet.
    """

    IDLE = "idle"
    SWITCHING = "switching"
    GRANTED = "granted"


class LeaseState(str, Enum):
    """State of one viewer seat reservation."""

    PENDING = "pending"
    ACTIVE = "active"
    LEAVING = "leaving"


class BroadcastReason(str, Enum):
    """Sanitized reason codes safe to return to any admitted participant.

    These are the *only* failure/rejection strings that cross the API boundary;
    vendor error text, stack traces and internal addresses never do.
    """

    VIEWER_LIMIT_REACHED = "viewer_limit_reached"
    SPEAKER_CONNECTION_EXISTS = "speaker_connection_exists"
    FLOOR_NOT_GRANTED = "floor_not_granted"
    STALE_FLOOR_EPOCH = "stale_floor_epoch"
    STALE_VERSION = "stale_version"
    AVATAR_STARTUP_TIMEOUT = "avatar_startup_timeout"
    AVATAR_CONTROL_LOST = "avatar_control_lost"
    AVATAR_TRACK_LOST = "avatar_track_lost"
    NOVA_FAILURE = "nova_failure"
    LIVEKIT_FAILURE = "livekit_failure"
    OWNER_LOST = "owner_lost"
    STOPPED_BY_MODERATOR = "stopped_by_moderator"
    AUDIENCE_EMPTY = "audience_empty"
    PENDING_EXPIRED = "pending_expired"


# ── Participant-scoped models ──────────────────────────────────────────────


class ParticipantPrincipal(BaseModel):
    """Scoped authenticated principal every broadcast operation is checked against.

    The existing :class:`~parrot.core.ws_auth.AuthenticatedUser` carries only
    ``user_id``/``username``/``email``/``roles`` — it has no tenant or agent
    scope.  This model adds that scope, which the HTTP/WS resolver supplies
    from trusted server state (never from a client-supplied field).

    A valid principal is necessary but **not** sufficient for any moderated
    operation: moderator and speaker authority derive from admission and
    grants, not from roles.

    Attributes:
        user_id: Stable authenticated user identifier.
        tenant_id: Tenant the operation is scoped to.
        agent_id: Agent the broadcast belongs to.
        display_name: Safe, bounded label shown to other participants.
        roles: Roles carried by the authenticated session.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(..., description="Stable authenticated user identifier.")
    tenant_id: str = Field(..., description="Tenant scope of this principal.")
    agent_id: str = Field(..., description="Agent the broadcast belongs to.")
    display_name: str = Field(
        default=_FALLBACK_DISPLAY_NAME,
        description="Safe bounded label shown to other participants.",
    )
    roles: List[str] = Field(
        default_factory=list,
        description="Roles from the authenticated session (never floor authority).",
    )

    @field_validator("display_name")
    @classmethod
    def _sanitise_display_name(cls, value: Optional[str]) -> str:
        """Bound and strip the display name, falling back to a safe label."""
        return _safe_display_name(value)

    @classmethod
    def from_authenticated_user(
        cls,
        user: AuthenticatedUser,
        *,
        tenant_id: str,
        agent_id: str,
    ) -> "ParticipantPrincipal":
        """Build a scoped principal from an authenticated WebSocket/HTTP user.

        The tenant and agent scope are supplied by the caller from trusted
        server-side resolution — deliberately not read off the token payload.

        Args:
            user: The authenticated user from ``parrot.core.ws_auth``.
            tenant_id: Server-resolved tenant scope.
            agent_id: Server-resolved agent scope.

        Returns:
            A scoped :class:`ParticipantPrincipal`.
        """
        return cls(
            user_id=user.user_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            display_name=_safe_display_name(user.username or user.user_id),
            roles=list(user.roles),
        )


class HandRequest(BaseModel):
    """One outstanding raise-hand request.

    Raising a hand never captures microphone audio and never grants permission
    to speak.  Requests are ordered by the server-assigned ``sequence``, and
    repeated requests from the same lease are idempotent.

    Attributes:
        lease_id: Lease of the requesting participant (also its display ID).
        display_name: Safe label from trusted profile data.
        sequence: Monotonic server sequence establishing queue order.
        requested_at: Server timestamp of the first (idempotent) request.
    """

    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(..., description="Lease of the requesting participant.")
    display_name: str = Field(
        default=_FALLBACK_DISPLAY_NAME,
        description="Safe bounded label from trusted profile data.",
    )
    sequence: int = Field(..., ge=0, description="Monotonic server sequence establishing queue order.")
    requested_at: datetime = Field(default_factory=_utcnow, description="Server timestamp of the request.")

    @field_validator("display_name")
    @classmethod
    def _sanitise_display_name(cls, value: Optional[str]) -> str:
        """Bound and strip the display name, falling back to a safe label."""
        return _safe_display_name(value)


class ViewerLease(BaseModel):
    """One reserved receiving seat, held from admission until confirmed release.

    A lease reserves one of :data:`MAX_VIEWERS` slots **even before** the
    browser connects any media, so pending admissions cannot over-admit the
    room.  Slots are released on confirmed disconnect or removal, never on an
    HTTP heartbeat timeout alone.

    Attributes:
        lease_id: Unique lease identifier; also this participant's display ID.
        principal: The scoped principal that owns this lease.
        livekit_identity: Unique LiveKit identity, independent of ``user_id``
            (identity reuse would evict the previous participant).
        state: Reservation state.
        credential_expires_at: When the issued admission credential stops being
            usable to join.  Not a revocation of an existing connection.
        admission_deadline: When an unconfirmed pending seat may be reclaimed.
        confirmed: Whether the participant's presence has been confirmed
            against LiveKit rather than merely asserted by the client.
        admission_sequence: Server admission order; the earliest sequence wins
            moderator election.
        last_control_heartbeat: Last authenticated control-socket heartbeat.
        speaker_socket_id: Identifier of the single bound microphone socket, if
            this lease currently holds the floor.
    """

    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(..., description="Unique lease identifier / display ID.")
    principal: ParticipantPrincipal = Field(..., description="Scoped principal owning this lease.")
    livekit_identity: str = Field(..., description="Unique LiveKit participant identity for this browser.")
    state: LeaseState = Field(default=LeaseState.PENDING, description="Seat reservation state.")
    credential_expires_at: Optional[datetime] = Field(
        default=None, description="Admission-credential expiry (not a revocation)."
    )
    admission_deadline: Optional[datetime] = Field(
        default=None, description="When an unconfirmed pending seat may be reclaimed."
    )
    confirmed: bool = Field(default=False, description="Presence confirmed against LiveKit.")
    admission_sequence: int = Field(..., ge=0, description="Server admission order (earliest wins election).")
    last_control_heartbeat: Optional[datetime] = Field(
        default=None, description="Last authenticated control-socket heartbeat."
    )
    speaker_socket_id: Optional[str] = Field(
        default=None, description="Bound microphone socket id while holding the floor."
    )


# ── Public projection ──────────────────────────────────────────────────────


class BroadcastPublicState(BaseModel):
    """Scoped public projection of a broadcast — the only shape a browser sees.

    Carries no vendor token, API secret, worker credential, worker address or
    internal tenant data.  Participants are referred to by **lease id** (their
    display ID), never by user id or email.

    Every browser observes ``version`` monotonically and treats the server as
    the sole authority; a state older than three seconds must mute output and
    disable capture (spec §2).

    Attributes:
        broadcast_id: Public broadcast identifier.
        state: Current lifecycle state.
        version: Monotonic public version; moderator controls compare-and-set
            against it.  Lease heartbeats do not bump it.
        output_epoch: Monotonic output generation; browsers reject events from
            an older epoch.
        media_ready: Whether room credentials and media are available.
        selected_identity: Publisher identity currently selected for playback.
        selected_audio_track_id: Track id of the authoritative audio source.
        selected_video_track_id: Track id of the avatar video, when present.
        viewer_count: Reserved seats in use, including moderator and speaker.
        max_viewers: Seat ceiling for this broadcast.
        moderator_display_id: Lease id of the current moderator.
        speaker_display_id: Lease id of the participant holding the floor.
        floor_state: Current floor state.
        floor_epoch: Monotonic floor generation; stale-epoch audio is rejected.
        hand_requests: Ordered raised-hand queue.
        reason: Sanitized reason code for the current or terminal state.
    """

    model_config = ConfigDict(extra="forbid")

    broadcast_id: str = Field(..., description="Public broadcast identifier.")
    state: BroadcastState = Field(..., description="Current lifecycle state.")
    version: int = Field(..., ge=0, description="Monotonic public state version.")
    output_epoch: int = Field(..., ge=0, description="Monotonic output generation.")
    media_ready: bool = Field(..., description="Whether room credentials and media are available.")
    selected_identity: Optional[str] = Field(default=None, description="Publisher identity selected for playback.")
    selected_audio_track_id: Optional[str] = Field(default=None, description="Authoritative audio track id.")
    selected_video_track_id: Optional[str] = Field(default=None, description="Avatar video track id, when present.")
    viewer_count: int = Field(..., ge=0, description="Reserved seats in use (moderator and speaker included).")
    max_viewers: int = Field(..., ge=1, le=MAX_VIEWERS, description="Seat ceiling for this broadcast.")
    moderator_display_id: Optional[str] = Field(default=None, description="Lease id of the current moderator.")
    speaker_display_id: Optional[str] = Field(
        default=None, description="Lease id of the participant holding the floor."
    )
    floor_state: FloorState = Field(..., description="Current floor state.")
    floor_epoch: int = Field(..., ge=0, description="Monotonic floor generation.")
    hand_requests: List[HandRequest] = Field(default_factory=list, description="Ordered raised-hand queue.")
    reason: Optional[BroadcastReason] = Field(default=None, description="Sanitized reason code for the current state.")

    @model_validator(mode="after")
    def _forbid_credential_bearing_fields(self) -> "BroadcastPublicState":
        """Fail loudly if this projection ever grows a credential-like field.

        ``extra="forbid"`` stops a *caller* from smuggling a token in; this
        check stops a future *maintainer* from declaring one.  It runs on the
        class's declared fields, so every test that builds a public state is
        also a regression test for AC3.

        Returns:
            ``self``, unchanged.

        Raises:
            ValueError: If a declared field name looks credential-bearing.
        """
        offending = [
            name
            for name in type(self).model_fields
            if any(fragment in name.lower() for fragment in _FORBIDDEN_PUBLIC_FIELD_FRAGMENTS)
        ]
        if offending:
            raise ValueError("BroadcastPublicState must not expose credential-bearing fields: " f"{sorted(offending)}")
        return self


class ViewerJoinResponse(BaseModel):
    """Admission response returned only to the principal that owns the lease.

    Carries the subscribe-only ``client_token`` and nothing else from
    :class:`~parrot.integrations.liveavatar.models.LiveKitRoomTokens` — the
    publish-capable ``agent_token`` never leaves the server.

    Attributes:
        public_state: The current public projection.
        lease_id: The admitted lease.
        livekit_url: Room WebSocket URL.
        room: Room name.
        client_token: Subscribe-only JWT, unique to this browser.
        expires_at: Admission-credential expiry.
    """

    model_config = ConfigDict(extra="forbid")

    public_state: BroadcastPublicState = Field(..., description="Current public projection of the broadcast.")
    lease_id: str = Field(..., description="The admitted lease id.")
    livekit_url: str = Field(..., description="LiveKit room WebSocket URL.")
    room: str = Field(..., description="LiveKit room name.")
    client_token: str = Field(..., description="Subscribe-only JWT unique to this browser.")
    expires_at: datetime = Field(..., description="Admission-credential expiry.")

    @classmethod
    def from_tokens(
        cls,
        tokens: LiveKitRoomTokens,
        *,
        public_state: BroadcastPublicState,
        lease_id: str,
        expires_at: datetime,
    ) -> "ViewerJoinResponse":
        """Project room tokens down to the browser-safe subset.

        This is the only sanctioned path from :class:`LiveKitRoomTokens` to a
        client response; it structurally drops ``agent_token``.

        Args:
            tokens: Freshly minted room tokens for this viewer's identity.
            public_state: Current public projection.
            lease_id: The admitted lease id.
            expires_at: Admission-credential expiry.

        Returns:
            A browser-safe :class:`ViewerJoinResponse`.
        """
        return cls(
            public_state=public_state,
            lease_id=lease_id,
            livekit_url=tokens.livekit_url,
            room=tokens.room,
            client_token=tokens.client_token,
            expires_at=expires_at,
        )


# ── Descriptor ─────────────────────────────────────────────────────────────


class BroadcastDescriptor(BaseModel):
    """Full server-side record of one broadcast.

    Persisted (namespaced by tenant and broadcast id) so any worker can serve
    participants or request a stop, while live SDK objects stay on the process
    that owns the producer.  Never holds audio, AWS credentials or LiveAvatar
    access tokens — ``liveavatar_session_id`` is an audit identifier only.

    Attributes:
        broadcast_id: Unique broadcast identifier.
        tenant_id: Owning tenant.
        agent_id: Agent this broadcast speaks for.
        creator_user_id: Who created it.  Creation does **not** confer
            moderator authority — the first successful admission does.
        moderator_lease_id: Lease of the current moderator.
        speaker_lease_id: Lease permitted to send microphone audio.
        floor_epoch: Monotonic floor generation.
        floor_state: Current floor state.
        hand_requests: Ordered raised-hand queue.
        voice_session_id: Stable conversation/session key for the shared
            VoiceBot memory namespace.
        room_name: Allocated LiveKit room.
        owner_worker_id: Worker holding the producer lease.
        owner_epoch: Monotonic ownership generation used for fencing.
        version: Monotonic public version for compare-and-set.
        state: Lifecycle state.
        output_epoch: Monotonic output generation.
        avatar_identity: LiveKit identity of the avatar publisher.
        direct_identity: LiveKit identity of the distinct direct publisher.
        selected_audio_track_id: Authoritative audio track id.
        selected_video_track_id: Avatar video track id, when present.
        max_viewers: Seat ceiling (1–10).
        admission_sequence: Next server admission sequence to hand out.
        created_at: Creation timestamp.
        updated_at: Last mutation timestamp.
        started_at: When media initialisation began.
        ended_at: When the broadcast reached a terminal state.
        failure_reason: Sanitized reason code, if any.
        liveavatar_session_id: Vendor session id for audit only, never a token.
    """

    model_config = ConfigDict(extra="forbid")

    broadcast_id: str = Field(..., description="Unique broadcast identifier.")
    tenant_id: str = Field(..., description="Owning tenant.")
    agent_id: str = Field(..., description="Agent this broadcast speaks for.")
    creator_user_id: str = Field(..., description="Creator; confers no moderator authority.")

    moderator_lease_id: Optional[str] = Field(default=None, description="Lease of the current moderator.")
    speaker_lease_id: Optional[str] = Field(default=None, description="Lease permitted to send microphone audio.")
    floor_epoch: int = Field(default=0, ge=0, description="Monotonic floor generation.")
    floor_state: FloorState = Field(default=FloorState.IDLE, description="Current floor state.")
    hand_requests: List[HandRequest] = Field(default_factory=list, description="Ordered raised-hand queue.")

    voice_session_id: Optional[str] = Field(default=None, description="Stable conversation key for shared bot memory.")
    room_name: Optional[str] = Field(default=None, description="Allocated LiveKit room.")

    owner_worker_id: Optional[str] = Field(default=None, description="Worker holding the producer lease.")
    owner_epoch: int = Field(default=0, ge=0, description="Monotonic ownership generation used for fencing.")

    version: int = Field(default=0, ge=0, description="Monotonic public version for compare-and-set.")
    state: BroadcastState = Field(default=BroadcastState.PENDING, description="Lifecycle state.")
    output_epoch: int = Field(default=0, ge=0, description="Monotonic output generation.")

    avatar_identity: Optional[str] = Field(default=None, description="LiveKit identity of the avatar publisher.")
    direct_identity: Optional[str] = Field(default=None, description="LiveKit identity of the direct audio publisher.")
    selected_audio_track_id: Optional[str] = Field(default=None, description="Authoritative audio track id.")
    selected_video_track_id: Optional[str] = Field(default=None, description="Avatar video track id, when present.")

    max_viewers: int = Field(default=MAX_VIEWERS, ge=1, le=MAX_VIEWERS, description="Seat ceiling (1–10).")
    admission_sequence: int = Field(default=0, ge=0, description="Next server admission sequence to hand out.")

    created_at: datetime = Field(default_factory=_utcnow, description="Creation timestamp.")
    updated_at: datetime = Field(default_factory=_utcnow, description="Last mutation timestamp.")
    started_at: Optional[datetime] = Field(default=None, description="When media initialisation began.")
    ended_at: Optional[datetime] = Field(default=None, description="When a terminal state was reached.")

    failure_reason: Optional[BroadcastReason] = Field(default=None, description="Sanitized reason code, if any.")
    liveavatar_session_id: Optional[str] = Field(
        default=None, description="Vendor session id for audit only — never a token."
    )

    # ── Derived helpers ────────────────────────────────────────────────

    @property
    def is_terminal(self) -> bool:
        """Whether the broadcast can no longer serve participants."""
        return self.state in (BroadcastState.ENDED, BroadcastState.FAILED)

    @property
    def selected_identity(self) -> Optional[str]:
        """Publisher identity that clients must play, per the current state.

        In ``avatar`` the avatar participant is authoritative; in
        ``audio_only`` the distinct direct publisher is.  Any other state has
        no authoritative source and browsers must stay muted.
        """
        if self.state is BroadcastState.AVATAR:
            return self.avatar_identity
        if self.state is BroadcastState.AUDIO_ONLY:
            return self.direct_identity
        return None

    def to_public_state(
        self,
        *,
        viewer_count: int = 0,
        media_ready: Optional[bool] = None,
    ) -> BroadcastPublicState:
        """Project this descriptor down to the browser-facing state.

        Viewer occupancy lives in the lease records rather than the descriptor,
        so the registry supplies it; it defaults to ``0`` for a bare
        descriptor.  ``media_ready`` is derived from the lifecycle state unless
        the caller overrides it.

        Args:
            viewer_count: Reserved seats currently in use.
            media_ready: Override for the derived readiness flag.

        Returns:
            A :class:`BroadcastPublicState` carrying no credentials.
        """
        derived_ready = self.state in (
            BroadcastState.AVATAR,
            BroadcastState.AUDIO_ONLY,
        ) and bool(self.room_name)
        return BroadcastPublicState(
            broadcast_id=self.broadcast_id,
            state=self.state,
            version=self.version,
            output_epoch=self.output_epoch,
            media_ready=derived_ready if media_ready is None else media_ready,
            selected_identity=self.selected_identity,
            selected_audio_track_id=self.selected_audio_track_id,
            selected_video_track_id=self.selected_video_track_id,
            viewer_count=viewer_count,
            max_viewers=self.max_viewers,
            moderator_display_id=self.moderator_lease_id,
            speaker_display_id=self.speaker_lease_id,
            floor_state=self.floor_state,
            floor_epoch=self.floor_epoch,
            hand_requests=list(self.hand_requests),
            reason=self.failure_reason,
        )


# ── Audio frame ────────────────────────────────────────────────────────────


class BroadcastAudioFrame(BaseModel):
    """One fenced block of generated PCM on its way to the selected sink.

    Every frame carries the full fencing tuple so a frame produced before a
    handoff, an ownership change or a fallback cutover can be discarded rather
    than played: stale ``owner_epoch``, ``floor_epoch``, ``turn_id`` or
    ``output_epoch`` all disqualify it.

    Attributes:
        owner_epoch: Ownership generation the frame was produced under.
        speaker_lease_id: Authenticated lease whose turn produced it.
        floor_epoch: Floor generation the input turn was admitted under.
        turn_id: Identifier of the producing turn.
        output_epoch: Output generation the frame belongs to.
        sequence: Monotonic per-turn frame sequence.
        pcm: Raw 16-bit little-endian mono PCM at
            :data:`OUTPUT_SAMPLE_RATE`.
        sample_count: Number of samples in ``pcm``.
    """

    model_config = ConfigDict(extra="forbid")

    owner_epoch: int = Field(..., ge=0, description="Ownership generation.")
    speaker_lease_id: str = Field(..., description="Authenticated lease whose turn produced this frame.")
    floor_epoch: int = Field(..., ge=0, description="Floor generation of the input.")
    turn_id: str = Field(..., description="Identifier of the producing turn.")
    output_epoch: int = Field(..., ge=0, description="Output generation.")
    sequence: int = Field(..., ge=0, description="Monotonic per-turn frame sequence.")
    pcm: bytes = Field(..., description="Raw 16-bit LE mono PCM at 24 kHz.")
    sample_count: int = Field(..., ge=1, description="Number of samples in ``pcm``.")

    @field_validator("pcm")
    @classmethod
    def _validate_pcm(cls, value: bytes) -> bytes:
        """Reject empty, misaligned or oversized PCM blocks.

        Args:
            value: Candidate PCM bytes.

        Returns:
            The validated bytes.

        Raises:
            ValueError: If the block is empty, not 16-bit aligned, or exceeds
                the two-second queue budget.
        """
        if not value:
            raise ValueError("pcm must not be empty")
        if len(value) % _BYTES_PER_SAMPLE != 0:
            raise ValueError("pcm must be 16-bit aligned")
        if len(value) > MAX_QUEUED_PCM_BYTES:
            raise ValueError(f"pcm exceeds the {MAX_QUEUED_PCM_BYTES}-byte bounded-queue budget")
        return value

    @model_validator(mode="after")
    def _validate_sample_count(self) -> "BroadcastAudioFrame":
        """Ensure ``sample_count`` agrees with the PCM length.

        Returns:
            ``self``, unchanged.

        Raises:
            ValueError: If the declared sample count does not match the bytes.
        """
        expected = len(self.pcm) // _BYTES_PER_SAMPLE
        if self.sample_count != expected:
            raise ValueError(f"sample_count {self.sample_count} does not match pcm length " f"({expected} samples)")
        return self

    def is_current(
        self,
        *,
        owner_epoch: int,
        floor_epoch: int,
        output_epoch: int,
        turn_id: Optional[str] = None,
    ) -> bool:
        """Whether this frame is still valid against the live fencing tuple.

        Args:
            owner_epoch: Current ownership generation.
            floor_epoch: Current floor generation.
            output_epoch: Current output generation.
            turn_id: Current turn id, when a turn is in flight.

        Returns:
            ``True`` only when every epoch matches and the turn (if given) is
            the producing turn.
        """
        if self.owner_epoch != owner_epoch or self.floor_epoch != floor_epoch or self.output_epoch != output_epoch:
            return False
        return turn_id is None or self.turn_id == turn_id


def public_payload(state: BroadcastPublicState) -> dict[str, Any]:
    """Serialise a public state for the wire in JSON-safe form.

    Args:
        state: The projection to serialise.

    Returns:
        A JSON-serialisable dict (enums as values, datetimes as ISO strings).
    """
    return state.model_dump(mode="json")
