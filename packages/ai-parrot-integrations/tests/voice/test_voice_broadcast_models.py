"""Unit tests for the FEAT-537 broadcast data contracts (TASK-2951).

Covers spec §2 "Data Models" and the AC3 invariant that the public projection
never carries a credential.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest
from pydantic import ValidationError

from parrot.core.ws_auth import AuthenticatedUser
from parrot.integrations.liveavatar.broadcast import (
    MAX_QUEUED_PCM_BYTES,
    MAX_VIEWERS,
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
from parrot.integrations.liveavatar.models import LiveKitRoomTokens

_FORBIDDEN = ("token", "secret", "ws_url", "api_key", "worker", "credential")


# ── Builders ───────────────────────────────────────────────────────────────


def _principal(**kwargs: Any) -> ParticipantPrincipal:
    """Build a scoped principal with sane defaults."""
    defaults: dict[str, Any] = {
        "user_id": "user-1",
        "tenant_id": "acme",
        "agent_id": "agent-1",
        "display_name": "Ada",
    }
    defaults.update(kwargs)
    return ParticipantPrincipal(**defaults)


def _descriptor(**kwargs: Any) -> BroadcastDescriptor:
    """Build a broadcast descriptor with sane defaults."""
    defaults: dict[str, Any] = {
        "broadcast_id": "bc-1",
        "tenant_id": "acme",
        "agent_id": "agent-1",
        "creator_user_id": "user-1",
    }
    defaults.update(kwargs)
    return BroadcastDescriptor(**defaults)


def _pcm(samples: int) -> bytes:
    """Return ``samples`` samples of silent 16-bit PCM."""
    return b"\x00\x00" * samples


def _walk_keys(obj: Any) -> Iterator[str]:
    """Yield every mapping key found anywhere in a nested structure."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _walk_keys(item)


# ── Enums and constants ────────────────────────────────────────────────────


def test_state_enum_values() -> None:
    assert {state.value for state in BroadcastState} == {
        "pending",
        "starting",
        "avatar",
        "audio_only",
        "stopping",
        "ended",
        "failed",
    }


def test_floor_and_lease_enum_values() -> None:
    assert {state.value for state in FloorState} == {"idle", "switching", "granted"}
    assert {state.value for state in LeaseState} == {"pending", "active", "leaving"}


def test_reason_codes_cover_every_spec_rejection() -> None:
    values = {reason.value for reason in BroadcastReason}
    assert {
        "viewer_limit_reached",
        "speaker_connection_exists",
        "floor_not_granted",
        "stale_floor_epoch",
        "stale_version",
        "avatar_startup_timeout",
        "avatar_control_lost",
        "avatar_track_lost",
        "nova_failure",
        "livekit_failure",
        "owner_lost",
        "stopped_by_moderator",
        "audience_empty",
        "pending_expired",
    } <= values


def test_max_viewers_constant_is_ten() -> None:
    assert MAX_VIEWERS == 10


# ── Public projection / AC3 ────────────────────────────────────────────────


def test_public_state_has_no_secret_like_keys() -> None:
    descriptor = _descriptor(
        state=BroadcastState.AVATAR,
        room_name="room-1",
        avatar_identity="avatar-pub",
        direct_identity="direct-pub",
        moderator_lease_id="lease-a",
        speaker_lease_id="lease-b",
        hand_requests=[HandRequest(lease_id="lease-c", display_name="Grace", sequence=1)],
        liveavatar_session_id="vendor-session-9",
    )
    dumped = descriptor.to_public_state(viewer_count=3).model_dump()
    offending = [
        key
        for key in _walk_keys(dumped)
        if any(fragment in key.lower() for fragment in _FORBIDDEN)
    ]
    assert offending == []


def test_public_state_omits_internal_descriptor_fields() -> None:
    descriptor = _descriptor(
        owner_worker_id="worker-7",
        liveavatar_session_id="vendor-session-9",
        creator_user_id="user-secret",
    )
    dumped = descriptor.to_public_state().model_dump()
    keys = set(_walk_keys(dumped))
    assert "owner_worker_id" not in keys
    assert "owner_epoch" not in keys
    assert "liveavatar_session_id" not in keys
    assert "creator_user_id" not in keys
    assert "tenant_id" not in keys
    assert "voice_session_id" not in keys
    # Participants are identified by lease id only — never by user id.
    assert "user-secret" not in str(dumped)


def test_public_state_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        BroadcastPublicState(
            broadcast_id="bc-1",
            state=BroadcastState.PENDING,
            version=0,
            output_epoch=0,
            media_ready=False,
            viewer_count=0,
            max_viewers=MAX_VIEWERS,
            floor_state=FloorState.IDLE,
            floor_epoch=0,
            agent_token="leaked",  # type: ignore[call-arg]
        )


def test_public_payload_is_json_safe() -> None:
    payload = public_payload(_descriptor().to_public_state())
    assert payload["state"] == "pending"
    assert payload["floor_state"] == "idle"


# ── Descriptor projection semantics ────────────────────────────────────────


def test_media_ready_is_false_until_a_media_state_with_a_room() -> None:
    assert _descriptor().to_public_state().media_ready is False
    assert (
        _descriptor(state=BroadcastState.STARTING, room_name="r")
        .to_public_state()
        .media_ready
        is False
    )
    assert (
        _descriptor(state=BroadcastState.AVATAR, room_name="r")
        .to_public_state()
        .media_ready
        is True
    )
    assert (
        _descriptor(state=BroadcastState.AVATAR).to_public_state().media_ready is False
    )


def test_selected_identity_follows_the_output_mode() -> None:
    kwargs = {"avatar_identity": "avatar-pub", "direct_identity": "direct-pub"}
    assert _descriptor(state=BroadcastState.AVATAR, **kwargs).selected_identity == (
        "avatar-pub"
    )
    assert _descriptor(state=BroadcastState.AUDIO_ONLY, **kwargs).selected_identity == (
        "direct-pub"
    )
    # No authoritative source outside the two media states.
    assert _descriptor(state=BroadcastState.STARTING, **kwargs).selected_identity is None
    assert _descriptor(state=BroadcastState.ENDED, **kwargs).selected_identity is None


def test_terminal_states() -> None:
    assert _descriptor(state=BroadcastState.ENDED).is_terminal is True
    assert _descriptor(state=BroadcastState.FAILED).is_terminal is True
    assert _descriptor(state=BroadcastState.AVATAR).is_terminal is False


def test_public_state_carries_display_ids_and_hand_queue() -> None:
    descriptor = _descriptor(
        moderator_lease_id="lease-a",
        speaker_lease_id="lease-b",
        floor_state=FloorState.GRANTED,
        floor_epoch=4,
        hand_requests=[
            HandRequest(lease_id="lease-c", sequence=1),
            HandRequest(lease_id="lease-d", sequence=2),
        ],
        failure_reason=BroadcastReason.AVATAR_STARTUP_TIMEOUT,
    )
    public = descriptor.to_public_state(viewer_count=4)
    assert public.moderator_display_id == "lease-a"
    assert public.speaker_display_id == "lease-b"
    assert public.floor_state is FloorState.GRANTED
    assert public.floor_epoch == 4
    assert [hand.lease_id for hand in public.hand_requests] == ["lease-c", "lease-d"]
    assert public.viewer_count == 4
    assert public.max_viewers == MAX_VIEWERS
    assert public.reason is BroadcastReason.AVATAR_STARTUP_TIMEOUT


def test_public_state_hand_queue_is_a_copy() -> None:
    descriptor = _descriptor(hand_requests=[HandRequest(lease_id="l", sequence=0)])
    public = descriptor.to_public_state()
    public.hand_requests.clear()
    assert len(descriptor.hand_requests) == 1


# ── Descriptor validation ──────────────────────────────────────────────────


def test_max_viewers_cannot_exceed_ten() -> None:
    with pytest.raises(ValidationError):
        _descriptor(max_viewers=MAX_VIEWERS + 1)


def test_max_viewers_cannot_be_zero() -> None:
    with pytest.raises(ValidationError):
        _descriptor(max_viewers=0)


def test_descriptor_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _descriptor(agent_token="leaked")


def test_epochs_cannot_be_negative() -> None:
    for field in ("floor_epoch", "owner_epoch", "output_epoch", "version"):
        with pytest.raises(ValidationError):
            _descriptor(**{field: -1})


# ── Principal / hand request sanitisation ──────────────────────────────────


def test_display_name_is_bounded_and_stripped() -> None:
    principal = _principal(display_name="  " + "x" * 200 + "  ")
    assert len(principal.display_name) == 64
    assert principal.display_name == "x" * 64


def test_blank_display_name_falls_back() -> None:
    assert _principal(display_name="   ").display_name == "participant"
    assert HandRequest(lease_id="l", display_name="", sequence=0).display_name == (
        "participant"
    )


def test_principal_from_authenticated_user_takes_scope_from_the_caller() -> None:
    user = AuthenticatedUser(
        user_id="u-1", username="Ada Lovelace", email="ada@example.com", roles=["admin"]
    )
    principal = ParticipantPrincipal.from_authenticated_user(
        user, tenant_id="acme", agent_id="agent-1"
    )
    assert principal.user_id == "u-1"
    assert principal.tenant_id == "acme"
    assert principal.agent_id == "agent-1"
    assert principal.display_name == "Ada Lovelace"
    assert principal.roles == ["admin"]


# ── Leases and admission response ──────────────────────────────────────────


def test_viewer_lease_defaults_to_pending_and_unconfirmed() -> None:
    lease = ViewerLease(
        lease_id="lease-a",
        principal=_principal(),
        livekit_identity="browser-abc",
        admission_sequence=0,
    )
    assert lease.state is LeaseState.PENDING
    assert lease.confirmed is False
    assert lease.speaker_socket_id is None


def test_viewer_join_response_drops_the_publisher_token() -> None:
    tokens = LiveKitRoomTokens(
        livekit_url="wss://livekit.example",
        room="room-1",
        client_token="viewer-jwt",
        agent_token="PUBLISHER-JWT-MUST-NOT-LEAK",
    )
    response = ViewerJoinResponse.from_tokens(
        tokens,
        public_state=_descriptor().to_public_state(),
        lease_id="lease-a",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    dumped = response.model_dump(mode="json")
    assert dumped["client_token"] == "viewer-jwt"
    assert "PUBLISHER-JWT-MUST-NOT-LEAK" not in str(dumped)
    assert "agent_token" not in set(_walk_keys(dumped))


# ── Audio frame ────────────────────────────────────────────────────────────


def _frame(**kwargs: Any) -> BroadcastAudioFrame:
    """Build a valid audio frame with overridable fields."""
    defaults: dict[str, Any] = {
        "owner_epoch": 1,
        "speaker_lease_id": "lease-a",
        "floor_epoch": 2,
        "turn_id": "turn-1",
        "output_epoch": 3,
        "sequence": 0,
        "pcm": _pcm(480),
        "sample_count": 480,
    }
    defaults.update(kwargs)
    return BroadcastAudioFrame(**defaults)


def test_audio_frame_accepts_aligned_pcm() -> None:
    frame = _frame()
    assert frame.sample_count == 480
    assert len(frame.pcm) == 960


def test_audio_frame_rejects_odd_length() -> None:
    with pytest.raises(ValidationError):
        BroadcastAudioFrame(
            owner_epoch=1,
            speaker_lease_id="l",
            floor_epoch=1,
            turn_id="t",
            output_epoch=1,
            sequence=0,
            pcm=b"\x00\x01\x02",
            sample_count=1,
        )


def test_audio_frame_rejects_empty_pcm() -> None:
    with pytest.raises(ValidationError):
        _frame(pcm=b"", sample_count=0)


def test_audio_frame_rejects_oversized_pcm() -> None:
    oversized = MAX_QUEUED_PCM_BYTES + 2
    with pytest.raises(ValidationError):
        _frame(pcm=b"\x00" * oversized, sample_count=oversized // 2)


def test_audio_frame_rejects_mismatched_sample_count() -> None:
    with pytest.raises(ValidationError):
        _frame(sample_count=479)


def test_audio_frame_is_current_only_when_every_epoch_matches() -> None:
    frame = _frame()
    assert frame.is_current(owner_epoch=1, floor_epoch=2, output_epoch=3) is True
    assert (
        frame.is_current(owner_epoch=1, floor_epoch=2, output_epoch=3, turn_id="turn-1")
        is True
    )
    assert frame.is_current(owner_epoch=9, floor_epoch=2, output_epoch=3) is False
    assert frame.is_current(owner_epoch=1, floor_epoch=9, output_epoch=3) is False
    assert frame.is_current(owner_epoch=1, floor_epoch=2, output_epoch=9) is False
    assert (
        frame.is_current(owner_epoch=1, floor_epoch=2, output_epoch=3, turn_id="other")
        is False
    )
