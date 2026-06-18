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
from typing import Any, Dict, Optional

from parrot.integrations.liveavatar.avatar_ws import AvatarWebSocket
from parrot.integrations.liveavatar.client import LiveAvatarClient
from parrot.integrations.liveavatar.models import (
    AvatarSessionHandle,
    LiveAvatarConfig,
    LiveKitRoomTokens,
)
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager


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
    ) -> None:
        self._tokens = tokens
        self._client = client
        self._handle = handle
        self._ws = ws
        self._closed: bool = False
        self.logger = logging.getLogger(__name__)

    # ── Factory ────────────────────────────────────────────────────────

    @classmethod
    async def start(
        cls,
        *,
        agent_id: str,
        session_id: str,
        tenant_id: Optional[str],
        avatar_id: Optional[str] = None,
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

        Returns:
            A fully-initialised :class:`VoiceAvatarSession`.

        Raises:
            RuntimeError: If required env vars are missing.
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
        )

        # 2. Mint room tokens (sync CPU work — offload to thread)
        room_manager = LiveKitRoomManager()
        tokens: LiveKitRoomTokens = await asyncio.to_thread(
            room_manager.mint_room_tokens, session_id, agent_id
        )

        # LiveKit config passed to the avatar so it joins our room as a publisher.
        # Field names follow LiveAvatar's LiveKitConfigSchema (snake_case).
        livekit_config: Dict[str, Any] = {
            "livekit_url": tokens.livekit_url,
            "livekit_room": tokens.room,
            "livekit_client_token": tokens.agent_token,  # avatar publishes → agent_token
        }

        # 3. Open the HTTP client (keep-alive; NOT async-with — would stop session early)
        client = LiveAvatarClient(cfg)
        await client.aopen()

        ws: Optional[AvatarWebSocket] = None
        handle: Optional[AvatarSessionHandle] = None
        try:
            # 4. Create session token with livekit_config
            handle = await client.create_session_token(cfg, livekit_config=livekit_config)
            # Populate the ai-parrot session id and tenant (create_session_token
            # cannot know these — it is the HTTP-layer's responsibility).
            handle.session_id = session_id
            handle.tenant_id = tenant_id

            # 5. Start the session (also populates handle.ws_url)
            await client.start_session(handle)

            # 6. Open the AvatarWebSocket and await the connected gate.
            # We enter the context manager manually (not via async-with) so the
            # WebSocket stays open for the lifetime of this session object.
            ws = AvatarWebSocket(handle)
            await ws.__aenter__()
            await ws.start_speaking()

        except Exception:
            # Clean up any partially-opened resources before re-raising.
            if ws is not None:
                with contextlib.suppress(Exception):
                    await ws.__aexit__(None, None, None)
            if handle is not None:
                with contextlib.suppress(Exception):
                    await client.stop_session(handle)
            with contextlib.suppress(Exception):
                await client.aclose()
            raise

        return cls(tokens=tokens, client=client, handle=handle, ws=ws)

    # ── Public interface ───────────────────────────────────────────────

    @property
    def viewer_credentials(self) -> Dict[str, str]:
        """Browser-safe viewer credentials for the LiveKit room.

        Returns ONLY the subscribe-only ``client_token`` (+ URL + room name).
        The ``agent_token`` / ``ws_url`` / ``session_token`` are NEVER exposed.

        Returns:
            Dict with keys ``livekit_url``, ``client_token``, and ``room``.
        """
        return {
            "livekit_url": self._tokens.livekit_url,
            "client_token": self._tokens.client_token,
            "room": self._tokens.room,
        }

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
