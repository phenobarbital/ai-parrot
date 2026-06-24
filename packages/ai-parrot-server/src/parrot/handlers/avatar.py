"""Avatar session endpoint — start/stop/viewers for an avatar session (FEAT-242, FEAT-249).

Additional endpoint for Mode C (multi-viewer LITE):

    POST /api/v1/avatar/{agent_id}/viewers
        For an active LITE session, mint up to ``count`` additional subscribe-only
        viewer tokens and return them as a list. No secrets are ever returned.


Provides authenticated REST endpoints for the LiveAvatar LITE avatar session:

    POST /api/v1/agents/avatar/{agent_id}/start
        Start an avatar session for the named agent.  Returns viewer credentials
        ONLY (``livekit_url``, ``client_token``, ``session_id``).  The
        ``agent_token``, ``ws_url`` and ``session_token`` are NEVER returned to
        the client.  The live :class:`LiveAvatarClient` (with its keep-alive
        loop) is kept alive and stored in ``app['avatar_sessions']`` so the
        matching ``/stop`` can tear it down.

    POST /api/v1/agents/avatar/{agent_id}/stop
        Stop an active avatar session by ``session_id``: stops the LiveAvatar
        session, cancels the keep-alive loop, and closes the HTTP client.

Both endpoints are served through :class:`AvatarSessionView`, a
``navigator.views.BaseView`` decorated with ``@is_authenticated()`` and
``@user_session()`` (mirrors :class:`AgentTalk`) — so an unauthenticated caller
can neither start nor stop a session.

Integration with ``AgentVoiceTalk``:
The avatar mode is exposed as a request flag (``avatar=true``) on the voice
endpoint.  A separate POST to ``/api/v1/agents/avatar/{agent_id}/start``
pre-starts the avatar session and returns viewer credentials that the browser
uses to join the LiveKit room; the browser still calls the voice endpoint as
normal for the actual dialogue.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List, Optional

from aiohttp import web, ClientResponseError
from navconfig.logging import logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session

# Lazy imports of the liveavatar stack happen inside the handlers so server
# boot never hard-requires the optional ``ai-parrot-integrations[liveavatar]``
# extra.

_logger = logging.getLogger("Parrot.AvatarSessionView")

# Key under which active avatar sessions are stored on the aiohttp Application.
# Maps session_id -> {"client": LiveAvatarClient, "handle": AvatarSessionHandle}.
AVATAR_SESSIONS_KEY = "avatar_sessions"


def _env_max_session_duration() -> Optional[int]:
    """Read the optional ``LIVEAVATAR_MAX_SESSION_DURATION`` env (seconds).

    Returns:
        The parsed integer, or ``None`` if unset/invalid.  Used as a safety-net
        backstop so abandoned sessions self-terminate server-side.
    """
    raw = os.environ.get("LIVEAVATAR_MAX_SESSION_DURATION", "")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        _logger.warning("Invalid LIVEAVATAR_MAX_SESSION_DURATION=%r; ignoring.", raw)
        return None


async def _resolve_avatar_id(
    request: web.Request,
    agent_id: str,
    body: Dict[str, Any],
) -> str:
    """Resolve the LiveAvatar ``avatar_id`` for this request.

    Per-agent avatar selection (rather than the single global
    ``LIVEAVATAR_AVATAR_ID``).  Resolution order, first non-empty wins:

    1. **Request body** — an explicit ``avatar_id`` in the POST payload lets a
       caller override the avatar for a single session.
    2. **Per-agent stored config** — ``avatar_id`` under the agent's
       :class:`BotConfig.config` dict (Redis-backed ``bot_config_storage``),
       so each agent can pin its own avatar declaratively.
    3. **Environment** — the global ``LIVEAVATAR_AVATAR_ID`` fallback (legacy
       behaviour, used when neither override is present).

    Args:
        request: The incoming aiohttp request (carries ``app`` for storage).
        agent_id: The agent slug from the URL path.
        body: The already-parsed JSON request body.

    Returns:
        The resolved avatar ID, or ``""`` if no source provides one.
    """
    # 1. Explicit per-call override from the request body.
    body_avatar = str(body.get("avatar_id") or "").strip()
    if body_avatar:
        _logger.debug("avatar_id resolved from request body for agent %s", agent_id)
        return body_avatar

    # 2. Per-agent declarative config (BotConfig.config["avatar_id"]).
    storage = request.app.get("bot_config_storage")
    if storage is not None:
        try:
            bot_config = await storage.get(agent_id)
        except Exception as exc:  # noqa: BLE001 — config lookup must never 500 the start
            _logger.warning(
                "avatar_id config lookup failed for agent %s: %s", agent_id, exc
            )
            bot_config = None
        if bot_config is not None:
            cfg_avatar = str((bot_config.config or {}).get("avatar_id") or "").strip()
            if cfg_avatar:
                _logger.debug(
                    "avatar_id resolved from BotConfig for agent %s", agent_id
                )
                return cfg_avatar

    # 3. Global env fallback (legacy single-avatar behaviour).
    return os.environ.get("LIVEAVATAR_AVATAR_ID", "").strip()


def _is_no_credits_error(exc: ClientResponseError) -> bool:
    """Return True when the LiveAvatar error maps to the no-credits case.

    Reuses the same detection logic as :func:`avatar_upstream_error_response`
    so the auto-fallback trigger is consistent with the error mapping.

    Args:
        exc: The upstream :class:`aiohttp.ClientResponseError`.

    Returns:
        ``True`` if the error indicates no avatar credits (code 4033 or
        "credit" in the message).
    """
    message = str(getattr(exc, "message", "") or "")
    return "4033" in message or "credit" in message.lower()


async def _start_direct_audio_session(
    tokens: Any,
    session_id: str,
    store: Dict[str, Any],
) -> web.Response:
    """Start an avatar-OFF session using a direct LiveKit audio publisher.

    Shared by the ``avatar=false`` path and the 402 auto-fallback path.
    Creates a :class:`~parrot.integrations.liveavatar.room_audio_publisher.RoomAudioPublisher`,
    stores it in ``store``, and returns the standard viewer-credentials response.

    Args:
        tokens: :class:`~parrot.integrations.liveavatar.models.LiveKitRoomTokens`
            from :func:`~parrot.integrations.liveavatar.room_manager.LiveKitRoomManager.mint_room_tokens`.
        session_id: The shared session ID.
        store: The ``app[AVATAR_SESSIONS_KEY]`` dict (mutated in-place).

    Returns:
        200 JSON response with ``livekit_url``, ``client_token``, ``session_id``.
    """
    try:
        from parrot.integrations.liveavatar.room_audio_publisher import RoomAudioPublisher
    except ImportError as exc:
        _logger.warning("RoomAudioPublisher unavailable: %s", exc)
        raise web.HTTPServiceUnavailable(
            reason="livekit realtime SDK not installed (liveavatar extra)"
        ) from exc

    publisher = await RoomAudioPublisher.start(tokens)
    # Store under "publisher" key (avatar-OFF record).  /stop and shutdown
    # detect this key and call publisher.aclose() instead of client teardown.
    store[session_id] = {"publisher": publisher}

    _logger.info(
        "AvatarSessionView: started direct-audio session %s (avatar-OFF)",
        session_id,
    )
    return web.json_response({
        "livekit_url": tokens.livekit_url,
        "client_token": tokens.client_token,
        "session_id": session_id,
    })


async def _start_avatar_session(request: web.Request) -> web.Response:
    """POST /api/v1/agents/avatar/{agent_id}/start — start an avatar session.

    Reads LiveAvatar / LiveKit credentials from env, mints room tokens, and
    selects the audio mode based on the ``avatar`` flag in the request body:

    - ``avatar=true`` (default, back-compat): creates and starts a LiveAvatar
      LITE session (with ``livekit_config``), keeps the client alive in
      ``app['avatar_sessions']``.
    - ``avatar=false``: skips LiveAvatar entirely; starts a
      :class:`~parrot.integrations.liveavatar.room_audio_publisher.RoomAudioPublisher`
      (direct LiveKit audio track) and stores it in ``app['avatar_sessions']``.
    - **Auto-fallback**: if ``avatar=true`` but LiveAvatar returns a no-credits
      error (402 / code 4033), silently falls back to the publisher path and
      returns a **200** (not 402) so the session starts normally.

    Request body (JSON):
        session_id (str): AgentChat session ID (shared with the browser).
        tenant_id  (str, optional): Tenant identifier for opt-in gating.
        avatar_id  (str, optional): Override the avatar for this session.
        avatar     (bool, optional): Enable avatar (default True).

    Response (JSON):
        livekit_url  (str): LiveKit WebSocket URL for the browser.
        client_token (str): Subscribe-only viewer JWT.
        session_id   (str): The shared session ID.

    The ``agent_token``, ``ws_url`` and ``session_token`` are NEVER serialised.
    """
    try:
        from parrot.integrations.liveavatar import (
            LiveAvatarClient,
            LiveAvatarConfig,
            LiveKitRoomManager,
        )
        from parrot.integrations.liveavatar.optin import is_avatar_enabled
    except ImportError as exc:
        _logger.warning("LiveAvatar stack unavailable: %s", exc)
        raise web.HTTPServiceUnavailable(
            reason="LiveAvatar stack not installed"
        ) from exc

    agent_id = request.match_info["agent_id"]

    try:
        body: Dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    session_id: str = body.get("session_id") or ""
    tenant_id: Optional[str] = body.get("tenant_id") or None

    if not session_id:
        raise web.HTTPBadRequest(reason="'session_id' is required")

    # Per-tenant opt-in gate (wired by TASK-008)
    if not is_avatar_enabled(tenant_id=tenant_id, agent_name=agent_id):
        raise web.HTTPForbidden(reason="Avatar mode is not enabled for this tenant")

    # NEW (FEAT-256): read the avatar flag (default True for back-compat).
    avatar_raw = body.get("avatar", True)
    if isinstance(avatar_raw, str):
        avatar_flag: bool = avatar_raw.lower() not in ("false", "0", "no")
    else:
        avatar_flag = bool(avatar_raw)

    room_manager = LiveKitRoomManager()  # reads LIVEKIT_* from env

    # Mint viewer + agent tokens.  JWT signing is sync CPU work — keep it off
    # the event loop.
    tokens = await asyncio.to_thread(room_manager.mint_room_tokens, session_id, agent_id)

    store = request.app.setdefault(AVATAR_SESSIONS_KEY, {})

    # ── avatar-OFF path: start a direct-audio publisher ──────────────────
    if not avatar_flag:
        _logger.info(
            "AvatarSessionView: avatar=false for session %s — using direct audio",
            session_id,
        )
        return await _start_direct_audio_session(tokens, session_id, store)

    # ── avatar-ON path: LiveAvatar LITE (with optional 402 auto-fallback) ─

    # api_key stays a global secret; avatar_id is resolved per-agent
    # (body > BotConfig > env). is_sandbox remains a global env switch.
    api_key = os.environ.get("LIVEAVATAR_API_KEY", "")
    avatar_id = await _resolve_avatar_id(request, agent_id, body)
    if not api_key or not avatar_id:
        raise web.HTTPServiceUnavailable(
            reason="LIVEAVATAR_API_KEY / LIVEAVATAR_AVATAR_ID env vars are not set"
        )

    cfg = LiveAvatarConfig(
        api_key=api_key,
        avatar_id=avatar_id,
        base_url=os.environ.get("LIVEAVATAR_BASE_URL", "https://api.liveavatar.com"),
        is_sandbox=os.environ.get("LIVEAVATAR_SANDBOX", "true").lower() != "false",
        # Safety-net backstop so an abandoned session self-terminates even if
        # /stop is never called.
        max_session_duration=_env_max_session_duration(),
    )

    # Field names match LiveAvatar's LiveKitConfigSchema (snake_case).  The
    # avatar joins our room as a publisher, so it receives the publish-capable
    # ``agent_token`` (the subscribe-only client_token stays with the browser).
    livekit_config: Dict[str, Any] = {
        "livekit_url": tokens.livekit_url,
        "livekit_room": tokens.room,
        "livekit_client_token": tokens.agent_token,
    }

    # Open the client and KEEP IT ALIVE — ownership transfers to the session
    # store; /stop tears it down.  We deliberately do NOT use ``async with``
    # here (that would call stop_session on block exit and kill the session
    # before the browser ever joins).
    client = LiveAvatarClient(cfg)
    await client.aopen()
    try:
        handle = await client.create_session_token(cfg, livekit_config=livekit_config)
        # create_session_token leaves session_id empty (it is the ai-parrot id,
        # unknown to the HTTP layer) — populate it now.
        handle.session_id = session_id
        handle.tenant_id = tenant_id
        await client.start_session(handle)
    except ClientResponseError as exc:
        # Close the client before any further action.
        try:
            await client.aclose()
        finally:
            pass
        if _is_no_credits_error(exc):
            # AUTO-FALLBACK (FEAT-256): LiveAvatar has no credits but the
            # session should still start using the direct-audio publisher.
            _logger.warning(
                "AvatarSessionView: LiveAvatar no credits for session %s — "
                "auto-fallback to direct audio",
                session_id,
            )
            return await _start_direct_audio_session(tokens, session_id, store)
        # Other upstream errors: return the clean error response.
        _logger.warning(
            "AvatarSessionView: LiveAvatar start failed for session %s: %s",
            session_id,
            getattr(exc, "message", exc),
        )
        return avatar_upstream_error_response(exc)
    except Exception:
        # On any failure, do not leak the client/session.
        try:
            await client.aclose()
        finally:
            pass
        raise

    # Register the live session so /stop (and shutdown cleanup) can reach it.
    store[session_id] = {"client": client, "handle": handle}

    _logger.info(
        "AvatarSessionView: started session %s for agent %s (tenant set=%s)",
        session_id,
        agent_id,
        tenant_id is not None,
    )

    # Return viewer credentials ONLY — agent_token / ws_url / session_token
    # stay server-side.
    return web.json_response({
        "livekit_url": tokens.livekit_url,
        "client_token": tokens.client_token,
        "session_id": session_id,
    })


def avatar_upstream_error_response(exc: ClientResponseError) -> web.Response:
    """Translate a LiveAvatar upstream error into a clean JSON response.

    Without this, the upstream ``ClientResponseError`` propagates and aiohttp
    returns a bare ``500`` whose body does NOT carry the reason — the frontend
    cannot tell "no credits" from a real server bug.  Map the two cases the
    frontend acts on:

      * "No credits" (LiveAvatar code ``4033`` / ``403``) -> ``402`` so the UI
        can show an actionable "avatar has no credits" message.
      * Any other upstream failure -> ``502`` (provider error).
    """
    message = str(getattr(exc, "message", "") or "")
    if "4033" in message or "credit" in message.lower():
        return web.json_response(
            {
                "error": "avatar_no_credits",
                "message": "No credits available for the avatar session.",
            },
            status=402,
        )
    return web.json_response(
        {
            "error": "avatar_upstream_error",
            "message": message or "The avatar provider returned an error.",
        },
        status=502,
    )


async def _stop_avatar_session(request: web.Request) -> web.Response:
    """POST /api/v1/agents/avatar/{agent_id}/stop — stop an active avatar session.

    Identifies the session by ``session_id`` ONLY.  The ``session_token`` is a
    server-side secret and is never accepted from the client.

    Request body (JSON):
        session_id (str): The session to stop.

    Response: 204 No Content (idempotent — unknown/expired sessions also 204).
    """
    try:
        body: Dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    session_id: str = body.get("session_id") or ""
    if not session_id:
        raise web.HTTPBadRequest(reason="'session_id' is required")

    # Tear down a stored viewer session if one exists.
    store: Dict[str, Any] = request.app.get(AVATAR_SESSIONS_KEY, {})
    record = store.pop(session_id, None)
    if not record:
        # Nothing more to stop (already closed / unknown) — idempotent success.
        _logger.debug(
            "AvatarSessionView: no active session for %s (idempotent)", session_id
        )
        return web.Response(status=204)

    publisher = record.get("publisher")
    client = record.get("client")
    handle = record.get("handle")

    if publisher is not None:
        # avatar-OFF path: disconnect the room publisher (FEAT-256).
        # aclose is idempotent and never raises.
        await publisher.aclose()
    elif client is not None and handle is not None:
        # avatar-ON path: stop LiveAvatar session + close client.
        try:
            await client.stop_session(handle)
        finally:
            # aclose cancels (and awaits) the keep-alive loop and closes the
            # HTTP session even if stop_session raised.
            await client.aclose()

    _logger.info("AvatarSessionView: stopped session %s", session_id)
    return web.Response(status=204)


@is_authenticated()
@user_session()
class AvatarSessionView(BaseView):
    """Authenticated entrypoint for the avatar start/stop actions.

    Routed at ``/api/v1/agents/avatar/{agent_id}/{action}`` where ``action`` is
    ``start`` or ``stop``.  Authentication/session decorators match
    :class:`AgentTalk`, so unauthenticated callers are rejected before any
    avatar session is created or destroyed.
    """

    async def post(self) -> web.Response:
        action = self.request.match_info.get("action", "")
        if action == "start":
            return await _start_avatar_session(self.request)
        if action == "stop":
            return await _stop_avatar_session(self.request)
        raise web.HTTPNotFound(reason=f"unknown avatar action '{action}'")


async def close_all_avatar_sessions(app: web.Application) -> None:
    """Best-effort teardown of any lingering avatar sessions on shutdown.

    Registered as an ``on_cleanup`` callback by the bot manager.  Iterates the
    session store, stops each LiveAvatar session or direct-audio publisher
    (FEAT-256 avatar-OFF path) and closes its client.
    """
    store: Dict[str, Any] = app.get(AVATAR_SESSIONS_KEY, {})
    for session_id, record in list(store.items()):
        publisher = record.get("publisher")
        client = record.get("client")
        handle = record.get("handle")
        if publisher is not None:
            # avatar-OFF: disconnect the room publisher.
            try:
                await publisher.aclose()
            except Exception:  # noqa: BLE001
                _logger.warning(
                    "Failed closing publisher for session %s on shutdown",
                    session_id,
                    exc_info=True,
                )
        elif client is not None and handle is not None:
            # avatar-ON: stop LiveAvatar session + close client.
            try:
                await client.stop_session(handle)
            except Exception:  # noqa: BLE001
                _logger.warning(
                    "Failed stopping avatar session %s on shutdown",
                    session_id,
                    exc_info=True,
                )
            finally:
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001
                    pass
    store.clear()


_VIEWERS_MAX_COUNT = 50
_VIEWERS_MIN_COUNT = 1


async def _mint_viewer_tokens(request: web.Request) -> web.Response:
    """POST /api/v1/avatar/{agent_id}/viewers — mint extra subscribe-only viewer tokens.

    For an existing LITE session identified by ``session_id``, mints ``count``
    additional subscribe-only tokens with distinct viewer identities so multiple
    browsers can watch the same avatar stream simultaneously (Mode C).

    Request body (JSON):
        session_id (str): The active LITE session ID (must be in avatar_sessions store).
        count (int, optional): Number of tokens to mint (1–50). Default 1.

    Response (JSON):
        viewers: list of {identity, livekit_url, client_token}

    The ``agent_token`` is NEVER returned.
    """
    try:
        from parrot.integrations.liveavatar import LiveKitRoomManager
    except ImportError as exc:
        _logger.warning("LiveAvatar stack unavailable: %s", exc)
        raise web.HTTPServiceUnavailable(
            reason="LiveAvatar stack not installed"
        ) from exc

    try:
        body: Dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    session_id: str = body.get("session_id") or ""
    if not session_id:
        raise web.HTTPBadRequest(reason="'session_id' is required")

    raw_count = body.get("count", 1)
    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(reason="'count' must be an integer")

    if count < _VIEWERS_MIN_COUNT or count > _VIEWERS_MAX_COUNT:
        raise web.HTTPBadRequest(
            reason=f"'count' must be between {_VIEWERS_MIN_COUNT} and {_VIEWERS_MAX_COUNT}"
        )

    # Verify the session exists
    store: Dict[str, Any] = request.app.get(AVATAR_SESSIONS_KEY, {})
    record = store.get(session_id)
    if not record:
        raise web.HTTPNotFound(reason=f"No active avatar session for session_id '{session_id}'")

    # Room name is the session_id (mirrors _start_avatar_session)
    room = session_id
    try:
        room_manager = LiveKitRoomManager()
    except KeyError as exc:
        raise web.HTTPServiceUnavailable(
            reason="LIVEKIT_* env vars are not configured"
        ) from exc

    # Mint all viewer tokens in parallel — each call is pure CPU/crypto work
    # (JWT sign), so asyncio.gather gives a ~count× speedup for large batches.
    identities = [f"viewer-{i}-{uuid.uuid4().hex[:8]}" for i in range(count)]

    async def _mint_one(identity: str) -> Dict[str, str]:
        tokens = await asyncio.to_thread(room_manager.mint_room_tokens, room, identity)
        return {
            "identity": identity,
            "livekit_url": tokens.livekit_url,
            "client_token": tokens.client_token,  # subscribe-only; never agent_token
        }

    viewers: List[Dict[str, str]] = list(
        await asyncio.gather(*(_mint_one(ident) for ident in identities))
    )

    _logger.info(
        "AvatarViewersView: minted %d viewer token(s) for session %s",
        count,
        session_id,
    )
    return web.json_response({"viewers": viewers})


@is_authenticated()
@user_session()
class AvatarViewersView(BaseView):
    """Authenticated endpoint to mint extra subscribe-only viewer tokens (Mode C).

    Routed at ``POST /api/v1/avatar/{agent_id}/viewers``.  Authentication mirrors
    :class:`AvatarSessionView` — only authenticated callers may mint viewer tokens.
    """

    async def post(self) -> web.Response:
        return await _mint_viewer_tokens(self.request)


def register_avatar_routes(router: Any) -> bool:
    """Register avatar session endpoints on the provided aiohttp router.

    Follows the same defensive-import pattern used by ``_register_voice_routes``
    in ``manager.py``.  Routes are served through the authenticated
    :class:`AvatarSessionView`.

    Args:
        router: The aiohttp ``UrlDispatcher`` to register routes on.

    Returns:
        ``True`` if routes were registered, ``False`` if the stack is missing.
    """
    try:
        import parrot.integrations.liveavatar  # noqa: F401
    except ImportError as exc:
        _logger.warning(
            "Avatar endpoints disabled (%s); install "
            "'ai-parrot-integrations[liveavatar]' to enable "
            "POST /api/v1/agents/avatar/{agent_id}/start.",
            exc,
        )
        return False

    router.add_view(
        "/api/v1/agents/avatar/{agent_id}/{action}",
        AvatarSessionView,
    )
    # Mode C: multi-viewer token endpoint (FEAT-249).
    router.add_view(
        "/api/v1/avatar/{agent_id}/viewers",
        AvatarViewersView,
    )
    _logger.info("Avatar session routes registered (authenticated).")
    return True
