"""Pydantic data models for the LiveAvatar integration (FEAT-242, Phase A).

All secrets (``api_key``, ``avatar_id``) are required fields that the caller
injects from env vars — they are never defaulted in code.

Open questions deferred to owners:
  Q-video-settings: ``quality``/``encoding`` enum values are unconfirmed for
  LITE mode; kept as ``Optional[str] = None`` until the API reference is
  reviewed.
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class LiveAvatarConfig(BaseModel):
    """Configuration for the LiveAvatar LITE API.

    Attributes:
        api_key: LiveAvatar API key (env: LIVEAVATAR_API_KEY).
        avatar_id: Avatar identifier (env: LIVEAVATAR_AVATAR_ID).
        base_url: Base URL for the LiveAvatar REST API.
        is_sandbox: Use the sandbox environment (default True).
        max_session_duration: Optional maximum session duration in seconds,
            sent to ``create_session_token`` as a safety net.
        quality: LITE video_settings.quality enum value.  # TODO Q-video-settings
        encoding: LITE video_settings.encoding enum value.  # TODO Q-video-settings
    """

    api_key: str = Field(..., description="LiveAvatar API key (env: LIVEAVATAR_API_KEY)")
    avatar_id: str = Field(..., description="Avatar ID (env: LIVEAVATAR_AVATAR_ID)")
    base_url: str = Field(
        default="https://api.liveavatar.com",
        description="Base URL for the LiveAvatar REST API.",
    )
    is_sandbox: bool = Field(
        default=True,
        description="Use the sandbox environment when True (default).",
    )
    max_session_duration: Optional[int] = Field(
        default=None,
        description="Maximum session duration in seconds (safety net).",
    )
    # TODO Q-video-settings: confirm the LITE video_settings.quality / encoding
    # enum values against the LiveAvatar API reference before hardcoding them.
    quality: Optional[str] = Field(
        default=None,
        description="LITE video_settings.quality (Q-video-settings — unconfirmed).",
    )
    encoding: Optional[str] = Field(
        default=None,
        description="LITE video_settings.encoding (Q-video-settings — unconfirmed).",
    )


class LiveKitRoomTokens(BaseModel):
    """Viewer and agent JWT tokens for a LiveKit Cloud room.

    IMPORTANT: ``agent_token`` is server-side only. It must never be returned
    in any client-facing HTTP response — the frontend receives only
    ``client_token``.

    Attributes:
        livekit_url: LiveKit Cloud WebSocket URL (wss://<project>.livekit.cloud).
        room: Room name.
        client_token: Browser-viewer JWT (subscribe-only grants).
        agent_token: Avatar-participant JWT (publish grants, server-side only).
    """

    livekit_url: str = Field(..., description="LiveKit Cloud WebSocket URL.")
    room: str = Field(..., description="LiveKit room name.")
    client_token: str = Field(
        ..., description="Browser viewer JWT (subscribe-only). Safe to send to client."
    )
    agent_token: str = Field(
        ...,
        description=(
            "Avatar participant JWT (publish grants). "
            "Server-side only — NEVER expose to clients."
        ),
    )


class AvatarSessionHandle(BaseModel):
    """Runtime handle for a LiveAvatar LITE session.

    Carries all the state needed to manage an active avatar session (keep-alive,
    stop, WS connection) without re-calling the API.

    Attributes:
        session_id: ai-parrot session ID, shared with AgentChat.
        liveavatar_session_id: LiveAvatar session ID returned by the API.
        session_token: Bearer token for ``start_session``.
        ws_url: Avatar media-server WebSocket URL (server-side only).
        tenant_id: Optional tenant identifier for per-tenant opt-in gating.
        agent_name: Logical agent name (used for LiveKit room identity).
    """

    session_id: str = Field(
        ..., description="ai-parrot session ID, shared with AgentChat."
    )
    liveavatar_session_id: str = Field(
        ..., description="LiveAvatar API session ID."
    )
    session_token: str = Field(
        ..., description="Bearer token for start_session API call."
    )
    ws_url: str = Field(
        ...,
        description=(
            "Avatar media-server WebSocket URL. "
            "Server-side only — NEVER expose to clients."
        ),
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant identifier for per-tenant opt-in gating.",
    )
    agent_name: str = Field(
        ..., description="Logical agent name (used as LiveKit room identity)."
    )


# ---------------------------------------------------------------------------
# FEAT-248: FULL Mode Models
# ---------------------------------------------------------------------------


class FullModeConfig(LiveAvatarConfig):
    """FULL mode configuration (extends LITE config with voice/language fields).

    LiveAvatar FULL mode lets the avatar manage its own STT, TTS, and lip-sync.
    The ai-parrot backend only mints the session (restricted mode — no
    ``llm_configuration_id``, no ``context_id``) and calls ``avatar.speak_text``.

    Attributes:
        voice_id: Optional voice ID for the avatar persona.  When ``None`` the
            avatar uses its default voice.
        language: BCP-47 language tag for the avatar (default ``"en"``).
        interactivity_type: Session interactivity mode — either
            ``"CONVERSATIONAL"`` (default) or ``"PUSH_TO_TALK"``.
    """

    voice_id: Optional[str] = Field(
        default=None,
        description="Voice ID for the avatar persona (uses avatar default when None).",
    )
    language: str = Field(
        default="en",
        description="BCP-47 language tag for the avatar persona.",
    )
    interactivity_type: Literal["CONVERSATIONAL", "PUSH_TO_TALK"] = Field(
        default="CONVERSATIONAL",
        description="Session interactivity mode: CONVERSATIONAL or PUSH_TO_TALK.",
    )


class FullModeSessionHandle(AvatarSessionHandle):
    """Runtime handle for a LiveAvatar FULL mode session.

    Extends :class:`AvatarSessionHandle` with the LiveKit room credentials
    returned by the FULL mode ``/start`` response.

    NOTE: ``ws_url`` is inherited from :class:`AvatarSessionHandle` but is
    unused in FULL mode (LITE-only).  It is always empty in FULL mode sessions —
    this is harmless but callers should not rely on it.

    Attributes:
        livekit_url: LiveKit WebSocket URL for the browser to connect to the
            avatar-managed room.  Safe to return to the client.
        livekit_client_token: Subscribe-only browser JWT for the LiveKit room.
            Safe to return to the client.
    """

    livekit_url: str = Field(
        default="",
        description="LiveKit WebSocket URL for the browser (safe to expose to clients).",
    )
    livekit_client_token: str = Field(
        default="",
        description="Subscribe-only browser JWT for the LiveKit room (safe to expose).",
    )


class StructuredOutputMessage(BaseModel):
    """Output-bridge contract for structured ai-parrot outputs (FEAT-249, relocated).

    Structured outputs (charts, data, canvas updates, tool calls) produced
    during a voice or chat turn are published to the AgentChat UI WebSocket
    channel keyed by :attr:`session_id` — the same conversation the avatar is
    speaking.

    Originally lived in ``livekit_agent/models.py``; relocated here (§3.4) so
    Mode A/B/C structured-output delivery survives the Phase C deletion.

    Attributes:
        type: Output kind, e.g. ``"chart"`` | ``"data"`` | ``"canvas"`` |
            ``"tool_call"``.
        session_id: Conversation id used as the WebSocket channel key.
        payload: Arbitrary structured payload the AgentChat UI renders.
        turn_id: Optional identifier of the turn that produced the output.
    """

    type: str = Field(
        ...,
        description='Output kind, e.g. "chart" | "data" | "canvas" | "tool_call".',
    )
    session_id: str = Field(
        ...,
        description="Conversation id used as the WebSocket channel key.",
    )
    payload: Dict[str, Any] = Field(
        ...,
        description="Structured payload rendered by the AgentChat UI.",
    )
    turn_id: Optional[str] = Field(
        default=None,
        description="Optional id of the turn that produced this output.",
    )


