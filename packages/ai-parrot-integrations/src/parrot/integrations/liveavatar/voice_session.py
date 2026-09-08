"""VoiceAvatarSession — drive a LiveAvatar mouth from a realtime PCM stream (FEAT-245).

Thin session-lifecycle wrapper that connects a realtime PCM source (e.g. Gemini
Live's 24 kHz output) to the LiveAvatar LITE "mouth" (``AvatarWebSocket``).
No TTS, no resampling — the caller supplies ready-to-send 24 kHz mono 16-bit PCM.

Lifecycle::

    session = await VoiceAvatarSession.start(
        agent_id="my-agent",
        session_id="sess-abc",
        tenant_id="acme",          # optional
        avatar_id="custom-avatar", # optional; falls back to LIVEAVATAR_AVATAR_ID
    )
    # session_started reply → include session.viewer_credentials
    async for chunk in gemini_stream:
        if chunk.audio_data:
            await session.speak(chunk.audio_data)
        if chunk.is_complete:
            await session.finish_turn()
        if chunk.is_interrupted:
            await session.interrupt()
    await session.aclose()

Design notes
------------
- The opt-in gate (``is_avatar_enabled``) is NOT called here — that check is the
  caller's responsibility (TASK-1589).  This keeps the helper transport-only and
  independently unit-testable.
- ``aclose`` is idempotent and never raises; it is safe to call from cleanup code.
- ``mint_room_tokens`` is sync CPU work (JWT signing); it is offloaded via
  ``asyncio.to_thread``.
- The ``AvatarWebSocket`` is opened in ``start`` and held open for the session
  lifetime (NOT used as a short-lived ``async with`` block, per the FEAT-242
  keep-alive caveat at avatar.py:157-176).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Union

from parrot.integrations.liveavatar.avatar_ws import AvatarWebSocket
from parrot.integrations.liveavatar.client import LiveAvatarClient
from parrot.integrations.liveavatar.models import (
    AvatarSessionHandle,
    LiveAvatarConfig,
    LiveKitRoomTokens,
)
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager

#: Callbacks accepted by the broadcast path; both sync and async are fine.
EventCallback = Callable[[Dict[str, Any]], Union[Awaitable[None], None]]
CloseCallback = Callable[[str], Union[Awaitable[None], None]]


class AvatarStartupTimeout(RuntimeError):
    """The avatar did not become ready within the startup deadline.

    Distinct from a generic failure so the broadcast can record
    ``avatar_startup_timeout`` and fall back to audio-only rather than treating
    a slow vendor as a fatal error (spec §2: "the startup deadline selects
    ``audio_only``").
    """


class VoiceAvatarSession:
    """Drives a LiveAvatar mouth from a realtime PCM (24 kHz mono 16-bit) stream.

    Create one instance per voice session via the :meth:`start` async class method.
    The instance holds the LiveKit room tokens, live :class:`LiveAvatarClient`,
    active :class:`AvatarSessionHandle`, and open :class:`AvatarWebSocket`.

    Caller responsibilities:
    - Run the opt-in gate (``is_avatar_enabled``) BEFORE calling :meth:`start`.
    - Call :meth:`aclose` in the cleanup path (idempotent; never raises).

    Args:
        _tokens: LiveKit room tokens (viewer + agent).
        _client: Open :class:`LiveAvatarClient` (keep-alive running).
        _handle: Active :class:`AvatarSessionHandle`.
        _ws: Open :class:`AvatarWebSocket` (already past the connected gate).
    """

    def __init__(
        self,
        *,
        tokens: LiveKitRoomTokens,
        client: LiveAvatarClient,
        handle: AvatarSessionHandle,
        ws: AvatarWebSocket,
        avatar_identity: Optional[str] = None,
        injected_credentials: bool = False,
    ) -> None:
        self._tokens = tokens
        self._client = client
        self._handle = handle
        self._ws = ws
        self._avatar_identity = avatar_identity
        self._injected_credentials = injected_credentials
        self._closed: bool = False
        self.logger = logging.getLogger(__name__)

    # ── Factory ────────────────────────────────────────────────────────

    @classmethod
    async def start(
        cls,
        *,
        agent_id: str,
        session_id: str,
        tenant_id: str | None,
        avatar_id: str | None = None,
        livekit_url: str | None = None,
        room_name: str | None = None,
        avatar_publisher_token: str | None = None,
        viewer_token: str | None = None,
        avatar_identity: str | None = None,
        broadcast: bool = False,
        on_event: Optional[EventCallback] = None,
        on_close: Optional[CloseCallback] = None,
        send_timeout_s: float | None = None,
        startup_deadline_s: float | None = None,
        max_session_duration_s: int | None = None,
    ) -> "VoiceAvatarSession":
        """Bring up a full LiveAvatar LITE session for realtime PCM delivery.

        Steps:
        1. Build :class:`LiveAvatarConfig` from env (``LIVEAVATAR_API_KEY``,
           ``LIVEAVATAR_AVATAR_ID``, ``LIVEAVATAR_BASE_URL``,
           ``LIVEAVATAR_SANDBOX``).
        2. Mint LiveKit room tokens via ``LiveKitRoomManager().mint_room_tokens``
           (offloaded to a thread — sync CPU work).
        3. Open a :class:`LiveAvatarClient` (``aopen``).
        4. Create a LITE session token (``create_session_token`` with
           ``livekit_config`` so the avatar joins our room).
        5. Start the session (``start_session``).
        6. Open the :class:`AvatarWebSocket` and await the connected gate
           (``start_speaking``).
        7. Return the ready :class:`VoiceAvatarSession`.

        On any failure, partially-opened resources are cleaned up before
        re-raising.

        Args:
            agent_id: Caller identity string (used as the LiveKit participant
                identity for the viewer token).
            session_id: ai-parrot session ID; becomes the LiveKit room name.
            tenant_id: Optional tenant identifier (stored on the handle for
                future opt-in / billing use).
            avatar_id: Optional avatar ID override.  Falls back to the
                ``LIVEAVATAR_AVATAR_ID`` environment variable.
            livekit_url: Pre-allocated room URL (broadcast path).
            room_name: Pre-allocated room name (broadcast path).
            avatar_publisher_token: The **avatar's own** publish-capable token
                for that room.  Supplying all three skips step 2 entirely: in a
                broadcast the room and both publisher identities are allocated
                *before* the avatar starts, and the avatar must not mint a
                second room or reuse the fixed ``avatar-agent`` identity.
            viewer_token: Optional subscribe-only token, only so
                :attr:`viewer_credentials` stays well-formed.  Broadcast
                participants get their own per-lease tokens instead.
            avatar_identity: The LiveKit identity the avatar publishes under,
                recorded for the public descriptor.
            broadcast: Configure the control socket for broadcast semantics —
                no silent reconnect, cross-call frame aggregation, and the
                caller's event/close callbacks.
            on_event: Forwarded to :class:`AvatarWebSocket` (broadcast only).
            on_close: Forwarded to :class:`AvatarWebSocket` (broadcast only).
            send_timeout_s: Per-send vendor deadline (broadcast only).
            startup_deadline_s: Bound on steps 3–6.  On expiry the partial
                resources are cleaned up and :class:`AvatarStartupTimeout` is
                raised so the caller can select audio-only.
            max_session_duration_s: Vendor session cap (spec §7: ≤ 600).

        Returns:
            A fully-initialised :class:`VoiceAvatarSession`.

        Raises:
            RuntimeError: If required env vars are missing.
            ValueError: If the injected-credential arguments are incomplete.
            AvatarStartupTimeout: If ``startup_deadline_s`` elapses.
            Any exception from the LiveAvatar / LiveKit client calls.
        """
        # 1. Build config from env
        api_key = os.environ.get("LIVEAVATAR_API_KEY", "")
        resolved_avatar_id = avatar_id or os.environ.get("LIVEAVATAR_AVATAR_ID", "")
        if not api_key or not resolved_avatar_id:
            raise RuntimeError(
                "LIVEAVATAR_API_KEY and LIVEAVATAR_AVATAR_ID must be set in env"
            )

        cfg = LiveAvatarConfig(
            api_key=api_key,
            avatar_id=resolved_avatar_id,
            base_url=os.environ.get(
                "LIVEAVATAR_BASE_URL", "https://api.liveavatar.com"
            ),
            is_sandbox=os.environ.get("LIVEAVATAR_SANDBOX", "true").lower() != "false",
            max_session_duration=max_session_duration_s,
        )

        # 2. Room credentials — injected (broadcast) or minted here (legacy).
        injected = (livekit_url, room_name, avatar_publisher_token)
        if any(value is not None for value in injected):
            if not all(value is not None for value in injected):
                raise ValueError(
                    "livekit_url, room_name and avatar_publisher_token must be "
                    "supplied together"
                )
            # ``agent_token`` here is the AVATAR publisher token for the shared
            # room — never the direct publisher's. The two must stay distinct
            # or they evict each other in LiveKit (spec §6).
            tokens = LiveKitRoomTokens(
                livekit_url=str(livekit_url),
                room=str(room_name),
                client_token=viewer_token or "",
                agent_token=str(avatar_publisher_token),
            )
            credentials_injected = True
        else:
            # Mint room tokens (sync CPU work — JWT signing via PyJWT, both
            # datetime.utcnow() and PyJWT are thread-safe; offload to avoid
            # blocking the event loop on key-derivation).
            room_manager = LiveKitRoomManager()
            tokens = await asyncio.to_thread(
                room_manager.mint_room_tokens, session_id, agent_id
            )
            credentials_injected = False

        # LiveKit config passed to the avatar so it joins our room as a publisher.
        # Field names follow LiveAvatar's LiveKitConfigSchema (snake_case) and
        # are verified against the OpenAPI document — do not rename them to the
        # configuration guide's shorthand (spec §2).
        livekit_config: dict[str, Any] = {
            "livekit_url": tokens.livekit_url,
            "livekit_room": tokens.room,
            "livekit_client_token": tokens.agent_token,  # avatar publishes → agent_token
        }

        started_at = time.monotonic()

        async def _bring_up() -> tuple[LiveAvatarClient, AvatarSessionHandle, AvatarWebSocket]:
            """Steps 3–6, as one cancellable unit for the startup deadline."""
            # 3. Open the HTTP client (keep-alive; NOT async-with — would stop
            # the session early).
            local_client = LiveAvatarClient(cfg)
            await local_client.aopen()

            local_ws: AvatarWebSocket | None = None
            local_handle: AvatarSessionHandle | None = None
            try:
                # 4. Create session token with livekit_config
                local_handle = await local_client.create_session_token(
                    cfg, livekit_config=livekit_config
                )
                # Populate the ai-parrot session id and tenant
                # (create_session_token cannot know these — it is the
                # HTTP-layer's responsibility).
                local_handle.session_id = session_id
                local_handle.tenant_id = tenant_id

                # 5. Start the session (also populates handle.ws_url)
                await local_client.start_session(local_handle)

                # 6. Open the AvatarWebSocket and await the connected gate.
                # We enter the context manager manually (not via async-with) so
                # the WebSocket stays open for the lifetime of this session.
                if broadcast:
                    # A broadcast must SEE a control-socket drop (it is a
                    # fallback trigger), and must coalesce Nova's small chunks
                    # into vendor-sized frames.
                    local_ws = AvatarWebSocket(
                        local_handle,
                        on_event=on_event,
                        on_close=on_close,
                        auto_reconnect=False,
                        aggregate=True,
                        send_timeout_s=send_timeout_s,
                    )
                else:
                    local_ws = AvatarWebSocket(local_handle)
                await local_ws.__aenter__()
                await local_ws.start_speaking()
                return local_client, local_handle, local_ws
            except BaseException:
                # Clean up any partially-opened resources before re-raising.
                # BaseException, not Exception: a startup-deadline cancellation
                # arrives as CancelledError and must not leak a live vendor
                # session (which would keep billing and hold the room).
                if local_ws is not None:
                    with contextlib.suppress(Exception):
                        await local_ws.__aexit__(None, None, None)
                if local_handle is not None:
                    with contextlib.suppress(Exception):
                        await local_client.stop_session(local_handle)
                with contextlib.suppress(Exception):
                    await local_client.aclose()
                raise

        if startup_deadline_s is None:
            client, handle, ws = await _bring_up()
        else:
            try:
                client, handle, ws = await asyncio.wait_for(
                    _bring_up(), timeout=startup_deadline_s
                )
            except asyncio.TimeoutError as exc:
                raise AvatarStartupTimeout(
                    "VoiceAvatarSession: avatar did not become ready within "
                    f"{startup_deadline_s}s"
                ) from exc

        logging.getLogger(__name__).info(
            "VoiceAvatarSession: ready for session %s in %.3fs (broadcast=%s)",
            session_id,
            time.monotonic() - started_at,
            broadcast,
        )
        return cls(
            tokens=tokens,
            client=client,
            handle=handle,
            ws=ws,
            avatar_identity=avatar_identity,
            injected_credentials=credentials_injected,
        )

    # ── Public interface ───────────────────────────────────────────────

    @property
    def viewer_credentials(self) -> dict[str, str]:
        """Browser-safe viewer credentials for the LiveKit room.

        Returns ONLY the subscribe-only ``client_token`` (+ URL + room name).
        The ``agent_token`` / ``ws_url`` / ``session_token`` are NEVER exposed.

        On the broadcast path the ``client_token`` is whatever ``viewer_token``
        the caller passed (often empty): broadcast participants receive their
        own per-lease subscribe-only credentials from the admission API, never
        a shared one from here.

        Returns:
            Dict with keys ``livekit_url``, ``client_token``, and ``room``.
        """
        return {
            "livekit_url": self._tokens.livekit_url,
            "client_token": self._tokens.client_token,
            "room": self._tokens.room,
        }

    @property
    def liveavatar_session_id(self) -> str:
        """The vendor's session id — audit only, never an access token."""
        return self._handle.liveavatar_session_id

    @property
    def room_name(self) -> str:
        """The LiveKit room this avatar publishes into."""
        return self._tokens.room

    @property
    def avatar_identity(self) -> Optional[str]:
        """The LiveKit identity the avatar publishes under, when known."""
        return self._avatar_identity

    @property
    def closed(self) -> bool:
        """Whether :meth:`aclose` has already run."""
        return self._closed

    async def speak(self, pcm: bytes) -> None:
        """Push one PCM chunk into the avatar's mouth.

        The bytes are forwarded as-is to :meth:`AvatarWebSocket.send_audio_frame`
        — no resampling, no buffering.  Input must be 24 kHz mono 16-bit LE,
        which matches Gemini Live's output format exactly.

        Args:
            pcm: Raw PCM bytes (int16 LE mono 24 kHz).
        """
        await self._ws.send_audio_frame(pcm)

    async def finish_turn(self) -> None:
        """Flush the avatar's audio buffer at the end of a turn.

        Sends the ``agent.speak_end`` frame so the avatar media server knows
        this utterance is complete and can flush its playback buffer.
        """
        await self._ws.finish_speaking()

    async def interrupt(self) -> None:
        """Clear the avatar's scheduled audio on a barge-in.

        Sends ``agent.interrupt`` to stop any in-progress avatar speech
        immediately.  Call this when ``LiveVoiceResponse.is_interrupted`` is
        ``True``.
        """
        await self._ws.interrupt()

    async def aclose(self) -> None:
        """Tear down the avatar session.  Idempotent, never raises.

        Closes the :class:`AvatarWebSocket`, stops the LiveAvatar session
        (``stop_session``), and closes the HTTP client (``aclose``).  Safe to
        call multiple times; subsequent calls are no-ops.
        """
        if self._closed:
            return
        self._closed = True

        self.logger.info(
            "VoiceAvatarSession: closing session %s",
            self._handle.session_id if self._handle else "<unknown>",
        )

        with contextlib.suppress(Exception):
            await self._ws.__aexit__(None, None, None)

        if self._handle is not None:
            with contextlib.suppress(Exception):
                await self._client.stop_session(self._handle)

        with contextlib.suppress(Exception):
            await self._client.aclose()
