"""LiveKit room manager — BYO Cloud tokens (FEAT-242 Phase A — Module 3).

Mints a LiveKit Cloud room plus client/agent JWT tokens using the
``livekit-api`` library.  **Shared with Phase C (FEAT-243).**

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
from typing import Optional

from parrot.integrations.liveavatar.models import LiveKitRoomTokens


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
