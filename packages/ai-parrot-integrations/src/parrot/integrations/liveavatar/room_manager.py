"""LiveKit room manager — BYO Cloud tokens (FEAT-242 Phase A — Module 3).

Mints a LiveKit Cloud room plus client/agent JWT tokens using the
``livekit-api`` library.

Env vars required:
    LIVEKIT_URL        wss://<project>.livekit.cloud
    LIVEKIT_API_KEY    LiveKit Cloud API key
    LIVEKIT_API_SECRET LiveKit Cloud API secret

Tokens:
    client_token  — subscribe-only grants (browser viewer; safe to expose).
    agent_token   — publish + subscribe grants (avatar participant; server-side only).

``livekit-api`` is an optional dependency; a clear error is raised on import
if the package is not installed (install with the ``liveavatar`` extra).
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import List, Optional

from parrot.integrations.liveavatar.models import LiveKitRoomTokens

#: Default validity of an admission credential.  Spec §2: viewer credentials
#: expire after 60 seconds *for admission*; expiry does not disconnect an
#: already-joined participant and is not revocation.
DEFAULT_VIEWER_TOKEN_TTL_S: int = 60

#: Default validity of a server-side publisher token (avatar or direct).
DEFAULT_PUBLISHER_TOKEN_TTL_S: int = 3600


def _require_livekit_api() -> object:
    """Lazily import ``livekit.api`` and raise a clear error when missing.

    Returns:
        The ``livekit.api`` module.

    Raises:
        ImportError: If ``livekit-api`` is not installed.
    """
    try:
        from livekit import api as livekit_api  # type: ignore[import-untyped]
        return livekit_api
    except ImportError as exc:
        raise ImportError(
            "livekit-api is not installed.  "
            "Install the liveavatar extra: "
            "pip install ai-parrot-integrations[liveavatar]"
        ) from exc


class LiveKitRoomManager:
    """Mint LiveKit Cloud room tokens for the BYO transport.

    Creates two JWTs per room:
    - ``client_token``: subscribe-only, safe to send to the browser viewer.
    - ``agent_token``: publish + subscribe, kept server-side only (never
      serialised into client responses).

    Args:
        url: LiveKit WebSocket URL (defaults to ``LIVEKIT_URL`` env).
        api_key: LiveKit API key (defaults to ``LIVEKIT_API_KEY`` env).
        api_secret: LiveKit API secret (defaults to ``LIVEKIT_API_SECRET`` env).

    Raises:
        KeyError: If a required env var is missing and no value is supplied.
    """

    _AGENT_IDENTITY: str = "avatar-agent"

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ) -> None:
        self.url: str = url or os.environ["LIVEKIT_URL"]
        self._key: str = api_key or os.environ["LIVEKIT_API_KEY"]
        self._secret: str = api_secret or os.environ["LIVEKIT_API_SECRET"]
        self.logger = logging.getLogger(__name__)

    def mint_room_tokens(
        self,
        room: str,
        identity: str,
    ) -> LiveKitRoomTokens:
        """Mint viewer and agent JWT tokens for a LiveKit room.

        The caller is responsible for keeping ``agent_token`` server-side.

        Args:
            room: Room name (e.g. the ai-parrot ``session_id``).
            identity: Viewer participant identity (used for the client token).

        Returns:
            A :class:`LiveKitRoomTokens` with ``client_token`` and
            ``agent_token`` populated.

        Raises:
            ImportError: If ``livekit-api`` is not installed.
        """
        livekit_api = _require_livekit_api()

        # Client token — subscribe-only (viewer)
        client_grants = livekit_api.VideoGrants(
            room_join=True,
            room=room,
            can_publish=False,
            can_subscribe=True,
        )
        client_token: str = (
            livekit_api.AccessToken(self._key, self._secret)
            .with_identity(identity)
            .with_grants(client_grants)
            .to_jwt()
        )

        # Agent token — publish + subscribe (avatar participant)
        agent_grants = livekit_api.VideoGrants(
            room_join=True,
            room=room,
            can_publish=True,
            can_subscribe=True,
        )
        agent_token: str = (
            livekit_api.AccessToken(self._key, self._secret)
            .with_identity(self._AGENT_IDENTITY)
            .with_grants(agent_grants)
            .to_jwt()
        )

        self.logger.debug(
            "LiveKitRoomManager: minted tokens for room=%s identity=%s", room, identity
        )
        return LiveKitRoomTokens(
            livekit_url=self.url,
            room=room,
            client_token=client_token,
            agent_token=agent_token,
        )

    # ── FEAT-537: role-specific tokens ─────────────────────────────────

    def mint_viewer_token(
        self,
        room: str,
        identity: str,
        *,
        ttl_s: int = DEFAULT_VIEWER_TOKEN_TTL_S,
    ) -> str:
        """Mint one browser's subscribe-only admission credential.

        Every browser connection gets its **own** identity: reusing an identity
        disconnects the previous participant in LiveKit, so a shared viewer
        token would let one late joiner evict an existing viewer.  The grants
        deliberately disable publishing *and* data publishing, and carry no
        administrative rights, so possession of this token can never be
        mistaken for permission to speak.

        Args:
            room: Allocated LiveKit room name.
            identity: Unique per-browser participant identity.
            ttl_s: Admission-credential validity in seconds.

        Returns:
            A signed subscribe-only JWT.

        Raises:
            ImportError: If ``livekit-api`` is not installed.
        """
        livekit_api = _require_livekit_api()
        grants = livekit_api.VideoGrants(
            room_join=True,
            room=room,
            can_publish=False,
            can_subscribe=True,
            can_publish_data=False,
        )
        token: str = (
            livekit_api.AccessToken(self._key, self._secret)
            .with_identity(identity)
            .with_grants(grants)
            .with_ttl(timedelta(seconds=ttl_s))
            .to_jwt()
        )
        self.logger.debug(
            "LiveKitRoomManager: minted viewer token for room=%s identity=%s ttl=%ss",
            room,
            identity,
            ttl_s,
        )
        return token

    def mint_publisher_token(
        self,
        room: str,
        identity: str,
        *,
        ttl_s: int = DEFAULT_PUBLISHER_TOKEN_TTL_S,
        name: Optional[str] = None,
    ) -> str:
        """Mint a server-side publisher token for a caller-chosen identity.

        A broadcast needs **two distinct** publishers in one room — the avatar
        participant and the direct audio publisher used after fallback — so
        the identity is a required argument rather than the class's fixed
        legacy :attr:`_AGENT_IDENTITY`.  Reusing ``avatar-agent`` for the direct
        publisher would make the two evict each other (spec §6).

        Never returned to a browser.

        Args:
            room: Allocated LiveKit room name.
            identity: Publisher participant identity, e.g. ``avatar-<bid8>`` or
                ``direct-<bid8>``.
            ttl_s: Token validity in seconds.
            name: Optional display name for the participant.

        Returns:
            A signed publish-capable JWT.  Server-side only.

        Raises:
            ImportError: If ``livekit-api`` is not installed.
            ValueError: If ``identity`` is the legacy fixed agent identity.
        """
        if identity == self._AGENT_IDENTITY:
            raise ValueError(
                "the fixed 'avatar-agent' identity must not be reused for a "
                "broadcast publisher; pass a per-broadcast identity"
            )
        livekit_api = _require_livekit_api()
        grants = livekit_api.VideoGrants(
            room_join=True,
            room=room,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=False,
        )
        builder = (
            livekit_api.AccessToken(self._key, self._secret)
            .with_identity(identity)
            .with_grants(grants)
            .with_ttl(timedelta(seconds=ttl_s))
        )
        if name is not None:
            builder = builder.with_name(name)
        token: str = builder.to_jwt()
        self.logger.debug(
            "LiveKitRoomManager: minted publisher token for room=%s identity=%s",
            room,
            identity,
        )
        return token

    # ── FEAT-537: room administration ──────────────────────────────────

    @property
    def http_url(self) -> str:
        """The HTTP(S) form of :attr:`url`, required by ``LiveKitAPI``.

        The realtime SDK connects over ``ws(s)://`` but the server API is a
        plain HTTP service on the same host, so the scheme is rewritten rather
        than configured twice.  A non-``ws`` URL is passed through unchanged.
        """
        if self.url.startswith("wss://"):
            return "https://" + self.url[len("wss://"):]
        if self.url.startswith("ws://"):
            return "http://" + self.url[len("ws://"):]
        return self.url

    def _api(self) -> object:
        """Build a ``LiveKitAPI`` client for one room-service call.

        Returns:
            A fresh ``livekit.api.LiveKitAPI``; the caller must ``aclose()`` it.

        Raises:
            ImportError: If ``livekit-api`` is not installed.
        """
        livekit_api = _require_livekit_api()
        return livekit_api.LiveKitAPI(self.http_url, self._key, self._secret)

    async def create_room(
        self,
        room: str,
        *,
        max_participants: int = 12,
        empty_timeout_s: int = 60,
    ) -> None:
        """Create the room that will carry one broadcast.

        ``max_participants`` defaults to **12**, not 10: the ten-seat rule is a
        *viewer* limit enforced by application reservations, and the room must
        additionally hold the avatar publisher and the direct publisher
        (spec §7).  Setting it to 10 here would lock out two real viewers.

        Args:
            room: Room name to create.
            max_participants: Hard room capacity — viewers plus both producers.
            empty_timeout_s: Seconds LiveKit keeps an empty room alive.

        Raises:
            ImportError: If ``livekit-api`` is not installed.
        """
        livekit_api = _require_livekit_api()
        client = self._api()
        try:
            await client.room.create_room(
                livekit_api.CreateRoomRequest(
                    name=room,
                    max_participants=max_participants,
                    empty_timeout=empty_timeout_s,
                )
            )
            self.logger.info(
                "LiveKitRoomManager: created room=%s (max_participants=%d)",
                room,
                max_participants,
            )
        finally:
            await client.aclose()

    async def remove_participant(self, room: str, identity: str) -> None:
        """Remove one participant from a room.

        Used to evict an expired control participant **before** its application
        seat is released, so an over-admitted joiner can never take a seat that
        is still occupied in the room itself (spec §2).

        Args:
            room: Room name.
            identity: Participant identity to remove.

        Raises:
            ImportError: If ``livekit-api`` is not installed.
        """
        livekit_api = _require_livekit_api()
        client = self._api()
        try:
            await client.room.remove_participant(
                livekit_api.RoomParticipantIdentity(room=room, identity=identity)
            )
            self.logger.info(
                "LiveKitRoomManager: removed identity=%s from room=%s", identity, room
            )
        finally:
            await client.aclose()

    async def list_participant_identities(self, room: str) -> List[str]:
        """Return the identities LiveKit currently reports for a room.

        This is the authority used to reconcile application reservations
        against real presence; on any uncertainty the caller must retain the
        seat rather than over-admit.

        Args:
            room: Room name.

        Returns:
            Participant identities, publishers included.

        Raises:
            ImportError: If ``livekit-api`` is not installed.
        """
        livekit_api = _require_livekit_api()
        client = self._api()
        try:
            response = await client.room.list_participants(
                livekit_api.ListParticipantsRequest(room=room)
            )
            return [participant.identity for participant in response.participants]
        finally:
            await client.aclose()

    async def delete_room(self, room: str) -> None:
        """Delete a room and disconnect everyone still in it.

        Args:
            room: Room name.

        Raises:
            ImportError: If ``livekit-api`` is not installed.
        """
        livekit_api = _require_livekit_api()
        client = self._api()
        try:
            await client.room.delete_room(livekit_api.DeleteRoomRequest(room=room))
            self.logger.info("LiveKitRoomManager: deleted room=%s", room)
        finally:
            await client.aclose()

