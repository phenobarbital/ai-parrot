"""FULL Mode avatar endpoint — start/stop sessions and list avatars/voices (FEAT-248).

Provides REST endpoints for the LiveAvatar FULL mode avatar session:

    POST /api/v1/avatar/fullmode/{agent_id}/start
        Start a FULL mode avatar session.  Returns viewer credentials ONLY
        (``session_id``, ``livekit_url``, ``livekit_client_token``).  The
        ``session_token`` and any server-side secrets are NEVER returned.
        The live :class:`LiveAvatarClient` (with its keep-alive loop) is
        kept alive and stored in ``app[FULLMODE_SESSIONS_KEY]`` so the
        matching ``/stop`` can tear it down.

    POST /api/v1/avatar/fullmode/{agent_id}/stop
        Stop an active FULL mode session by ``session_id``: stops the
        LiveAvatar session, cancels the keep-alive loop, and closes the
        HTTP client.  Idempotent — unknown/expired sessions return 204.

    GET /api/v1/avatar/avatars
        List available avatars (stock + user-uploaded) from the LiveAvatar API.

    GET /api/v1/avatar/voices
        List available voices from the LiveAvatar API.

    GET /api/v1/avatar/session/{session_id}/transcript
        Retrieve the server-side transcript for a completed FULL mode session.

All FULL mode session management is separate from the LITE phase (``avatar.py``)
and uses a dedicated session store key ``FULLMODE_SESSIONS_KEY``.  The opt-in
gate uses ``is_fullmode_enabled()`` (a superset of ``is_avatar_enabled()``).

Lazy imports of the liveavatar stack happen inside the handlers so server
boot never hard-requires the optional ``ai-parrot-integrations[liveavatar]``
extra.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from aiohttp import web, ClientResponseError

from .avatar import avatar_upstream_error_response
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session

_logger = logging.getLogger("Parrot.AvatarFullmodeView")

# Key under which active FULL mode sessions are stored on the aiohttp Application.
# Maps session_id -> {"client": LiveAvatarClient, "handle": FullModeSessionHandle}.
# Kept separate from Phase A LITE sessions (AVATAR_SESSIONS_KEY in avatar.py) so
# the two modes never interfere.
FULLMODE_SESSIONS_KEY = "avatar_fullmode_sessions"

# Optional override for the public-facing base URL used to build
# `custom_llm_url` (FEAT-247 TASK-1875). When unset, the base URL is derived
# from the incoming request (`{scheme}://{host}`), which is correct for
# direct deployments but may be wrong behind certain reverse-proxy setups
# that do not forward scheme/host faithfully.
OPENAI_COMPAT_BASE_URL_ENV = "OPENAI_COMPAT_BASE_URL"


# ---------------------------------------------------------------------------
# Start / Stop handlers (TASK-1594)
# ---------------------------------------------------------------------------


async def _start_fullmode_session(request: web.Request) -> web.Response:
    """POST /api/v1/avatar/fullmode/{agent_id}/start — start a FULL mode session.

    Resolves per-tenant configuration, runs the opt-in gate, creates and starts
    a LiveAvatar FULL mode session (restricted — no LLM, no context), keeps the
    client alive in ``app[FULLMODE_SESSIONS_KEY]``, and returns viewer credentials.

    Request body (JSON):
        session_id (str): AgentChat session ID (shared with the browser). Required.
        tenant_id  (str, optional): Tenant identifier for opt-in gating.
        agent_name (str, optional): Logical agent name for logging (defaults to
            the ``agent_id`` path parameter).
        avatar_id  (str, optional): Per-request avatar override. When provided it
            takes precedence over the resolved config's ``avatar_id`` (the
            ``LIVEAVATAR_AVATAR_ID`` env default). When omitted, the configured
            default avatar is used.

    Response (JSON):
        session_id          (str): The shared session ID.
        livekit_url         (str): LiveKit Cloud WebSocket URL for the browser.
        livekit_client_token (str): Browser viewer JWT from the FULL mode /start.
        custom_llm_url       (str): Per-session OpenAI-compat endpoint
            (FEAT-247) — ``{base}/v1/chat/completions/{session_id}?agent={agent_id}``
            — for the frontend to pass to LiveAvatar's Custom LLM configuration.

    The ``session_token`` and any other server-side secrets are NEVER returned.
    """
    try:
        from parrot.integrations.liveavatar.client import LiveAvatarClient
        from parrot.integrations.liveavatar.optin import is_fullmode_enabled
        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config
    except ImportError as exc:
        _logger.warning("LiveAvatar stack unavailable: %s", exc)
        raise web.HTTPServiceUnavailable(
            reason="LiveAvatar stack not installed"
        ) from exc

    agent_id = request.match_info.get("agent_id", "")

    try:
        body: Dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    session_id: str = body.get("session_id") or ""
    tenant_id: Optional[str] = body.get("tenant_id") or None
    agent_name: str = body.get("agent_name") or agent_id
    avatar_id: Optional[str] = (body.get("avatar_id") or "").strip() or None

    if not session_id:
        raise web.HTTPBadRequest(reason="'session_id' is required")

    # Guard against concurrent /start calls for the same session_id — two
    # simultaneous requests would each open a LiveAvatarClient and the second
    # would overwrite the first, leaving an orphaned keep-alive loop.
    store = request.app.setdefault(FULLMODE_SESSIONS_KEY, {})
    if session_id in store:
        raise web.HTTPConflict(
            reason=f"A FULL mode session for '{session_id}' is already active"
        )

    # Per-tenant FULL mode opt-in gate (superset of is_avatar_enabled).
    if not is_fullmode_enabled(tenant_id=tenant_id, agent_name=agent_name):
        raise web.HTTPForbidden(
            reason="FULL mode avatar is not enabled for this tenant"
        )

    # Resolve config from env (+ future DB overrides).
    try:
        cfg = await resolve_fullmode_config(tenant_id=tenant_id)
    except RuntimeError as exc:
        _logger.warning("LiveAvatar config error: %s", exc)
        raise web.HTTPServiceUnavailable(
            reason="LiveAvatar configuration is incomplete — check LIVEAVATAR_* env vars"
        ) from exc

    # Per-request avatar override: a client may pick a specific avatar for this
    # session. When present, it wins over the env/config default; otherwise the
    # resolved config's avatar_id is used.
    if avatar_id:
        cfg = cfg.model_copy(update={"avatar_id": avatar_id})

    # Open the client and KEEP IT ALIVE — ownership transfers to the session
    # store; /stop tears it down.  We deliberately do NOT use ``async with``
    # here (that would call stop_session on block exit and kill the session
    # before the browser ever joins).
    client = LiveAvatarClient(cfg)
    await client.aopen()
    try:
        handle = await client.create_full_session_token(cfg)
        # create_full_session_token leaves session_id empty (it is the ai-parrot
        # id, unknown to the HTTP layer) — populate it now.
        handle.session_id = session_id
        handle.tenant_id = tenant_id
        await client.start_session(handle)
    except ClientResponseError as exc:
        # Upstream LiveAvatar rejected the start (e.g. no credits). Close the
        # client and return a clean, machine-readable status the frontend can
        # act on instead of leaking a bare 500.
        await client.aclose()
        _logger.warning(
            "AvatarFullmode: LiveAvatar start failed for session %s: %s",
            session_id,
            getattr(exc, "message", exc),
        )
        return avatar_upstream_error_response(exc)
    except Exception:
        # On any failure, do not leak the client/session.
        await client.aclose()
        raise

    # Register the live session so /stop (and shutdown cleanup) can reach it.
    store[session_id] = {"client": client, "handle": handle}

    _logger.info(
        "AvatarFullmode: started session %s for agent %s (tenant set=%s, avatar=%s%s)",
        session_id,
        agent_id,
        tenant_id is not None,
        cfg.avatar_id,
        " [request override]" if avatar_id else " [config default]",
    )

    # FEAT-247 (TASK-1875): mint the per-session OpenAI-compat URL so the
    # frontend can pass it to LiveAvatar's Custom LLM configuration. Prefers
    # OPENAI_COMPAT_BASE_URL when configured (public-facing URL may differ
    # from request.host behind some reverse proxies); falls back to the
    # incoming request's scheme/host otherwise.
    base_url = os.environ.get(OPENAI_COMPAT_BASE_URL_ENV) or (
        f"{request.scheme}://{request.host}"
    )
    custom_llm_url = f"{base_url}/v1/chat/completions/{session_id}?agent={agent_id}"

    # Return viewer credentials ONLY — session_token stays server-side.
    return web.json_response({
        "session_id": session_id,
        "livekit_url": handle.livekit_url,
        "livekit_client_token": handle.livekit_client_token,
        "custom_llm_url": custom_llm_url,
    })


async def _stop_fullmode_session(request: web.Request) -> web.Response:
    """POST /api/v1/avatar/fullmode/{agent_id}/stop — stop a FULL mode session.

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

    store: Dict[str, Any] = request.app.get(FULLMODE_SESSIONS_KEY, {})
    record = store.pop(session_id, None)
    if not record:
        # Nothing to stop — idempotent success.
        _logger.debug(
            "AvatarFullmode: no active session for %s (idempotent stop)", session_id
        )
        return web.Response(status=204)

    client = record["client"]
    handle = record["handle"]
    try:
        await client.stop_session(handle)
    finally:
        # aclose cancels (and awaits) the keep-alive loop and closes the HTTP
        # session even if stop_session raised.
        await client.aclose()

    _logger.info("AvatarFullmode: stopped session %s", session_id)
    return web.Response(status=204)


# ---------------------------------------------------------------------------
# Avatar / Voice listing handlers (TASK-1595)
# ---------------------------------------------------------------------------


async def _list_avatars(request: web.Request) -> web.Response:
    """GET /api/v1/avatar/avatars — list available avatars.

    Proxies ``LiveAvatarClient.list_avatars()`` using global env config.
    No avatar opt-in required — this is a read-only discovery endpoint.

    Query parameters:
        tenant_id (str, optional): Tenant identifier for per-tenant API key
            resolution (future DB layer).

    Response (JSON):
        {"avatars": [list of avatar dicts from the LiveAvatar API]}
    """
    try:
        from parrot.integrations.liveavatar.client import LiveAvatarClient
        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config
    except ImportError as exc:
        _logger.warning("LiveAvatar stack unavailable: %s", exc)
        raise web.HTTPServiceUnavailable(
            reason="LiveAvatar stack not installed"
        ) from exc

    tenant_id: Optional[str] = request.rel_url.query.get("tenant_id") or None

    try:
        cfg = await resolve_fullmode_config(tenant_id=tenant_id)
    except RuntimeError as exc:
        _logger.warning("LiveAvatar config error: %s", exc)
        raise web.HTTPServiceUnavailable(
            reason="LiveAvatar configuration is incomplete — check LIVEAVATAR_* env vars"
        ) from exc

    try:
        async with LiveAvatarClient(cfg) as client:
            avatars = await client.list_avatars(cfg)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("LiveAvatar list_avatars error: %s", exc)
        raise web.HTTPInternalServerError(
            reason="Failed to retrieve avatar list from LiveAvatar API"
        ) from exc

    return web.json_response({"avatars": avatars})


async def _list_voices(request: web.Request) -> web.Response:
    """GET /api/v1/avatar/voices — list available voices.

    Proxies ``LiveAvatarClient.list_voices()`` using global env config.
    No avatar opt-in required — this is a read-only discovery endpoint.

    Query parameters:
        tenant_id (str, optional): Tenant identifier for per-tenant API key
            resolution (future DB layer).

    Response (JSON):
        {"voices": [list of voice dicts from the LiveAvatar API]}
    """
    try:
        from parrot.integrations.liveavatar.client import LiveAvatarClient
        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config
    except ImportError as exc:
        _logger.warning("LiveAvatar stack unavailable: %s", exc)
        raise web.HTTPServiceUnavailable(
            reason="LiveAvatar stack not installed"
        ) from exc

    tenant_id: Optional[str] = request.rel_url.query.get("tenant_id") or None

    try:
        cfg = await resolve_fullmode_config(tenant_id=tenant_id)
    except RuntimeError as exc:
        _logger.warning("LiveAvatar config error: %s", exc)
        raise web.HTTPServiceUnavailable(
            reason="LiveAvatar configuration is incomplete — check LIVEAVATAR_* env vars"
        ) from exc

    try:
        async with LiveAvatarClient(cfg) as client:
            voices = await client.list_voices(cfg)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("LiveAvatar list_voices error: %s", exc)
        raise web.HTTPInternalServerError(
            reason="Failed to retrieve voice list from LiveAvatar API"
        ) from exc

    return web.json_response({"voices": voices})


async def _get_session_transcript(request: web.Request) -> web.Response:
    """GET /api/v1/avatar/session/{session_id}/transcript — get session transcript.

    Proxies ``LiveAvatarClient.get_session_transcript()`` for a completed
    FULL mode session.

    Response (JSON):
        Transcript dict from the LiveAvatar API.
    """
    try:
        from parrot.integrations.liveavatar.client import LiveAvatarClient
        from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config
    except ImportError as exc:
        _logger.warning("LiveAvatar stack unavailable: %s", exc)
        raise web.HTTPServiceUnavailable(
            reason="LiveAvatar stack not installed"
        ) from exc

    liveavatar_session_id: str = request.match_info.get("session_id", "")
    if not liveavatar_session_id:
        raise web.HTTPBadRequest(reason="'session_id' path parameter is required")

    try:
        cfg = await resolve_fullmode_config()
    except RuntimeError as exc:
        _logger.warning("LiveAvatar config error: %s", exc)
        raise web.HTTPServiceUnavailable(
            reason="LiveAvatar configuration is incomplete — check LIVEAVATAR_* env vars"
        ) from exc

    try:
        async with LiveAvatarClient(cfg) as client:
            transcript = await client.get_session_transcript(cfg, liveavatar_session_id)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("LiveAvatar get_session_transcript error: %s", exc)
        raise web.HTTPInternalServerError(
            reason="Failed to retrieve session transcript from LiveAvatar API"
        ) from exc

    return web.json_response(transcript)


# ---------------------------------------------------------------------------
# Authenticated views (MAJOR-1 fix — mirrors AvatarSessionView in avatar.py)
# ---------------------------------------------------------------------------


@is_authenticated()
@user_session()
class FullmodeStartView(BaseView):
    """Authenticated entrypoint for POST .../fullmode/{agent_id}/start."""

    async def post(self) -> web.Response:
        return await _start_fullmode_session(self.request)


@is_authenticated()
@user_session()
class FullmodeStopView(BaseView):
    """Authenticated entrypoint for POST .../fullmode/{agent_id}/stop."""

    async def post(self) -> web.Response:
        return await _stop_fullmode_session(self.request)


@is_authenticated()
@user_session()
class FullmodeAvatarsView(BaseView):
    """Authenticated entrypoint for GET /api/v1/avatar/avatars."""

    async def get(self) -> web.Response:
        return await _list_avatars(self.request)


@is_authenticated()
@user_session()
class FullmodeVoicesView(BaseView):
    """Authenticated entrypoint for GET /api/v1/avatar/voices."""

    async def get(self) -> web.Response:
        return await _list_voices(self.request)


@is_authenticated()
@user_session()
class FullmodeTranscriptView(BaseView):
    """Authenticated entrypoint for GET /api/v1/avatar/session/{session_id}/transcript."""

    async def get(self) -> web.Response:
        return await _get_session_transcript(self.request)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_fullmode_routes(router: Any) -> bool:
    """Register FULL mode avatar endpoints on the provided aiohttp router.

    Follows the same defensive-import pattern used by ``register_avatar_routes``
    in ``avatar.py``.  Routes are served through authenticated
    :class:`BaseView` subclasses (``@is_authenticated()`` + ``@user_session()``)
    to match the auth posture of the LITE avatar endpoints.

    Args:
        router: The aiohttp ``UrlDispatcher`` to register routes on.

    Returns:
        ``True`` if routes were registered, ``False`` if the stack is missing.
    """
    try:
        import parrot.integrations.liveavatar  # noqa: F401
    except ImportError as exc:
        _logger.warning(
            "FULL mode avatar endpoints disabled (%s); install "
            "'ai-parrot-integrations[liveavatar]' to enable.",
            exc,
        )
        return False

    router.add_view(
        "/api/v1/avatar/fullmode/{agent_id}/start",
        FullmodeStartView,
    )
    router.add_view(
        "/api/v1/avatar/fullmode/{agent_id}/stop",
        FullmodeStopView,
    )
    router.add_view("/api/v1/avatar/avatars", FullmodeAvatarsView)
    router.add_view("/api/v1/avatar/voices", FullmodeVoicesView)
    router.add_view(
        "/api/v1/avatar/session/{session_id}/transcript",
        FullmodeTranscriptView,
    )

    _logger.info("FULL mode avatar routes registered (authenticated).")
    return True


async def close_all_fullmode_sessions(app: web.Application) -> None:
    """Best-effort teardown of any lingering FULL mode sessions on shutdown.

    Registered as an ``on_cleanup`` callback by the bot manager.  Iterates the
    session store, stops each session, and closes its client.
    """
    store: Dict[str, Any] = app.get(FULLMODE_SESSIONS_KEY, {})
    for session_id, record in list(store.items()):
        client = record.get("client")
        handle = record.get("handle")
        try:
            if client is not None and handle is not None:
                await client.stop_session(handle)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Failed stopping FULL mode session %s on shutdown",
                session_id,
                exc_info=True,
            )
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "Failed to close session %s: %s", session_id, exc
                    )
    store.clear()
