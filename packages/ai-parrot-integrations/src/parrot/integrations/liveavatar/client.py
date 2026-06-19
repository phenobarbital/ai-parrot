"""LiveAvatar HTTP client and session lifecycle (FEAT-242 Phase A — Module 1).

Ports the LiveAvatar starter ``liveavatar_client.py`` (httpx/websockets) to
``aiohttp`` per project standards.

Responsibilities:
- ``create_session_token``: create a LITE session (optionally with
  ``livekit_config`` so the avatar joins our LiveKit Cloud room).
- ``create_full_session_token``: create a FULL mode session (FEAT-248).
- ``start_session``: start the created session (Bearer auth).
- ``stop_session``: stop/close the session (idempotent).
- ``keep_alive``: periodic HTTP keep-alive (< 5 min interval).
- ``list_avatars``: list available avatars (FEAT-248).
- ``list_voices``: list available voices (FEAT-248).
- ``get_session_transcript``: retrieve session transcript (FEAT-248).

Auth headers:
- ``X-API-KEY: cfg.api_key`` on create / stop / keep-alive.
- ``Authorization: Bearer <handle.session_token>`` on start_session.

Keep-alive strategy: HTTP ``/v1/sessions/{id}/keep-alive`` is used here
(not the WS variant).  # TODO P7 — if WS keep_alive is chosen in the
future, move this call to AvatarWebSocket (TASK-003).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from parrot.integrations.liveavatar.models import (
    AvatarSessionHandle,
    FullModeConfig,
    FullModeSessionHandle,
    LiveAvatarConfig,
)

# Keep-alive interval must be strictly less than the LiveAvatar 5 min inactivity
# timeout.  280 s gives a comfortable 20 s safety margin.
_KEEP_ALIVE_INTERVAL: int = 280  # seconds


class LiveAvatarClient:
    """Async HTTP client for the LiveAvatar LITE API.

    Manages session token creation, session start/stop, and periodic
    keep-alive.  All auth is handled internally; callers receive an opaque
    :class:`~parrot.integrations.liveavatar.models.AvatarSessionHandle`.

    Usage (preferred — guarantees stop on exit)::

        async with LiveAvatarClient(cfg) as client:
            handle = await client.create_session_token(cfg)
            await client.start_session(handle)
            ...  # speak

    Args:
        cfg: LiveAvatar configuration (read from env by the caller).
        session: Optional external ``aiohttp.ClientSession`` to reuse.
            When ``None`` (default) the client creates and owns one.
    """

    def __init__(
        self,
        cfg: LiveAvatarConfig,
        *,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)
        self._session: Optional[aiohttp.ClientSession] = session
        self._owns_session: bool = session is None
        self._keep_alive_task: Optional[asyncio.Task[None]] = None
        self._handle: Optional[AvatarSessionHandle] = None

    # ── Context manager ────────────────────────────────────────────────

    async def __aenter__(self) -> "LiveAvatarClient":
        """Open the aiohttp session if not provided externally."""
        return await self.aopen()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Guarantee stop_session + keep-alive cancellation on exit."""
        if self._handle is not None:
            try:
                await self.stop_session(self._handle)
            except Exception:  # noqa: BLE001
                self.logger.exception("LiveAvatarClient: stop_session failed on exit")
        await self.aclose()

    async def aopen(self) -> "LiveAvatarClient":
        """Open the owned aiohttp session (idempotent).

        Used by callers that need to keep the client alive *beyond* a single
        ``async with`` block — e.g. the avatar ``/start`` endpoint, which hands
        the live client to a per-session store so ``/stop`` can tear it down
        later.  Unlike ``__aexit__``, ``aclose`` does NOT call ``stop_session``,
        so ownership of the LiveAvatar session is transferred to the caller.

        Returns:
            ``self`` (for fluent use).
        """
        if self._owns_session and self._session is None:
            self._session = aiohttp.ClientSession()
        return self

    async def aclose(self) -> None:
        """Cancel the keep-alive loop and close the owned aiohttp session.

        Awaits the keep-alive task's cancellation so no ping can fire against a
        closing session (avoids "Future exception was never retrieved").  Does
        NOT call ``stop_session`` — callers that opened the client via
        ``aopen`` must stop the LiveAvatar session explicitly.
        """
        await self._acancel_keep_alive()
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    # ── Public API ─────────────────────────────────────────────────────

    async def create_session_token(
        self,
        cfg: LiveAvatarConfig,
        *,
        livekit_config: Optional[Dict[str, Any]] = None,
    ) -> AvatarSessionHandle:
        """Create a LiveAvatar LITE session token.

        Calls ``POST /v1/sessions`` on the LiveAvatar API, optionally
        embedding ``livekit_config`` so the avatar joins our LiveKit Cloud
        room.

        Args:
            cfg: LiveAvatar configuration (api_key, avatar_id, …).
            livekit_config: Optional LiveKit room config dict to pass to the
                API so the avatar joins our room (BYO transport).

        Returns:
            An :class:`AvatarSessionHandle` populated with the API response.

        Raises:
            aiohttp.ClientResponseError: On non-2xx responses.
        """
        url = f"{cfg.base_url}/v1/sessions/token"
        headers = self._api_key_headers(cfg)

        # LITE (BYO transport) mode — see LiteSDKSessionTokenConfigDataSchema in
        # https://docs.liveavatar.com/openapi.json.  All field names are
        # snake_case and the response is wrapped in a ``data`` envelope.
        payload: Dict[str, Any] = {
            "mode": "LITE",
            "avatar_id": cfg.avatar_id,
        }
        if cfg.is_sandbox:
            payload["is_sandbox"] = True
        if cfg.max_session_duration is not None:
            payload["max_session_duration"] = cfg.max_session_duration
        if livekit_config is not None:
            payload["livekit_config"] = livekit_config
        if cfg.quality is not None or cfg.encoding is not None:
            video_settings: Dict[str, Any] = {}
            if cfg.quality is not None:
                video_settings["quality"] = cfg.quality  # TODO Q-video-settings
            if cfg.encoding is not None:
                video_settings["encoding"] = cfg.encoding  # TODO Q-video-settings
            payload["video_settings"] = video_settings

        self.logger.debug("LiveAvatarClient: creating session for avatar %s", cfg.avatar_id)
        response_data = await self._post(url, headers=headers, json=payload)
        # The API wraps the payload in an envelope: {code, data, message}.
        data = response_data.get("data") or response_data

        # NOTE: ``session_id`` is the ai-parrot/AgentChat session id, which is
        # NOT known to this HTTP client — it is left empty here and the CALLER
        # MUST populate ``handle.session_id`` before using the handle (the
        # orchestrator and the /start endpoint both do).  ``liveavatar_session_id``
        # is the external API's id and is the only id this layer can supply.
        # NOTE: the /token response carries only session_id + session_token.
        # ``ws_url`` (and the LiveKit tokens) are returned later by /start, so
        # the handle's ws_url is populated in :meth:`start_session`.
        handle = AvatarSessionHandle(
            session_id="",
            liveavatar_session_id=data.get("session_id", ""),
            session_token=data.get("session_token", ""),
            ws_url="",
            agent_name=cfg.avatar_id,
        )
        self._handle = handle
        self.logger.info("LiveAvatarClient: session token created — id=%s", handle.liveavatar_session_id)
        return handle

    async def create_full_session_token(
        self,
        cfg: FullModeConfig,
    ) -> FullModeSessionHandle:
        """Create a LiveAvatar FULL mode session token (restricted — no LLM, no context).

        Sends ``mode: "FULL"`` with ``avatar_persona`` (voice_id, language),
        ``interactivity_type``, ``video_settings``, and ``max_session_duration``.
        Critically: ``llm_configuration_id`` and ``context_id`` are OMITTED so the
        avatar never auto-responds via its built-in LLM (Q1 confirmed by spike).

        Args:
            cfg: FULL mode configuration (voice_id, language, interactivity_type,
                plus all base LiveAvatarConfig fields).

        Returns:
            A :class:`FullModeSessionHandle` populated with ``session_id`` and
            ``session_token`` from the API.  ``livekit_url`` and
            ``livekit_client_token`` are populated later by :meth:`start_session`.

        Raises:
            aiohttp.ClientResponseError: On non-2xx responses.
        """
        url = f"{cfg.base_url}/v1/sessions/token"
        headers = self._api_key_headers(cfg)

        payload: Dict[str, Any] = {
            "mode": "FULL",
            "avatar_id": cfg.avatar_id,
            "interactivity_type": cfg.interactivity_type,
        }
        # avatar_persona — only include voice_id if set (None means use avatar default)
        persona: Dict[str, Any] = {}
        if cfg.voice_id:
            persona["voice_id"] = cfg.voice_id
        if cfg.language:
            persona["language"] = cfg.language
        if persona:
            payload["avatar_persona"] = persona

        # video_settings (quality / encoding from base config)
        video_settings: Dict[str, Any] = {}
        if cfg.quality is not None:
            video_settings["quality"] = cfg.quality
        if cfg.encoding is not None:
            video_settings["encoding"] = cfg.encoding
        if video_settings:
            payload["video_settings"] = video_settings

        if cfg.is_sandbox:
            payload["is_sandbox"] = True
        if cfg.max_session_duration is not None:
            payload["max_session_duration"] = cfg.max_session_duration

        # NOTE: ``llm_configuration_id`` and ``context_id`` are intentionally OMITTED.
        # This puts the avatar in restricted mode — it will never auto-respond
        # with its built-in LLM (Q1 confirmed by spike_q1_speaktext.py).

        self.logger.debug(
            "LiveAvatarClient: creating FULL mode session for avatar %s", cfg.avatar_id
        )
        response_data = await self._post(url, headers=headers, json=payload)
        data = response_data.get("data") or response_data

        handle = FullModeSessionHandle(
            session_id="",
            liveavatar_session_id=data.get("session_id", ""),
            session_token=data.get("session_token", ""),
            ws_url="",  # unused in FULL mode; populated by LITE start_session only
            agent_name=cfg.avatar_id,
        )
        self._handle = handle
        self.logger.info(
            "LiveAvatarClient: FULL mode session token created — id=%s",
            handle.liveavatar_session_id,
        )
        return handle

    async def start_session(self, handle: AvatarSessionHandle) -> Dict[str, Any]:
        """Start a previously created session.

        Uses ``Authorization: Bearer <session_token>`` auth.

        For :class:`FullModeSessionHandle`, the ``/start`` response carries
        ``livekit_url`` and ``livekit_client_token`` (not ``ws_url``) — both are
        populated on the handle so the caller can return them to the browser.

        Args:
            handle: The session handle returned by :meth:`create_session_token`
                or :meth:`create_full_session_token`.

        Returns:
            The raw API response dict.

        Raises:
            aiohttp.ClientResponseError: On non-2xx responses.
        """
        url = f"{self.cfg.base_url}/v1/sessions/start"
        headers = self._bearer_headers(handle)

        self.logger.debug("LiveAvatarClient: starting session %s", handle.liveavatar_session_id)
        result = await self._post(url, headers=headers, json={})
        # The /start response (StartSessionResponseSchema) carries ws_url and the
        # LiveKit tokens, wrapped in a ``data`` envelope.  Populate ws_url now.
        start_data = result.get("data") or result
        handle.ws_url = start_data.get("ws_url", handle.ws_url)

        # FULL mode: /start returns livekit_url + livekit_client_token (not ws_url).
        if isinstance(handle, FullModeSessionHandle):
            handle.livekit_url = start_data.get("livekit_url", handle.livekit_url)
            handle.livekit_client_token = start_data.get(
                "livekit_client_token", handle.livekit_client_token
            )

        self.logger.info("LiveAvatarClient: session started — id=%s", handle.liveavatar_session_id)

        # Start the background keep-alive loop after the session is live.
        self._start_keep_alive(handle)
        return result

    async def stop_session(self, handle: AvatarSessionHandle) -> None:
        """Stop (close) an active session.

        Idempotent: safe to call multiple times or after the session has
        already closed.

        Args:
            handle: The session handle to stop.
        """
        await self._acancel_keep_alive()

        if not handle.liveavatar_session_id:
            return

        # No session id in the path — the session is identified by the Bearer
        # ``session_token``.  Body defaults to {"reason": "USER_CLOSED"}.
        url = f"{self.cfg.base_url}/v1/sessions/stop"
        headers = self._bearer_headers(handle)

        self.logger.debug("LiveAvatarClient: stopping session %s", handle.liveavatar_session_id)
        try:
            await self._post(url, headers=headers, json={"reason": "USER_CLOSED"})
        except aiohttp.ClientResponseError as exc:
            # 404 means already closed — treat as success.
            if exc.status == 404:
                self.logger.debug(
                    "LiveAvatarClient: session %s already closed (404)",
                    handle.liveavatar_session_id,
                )
            else:
                self.logger.warning(
                    "LiveAvatarClient: stop_session failed for %s: %s",
                    handle.liveavatar_session_id,
                    exc,
                )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "LiveAvatarClient: unexpected error stopping session %s",
                handle.liveavatar_session_id,
            )
        self.logger.info("LiveAvatarClient: session stopped — id=%s", handle.liveavatar_session_id)

    async def keep_alive(self, handle: AvatarSessionHandle) -> None:
        """Send a single HTTP keep-alive ping for the session.

        Calls ``POST /v1/sessions/keep-alive`` with Bearer ``session_token``
        auth (no session id in the path — the token scopes the session).
        # TODO P7 — switch to WS ``session.keep_alive`` here if the WS
        #           variant is chosen as the canonical keep-alive transport.

        Args:
            handle: The active session handle.
        """
        url = f"{self.cfg.base_url}/v1/sessions/keep-alive"
        headers = self._bearer_headers(handle)
        try:
            await self._post(url, headers=headers, json={})
            self.logger.debug("LiveAvatarClient: keep-alive sent for %s", handle.liveavatar_session_id)
        except Exception:  # noqa: BLE001
            self.logger.warning(
                "LiveAvatarClient: keep-alive failed for %s",
                handle.liveavatar_session_id,
                exc_info=True,
            )

    async def list_avatars(self, cfg: LiveAvatarConfig) -> List[Dict[str, Any]]:
        """List available avatars (stock + user-uploaded).

        Calls ``GET /v1/avatars`` with ``X-API-KEY`` auth.

        Args:
            cfg: LiveAvatar configuration (provides api_key and base_url).

        Returns:
            List of avatar dicts from the LiveAvatar API.

        Raises:
            aiohttp.ClientResponseError: On non-2xx responses.
        """
        url = f"{cfg.base_url}/v1/avatars"
        headers = self._api_key_headers(cfg)
        self.logger.debug("LiveAvatarClient: listing avatars")
        result = await self._get(url, headers=headers)
        data = result.get("data") or result
        if isinstance(data, list):
            return data
        return data.get("avatars") or data.get("items") or []

    async def list_voices(self, cfg: LiveAvatarConfig) -> List[Dict[str, Any]]:
        """List available voices.

        Calls ``GET /v1/voices`` with ``X-API-KEY`` auth.

        Args:
            cfg: LiveAvatar configuration (provides api_key and base_url).

        Returns:
            List of voice dicts from the LiveAvatar API.

        Raises:
            aiohttp.ClientResponseError: On non-2xx responses.
        """
        url = f"{cfg.base_url}/v1/voices"
        headers = self._api_key_headers(cfg)
        self.logger.debug("LiveAvatarClient: listing voices")
        result = await self._get(url, headers=headers)
        data = result.get("data") or result
        if isinstance(data, list):
            return data
        return data.get("voices") or data.get("items") or []

    async def get_session_transcript(
        self,
        cfg: LiveAvatarConfig,
        session_id: str,
    ) -> Dict[str, Any]:
        """Retrieve the server-side transcript for a completed session.

        Calls ``GET /v1/sessions/{session_id}/transcript`` with ``X-API-KEY`` auth.

        Args:
            cfg: LiveAvatar configuration (provides api_key and base_url).
            session_id: LiveAvatar session ID (``liveavatar_session_id`` on the handle).

        Returns:
            Transcript dict from the LiveAvatar API.

        Raises:
            aiohttp.ClientResponseError: On non-2xx responses.
        """
        url = f"{cfg.base_url}/v1/sessions/{session_id}/transcript"
        headers = self._api_key_headers(cfg)
        self.logger.debug(
            "LiveAvatarClient: fetching transcript for session %s", session_id
        )
        result = await self._get(url, headers=headers)
        return result.get("data") or result

    # ── Internal helpers ───────────────────────────────────────────────

    def _api_key_headers(self, cfg: LiveAvatarConfig) -> Dict[str, str]:
        """Build headers with ``X-API-KEY`` auth.

        Args:
            cfg: LiveAvatar configuration containing the API key.

        Returns:
            Headers dict suitable for most LiveAvatar API calls.
        """
        return {
            "X-API-KEY": cfg.api_key,
            "Content-Type": "application/json",
        }

    def _bearer_headers(self, handle: AvatarSessionHandle) -> Dict[str, str]:
        """Build headers with ``Authorization: Bearer`` for start_session.

        Args:
            handle: The session handle whose ``session_token`` to use.

        Returns:
            Headers dict for the start_session API call.
        """
        return {
            "Authorization": f"Bearer {handle.session_token}",
            "Content-Type": "application/json",
        }

    async def _post(
        self,
        url: str,
        *,
        headers: Dict[str, str],
        json: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a POST request and return the parsed JSON body.

        Args:
            url: The request URL.
            headers: Request headers.
            json: JSON-serialisable request body.

        Returns:
            Parsed JSON response dict (may be empty for 204 responses).

        Raises:
            RuntimeError: If the client session is not initialised.
            aiohttp.ClientResponseError: On non-2xx responses.
        """
        if self._session is None:
            raise RuntimeError(
                "LiveAvatarClient has no active aiohttp session. "
                "Use 'async with LiveAvatarClient(cfg) as client:' or "
                "call __aenter__ before using the client."
            )
        async with self._session.post(url, headers=headers, json=json) as resp:
            resp.raise_for_status()
            if resp.content_type == "application/json":
                return await resp.json()  # type: ignore[no-any-return]
            return {}

    async def _get(
        self,
        url: str,
        *,
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        """Execute a GET request and return the parsed JSON body.

        Args:
            url: The request URL.
            headers: Request headers (typically ``X-API-KEY`` auth).

        Returns:
            Parsed JSON response dict (may be empty for 204 responses).

        Raises:
            RuntimeError: If the client session is not initialised.
            aiohttp.ClientResponseError: On non-2xx responses.
        """
        if self._session is None:
            raise RuntimeError(
                "LiveAvatarClient has no active aiohttp session. "
                "Use 'async with LiveAvatarClient(cfg) as client:' or "
                "call __aenter__ before using the client."
            )
        async with self._session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            if resp.content_type == "application/json":
                return await resp.json()  # type: ignore[no-any-return]
            return {}

    def _start_keep_alive(self, handle: AvatarSessionHandle) -> None:
        """Start the background keep-alive task.

        Cancels any existing task before creating a new one.

        Args:
            handle: The active session handle.
        """
        self._cancel_keep_alive()
        self._keep_alive_task = asyncio.create_task(
            self._keep_alive_loop(handle),
            name=f"liveavatar-keepalive-{handle.liveavatar_session_id}",
        )

    def _cancel_keep_alive(self) -> None:
        """Cancel the keep-alive task (fire-and-forget, used before restart).

        Synchronous best-effort cancel for the "cancel then immediately
        re-create" path in :meth:`_start_keep_alive`.  Teardown paths must use
        :meth:`_acancel_keep_alive` instead so the cancellation is awaited.
        """
        if self._keep_alive_task is not None and not self._keep_alive_task.done():
            self._keep_alive_task.cancel()
        self._keep_alive_task = None

    async def _acancel_keep_alive(self) -> None:
        """Cancel the keep-alive task AND await its termination.

        Awaiting guarantees the loop has fully unwound (and cannot fire a ping
        against a closing aiohttp session) before teardown continues.
        """
        task = self._keep_alive_task
        self._keep_alive_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _keep_alive_loop(self, handle: AvatarSessionHandle) -> None:
        """Background coroutine that sends periodic keep-alive pings.

        Runs every :data:`_KEEP_ALIVE_INTERVAL` seconds (< 5 min inactivity
        timeout) until cancelled.

        Args:
            handle: The active session handle.
        """
        try:
            while True:
                await asyncio.sleep(_KEEP_ALIVE_INTERVAL)
                await self.keep_alive(handle)
        except asyncio.CancelledError:
            self.logger.debug(
                "LiveAvatarClient: keep-alive loop cancelled for %s",
                handle.liveavatar_session_id,
            )
