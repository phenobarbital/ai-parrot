"""HTTP API for moderated voice broadcasts (FEAT-537 — Module 5).

Mounts spec §2's "New Public Interfaces" table under
``/api/v1/agents/{agent_id}/voice-broadcasts``.  Plain ``async def`` aiohttp
handlers closing over a :class:`BroadcastService`, rather than navigator
``BaseView`` classes, so the runnable example (TASK-2963) can mount the exact
same endpoints with a demo principal resolver instead of a second, divergent
implementation.

Authority model, restated because every handler depends on it:

* Being authenticated is necessary and **never sufficient**.  Tenant/agent
  scope, lease ownership and the moderator/speaker role are checked per
  operation, through the same service the WebSocket route uses.
* Creating a broadcast confers nothing.  The moderator is the first
  participant admitted, decided atomically inside the registry.
* A share link carries the broadcast id and nothing else — no role claim, no
  credential.  ``client_token`` appears in exactly one response body
  (``GET …/connection``) and is subscribe-only.

Hardening applied to every state-changing request: an 8 KiB JSON body cap, an
``Origin`` allow-list (``PARROT_BROADCAST_ALLOWED_ORIGINS``, same-origin by
default), and a per-principal token bucket (30 requests / 10 s) returning 429.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, Optional, Tuple

from aiohttp import web

from parrot.integrations.liveavatar.broadcast import errors
from parrot.integrations.liveavatar.broadcast.models import ParticipantPrincipal

logger = logging.getLogger(__name__)

#: Default mount point (spec §2).
DEFAULT_PREFIX: str = "/api/v1/agents/{agent_id}/voice-broadcasts"

#: Largest accepted JSON request body.
MAX_BODY_BYTES: int = 8 * 1024

#: Per-principal token bucket.
RATE_LIMIT_REQUESTS: int = 30
RATE_LIMIT_WINDOW_S: float = 10.0

#: Comma-separated allow-list of acceptable ``Origin`` values.
ALLOWED_ORIGINS_ENV: str = "PARROT_BROADCAST_ALLOWED_ORIGINS"

PrincipalResolver = Callable[[web.Request, str], Awaitable[ParticipantPrincipal]]

#: Exception → HTTP status.  ``BroadcastError.status`` already carries the
#: spec's code for the typed errors; this map is the fallback and the place the
#: mapping is documented in one piece.
_STATUS_BY_ERROR: Tuple[Tuple[type, int], ...] = (
    (errors.ViewerLimitReached, 409),
    (errors.IdentityTombstoned, 409),
    (errors.BroadcastTerminal, 410),
    (errors.StaleVersion, 409),
    (errors.StaleFloorEpoch, 409),
    (errors.SpeakerConnectionExists, 409),
    (errors.FloorNotGranted, 403),
    (errors.NotModerator, 403),
    (errors.NotSpeaker, 403),
    (errors.NotOwner, 409),
)


async def navigator_principal_resolver(request: web.Request, agent_id: str) -> ParticipantPrincipal:
    """Build a scoped principal from the navigator session.

    ``request["user_id"]`` is never set by navigator-auth, so the session is the
    only trustworthy source.  The tenant likewise comes from the session, never
    from a request field a client could choose.

    Args:
        request: The incoming request.
        agent_id: Agent from the route.

    Returns:
        The scoped principal.

    Raises:
        web.HTTPUnauthorized: When there is no authenticated session.
    """
    session: Any = getattr(request, "session", None)
    if session is None:
        try:
            from navigator_session import get_session
        except ImportError as exc:  # pragma: no cover — server-only dependency
            raise web.HTTPUnauthorized(reason="authentication unavailable") from exc
        session = await get_session(request)
    if not session:
        raise web.HTTPUnauthorized(reason="authentication required")

    user_id = session.get("user_id") or session.get("username")
    if not user_id:
        raise web.HTTPUnauthorized(reason="session carries no user identity")
    tenant_id = session.get("tenant_id") or session.get("program") or "default"
    return ParticipantPrincipal(
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        agent_id=agent_id,
        display_name=str(session.get("display_name") or user_id),
        roles=list(session.get("groups") or []),
    )


async def _session_user(request: web.Request) -> Dict[str, Any]:
    """Extract a user mapping from the navigator session.

    Returns only the *identity*: the tenant is the service's decision, not the
    transport's, so it is deliberately not read here.  ``request["user_id"]`` is
    never set by navigator-auth, which is why the session is the only source.

    Args:
        request: The incoming request.

    Returns:
        A mapping with ``user_id`` / ``username`` / ``roles``.

    Raises:
        web.HTTPUnauthorized: When there is no authenticated session.
    """
    session: Any = getattr(request, "session", None)
    if session is None:
        try:
            from navigator_session import get_session
        except ImportError as exc:  # pragma: no cover — server-only dependency
            raise web.HTTPUnauthorized(reason="authentication unavailable") from exc
        session = await get_session(request)
    if not session:
        raise web.HTTPUnauthorized(reason="authentication required")
    user_id = session.get("user_id") or session.get("username")
    if not user_id:
        raise web.HTTPUnauthorized(reason="session carries no user identity")
    return {
        "user_id": str(user_id),
        "username": str(session.get("display_name") or user_id),
        "roles": list(session.get("groups") or []),
    }


class _RateLimiter:
    """Per-principal sliding-window limiter."""

    def __init__(self, limit: int = RATE_LIMIT_REQUESTS, window_s: float = RATE_LIMIT_WINDOW_S) -> None:
        self._limit = limit
        self._window_s = window_s
        self._hits: Dict[str, Deque[float]] = {}
        self._last_sweep: float = time.monotonic()

    def allow(self, key: str) -> bool:
        """Whether ``key`` may make one more request now.

        Args:
            key: Principal identity.

        Returns:
            ``False`` once the window's budget is exhausted.
        """
        now = time.monotonic()
        self._evict(now)
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self._window_s:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def _evict(self, now: float) -> None:
        """Drop principals that have gone quiet.

        Without this the map keeps one deque per distinct ``tenant:user`` for
        the lifetime of the process, so a long-running server accumulates an
        entry for every principal that ever called — a slow leak proportional
        to distinct callers rather than to concurrent ones. Sweeping is
        amortised: it runs at most once per window, not on every request.

        Args:
            now: Current monotonic time.
        """
        if now - self._last_sweep < self._window_s:
            return
        self._last_sweep = now
        stale = [key for key, hits in self._hits.items() if not hits or (now - hits[-1]) > self._window_s]
        for key in stale:
            del self._hits[key]


def _allowed_origins() -> Optional[frozenset[str]]:
    """Parse the configured origin allow-list.

    Returns:
        The allow-list, or ``None`` when unset (same-origin only).
    """
    raw = os.environ.get(ALLOWED_ORIGINS_ENV, "").strip()
    if not raw:
        return None
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def _origin_ok(request: web.Request) -> bool:
    """Check a state-changing request's ``Origin`` header.

    A missing ``Origin`` is allowed (non-browser clients such as curl and the
    server's own tests never send one); a *present* one must match the
    allow-list or the request's own host.
    """
    origin = request.headers.get("Origin")
    if not origin:
        return True
    allowed = _allowed_origins()
    if allowed is not None:
        return origin in allowed
    host = request.headers.get("Host", "")
    return origin.split("//", 1)[-1] == host


async def _json_body(request: web.Request) -> Dict[str, Any]:
    """Read a bounded JSON object body.

    Returns:
        The parsed object, or ``{}`` for an empty body.

    Raises:
        web.HTTPRequestEntityTooLarge: Over :data:`MAX_BODY_BYTES`.
        web.HTTPBadRequest: On malformed JSON or a non-object body.
    """
    raw = await request.content.read(MAX_BODY_BYTES + 1)
    if len(raw) > MAX_BODY_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY_BYTES, actual_size=len(raw))
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise web.HTTPBadRequest(reason="body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(reason="body must be a JSON object")
    return payload


def _status_for(exc: errors.BroadcastError) -> int:
    """Resolve the HTTP status for a broadcast error."""
    for error_type, status in _STATUS_BY_ERROR:
        if isinstance(exc, error_type):
            return status
    return getattr(exc, "status", 409)


async def _error_response(
    exc: errors.BroadcastError,
    *,
    service: Any = None,
    principal: Optional[ParticipantPrincipal] = None,
    broadcast_id: Optional[str] = None,
) -> web.Response:
    """Render a broadcast error as a sanitized JSON response.

    Includes the current public state where it is available, so a client that
    lost a compare-and-set race can retry without an extra round trip (spec §2:
    "stale/switching conflict 409 … return current state").

    Args:
        exc: The error to render.
        service: The service, for fetching current state.
        principal: The caller.
        broadcast_id: Broadcast concerned.

    Returns:
        The JSON error response.
    """
    status = _status_for(exc)
    body: Dict[str, Any] = {
        "error": exc.reason.value if exc.reason else "forbidden",
    }
    if service is not None and principal is not None and broadcast_id:
        try:
            body["state"] = await service.public_state(principal.tenant_id, broadcast_id)
        except Exception:  # noqa: BLE001 — the error response must still render
            pass
    headers = {}
    from parrot.integrations.liveavatar.broadcast.service import BroadcastNotReady

    if isinstance(exc, BroadcastNotReady):
        # Explicitly retryable: the browser polls for its room credentials.
        headers["Retry-After"] = "1"
        body["retryable"] = True
    return web.json_response(body, status=status, headers=headers)


def register_voice_broadcast_routes(
    app: web.Application,
    service: Any,
    *,
    prefix: str = DEFAULT_PREFIX,
    principal_resolver: Optional[PrincipalResolver] = None,
) -> None:
    """Mount the broadcast HTTP API on an aiohttp application.

    Args:
        app: The application to mount on.
        service: A :class:`BroadcastService`.
        prefix: Route prefix; must contain ``{agent_id}``.
        principal_resolver: Override for
            :func:`navigator_principal_resolver` (the example passes a demo
            resolver bound to server-configured tokens).
    """
    limiter = _RateLimiter()

    async def _principal(request: web.Request) -> ParticipantPrincipal:
        """Resolve, authorize and rate-limit the caller.

        Two paths, deliberately:

        * **Default** — the session is turned into a user object and handed to
          ``service.resolve_principal``, so tenant scoping *and* the service's
          ``authorize_agent`` hook are applied by the same code the WebSocket
          route uses.  HTTP and WS cannot diverge on who may use an agent.
        * **Injected `principal_resolver`** — authoritative and used as-is.
          The runnable example needs this to map server-configured demo tokens
          to fixed principals without a navigator session.

        Raises:
            web.HTTPForbidden: On a rejected ``Origin`` or a failed
                authorization check.
            web.HTTPTooManyRequests: When the per-principal budget is spent.
        """
        if request.method != "GET" and not _origin_ok(request):
            raise web.HTTPForbidden(reason="origin not allowed")
        agent_id = request.match_info["agent_id"]
        if principal_resolver is not None:
            principal = await principal_resolver(request, agent_id)
        else:
            try:
                principal = await service.resolve_principal(await _session_user(request), agent_id)
            except errors.BroadcastError as exc:
                raise web.HTTPForbidden(reason=str(exc)) from exc
        if not limiter.allow(f"{principal.tenant_id}:{principal.user_id}"):
            raise web.HTTPTooManyRequests(reason="rate limited")
        return principal

    # ── Handlers ───────────────────────────────────────────────────────

    async def create(request: web.Request) -> web.Response:
        """``POST /`` — create a pending broadcast (201).

        Returns no room or provider credentials and asserts no moderator: the
        first admitted participant becomes moderator (spec §2 step 1).
        """
        principal = await _principal(request)
        agent_id = request.match_info["agent_id"]
        await _json_body(request)
        try:
            descriptor = await service.create_broadcast(principal, agent_id)
        except errors.BroadcastError as exc:
            return await _error_response(exc)
        state = await service.public_state(principal.tenant_id, descriptor.broadcast_id)
        return web.json_response(
            {
                "broadcast_id": descriptor.broadcast_id,
                "share_path": f"/?broadcast={descriptor.broadcast_id}",
                "state": state,
            },
            status=201,
        )

    async def get_state(request: web.Request) -> web.Response:
        """``GET /{bid}`` — public state (200), or 404 when out of scope."""
        principal = await _principal(request)
        agent_id = request.match_info["agent_id"]
        broadcast_id = request.match_info["broadcast_id"]
        try:
            state = await service.get_public_state(principal, agent_id, broadcast_id)
        except errors.BroadcastTerminal:
            # Unknown and out-of-scope are deliberately indistinguishable.
            raise web.HTTPNotFound(reason="unknown broadcast") from None
        except errors.BroadcastError as exc:
            return await _error_response(exc)
        return web.json_response({"state": state.model_dump(mode="json")})

    async def join(request: web.Request) -> web.Response:
        """``POST /{bid}/viewers`` — atomically reserve one of ten seats."""
        principal = await _principal(request)
        agent_id = request.match_info["agent_id"]
        broadcast_id = request.match_info["broadcast_id"]
        await _json_body(request)
        try:
            admission = await service.join(principal, agent_id, broadcast_id)
        except errors.BroadcastTerminal as exc:
            if exc.reason is None and not await service.get_descriptor(principal.tenant_id, broadcast_id):
                raise web.HTTPNotFound(reason="unknown broadcast") from None
            return await _error_response(exc)
        except errors.BroadcastError as exc:
            return await _error_response(
                exc,
                service=service,
                principal=principal,
                broadcast_id=broadcast_id,
            )
        state = await service.public_state(principal.tenant_id, broadcast_id)
        return web.json_response(
            {
                "lease_id": admission.lease.lease_id,
                "role": "moderator" if admission.is_first else "viewer",
                "media_ready": bool(state.get("media_ready")),
                "state": state,
            },
            status=201,
        )

    async def connection(request: web.Request) -> web.Response:
        """``GET /{bid}/viewers/{lease}/connection`` — this lease's credentials.

        The only response in this module that carries a token, and it is the
        subscribe-only ``client_token`` for this browser's own identity.
        """
        principal = await _principal(request)
        broadcast_id = request.match_info["broadcast_id"]
        lease_id = request.match_info["lease_id"]
        try:
            response = await service.connection(principal, broadcast_id, lease_id)
        except errors.BroadcastError as exc:
            return await _error_response(
                exc,
                service=service,
                principal=principal,
                broadcast_id=broadcast_id,
            )
        return web.json_response(response.model_dump(mode="json"))

    async def leave(request: web.Request) -> web.Response:
        """``DELETE /{bid}/viewers/{lease}`` — idempotent 204."""
        principal = await _principal(request)
        broadcast_id = request.match_info["broadcast_id"]
        lease_id = request.match_info["lease_id"]
        try:
            await service.leave(principal, broadcast_id, lease_id)
        except errors.BroadcastTerminal:
            return web.Response(status=204)
        except errors.BroadcastError as exc:
            return await _error_response(exc)
        return web.Response(status=204)

    async def raise_hand(request: web.Request) -> web.Response:
        """``POST /{bid}/hands`` — idempotent raise, own lease only."""
        principal = await _principal(request)
        broadcast_id = request.match_info["broadcast_id"]
        body = await _json_body(request)
        lease_id = str(body.get("lease_id") or "")
        if not lease_id:
            raise web.HTTPBadRequest(reason="lease_id is required")
        try:
            state = await service.raise_hand(principal, broadcast_id, lease_id)
        except errors.BroadcastError as exc:
            return await _error_response(exc)
        return web.json_response({"state": state.model_dump(mode="json")})

    async def cancel_own_hand(request: web.Request) -> web.Response:
        """``DELETE /{bid}/hands/me`` — withdraw the caller's own request."""
        principal = await _principal(request)
        broadcast_id = request.match_info["broadcast_id"]
        lease_id = request.query.get("lease_id", "")
        if not lease_id:
            raise web.HTTPBadRequest(reason="lease_id is required")
        try:
            state = await service.cancel_hand(principal, broadcast_id, lease_id)
        except errors.BroadcastError as exc:
            return await _error_response(exc)
        return web.json_response({"state": state.model_dump(mode="json")})

    async def dismiss_hand(request: web.Request) -> web.Response:
        """``DELETE /{bid}/hands/{lease}`` — moderator dismisses a request.

        Changes no microphone permission (spec §2).
        """
        principal = await _principal(request)
        broadcast_id = request.match_info["broadcast_id"]
        target = request.match_info["lease_id"]
        try:
            state = await service.dismiss_hand(principal, broadcast_id, target)
        except errors.BroadcastError as exc:
            return await _error_response(exc)
        return web.json_response({"state": state.model_dump(mode="json")})

    async def set_floor(request: web.Request) -> web.Response:
        """``POST /{bid}/floor`` — moderator grant/revoke/reclaim.

        ``lease_id: null`` revokes.  A stale ``expected_version`` or an
        in-flight switch returns 409 **with the current state**.
        """
        principal = await _principal(request)
        broadcast_id = request.match_info["broadcast_id"]
        body = await _json_body(request)
        if "expected_version" not in body:
            raise web.HTTPBadRequest(reason="expected_version is required")
        try:
            expected_version = int(body["expected_version"])
        except (TypeError, ValueError) as exc:
            raise web.HTTPBadRequest(reason="expected_version must be an integer") from exc
        target = body.get("lease_id")
        try:
            result = await service.set_floor(
                principal,
                broadcast_id,
                str(target) if target else None,
                expected_version,
            )
        except errors.BroadcastError as exc:
            return await _error_response(
                exc,
                service=service,
                principal=principal,
                broadcast_id=broadcast_id,
            )
        state = await service.public_state(principal.tenant_id, broadcast_id)
        return web.json_response({"state": state, "floor_epoch": result.floor_epoch})

    async def release_floor(request: web.Request) -> web.Response:
        """``POST /{bid}/floor/release`` — Finish Speaking, current speaker only."""
        principal = await _principal(request)
        broadcast_id = request.match_info["broadcast_id"]
        body = await _json_body(request)
        lease_id = str(body.get("lease_id") or "")
        if not lease_id:
            raise web.HTTPBadRequest(reason="lease_id is required")
        try:
            lease = await service.get_lease(principal.tenant_id, broadcast_id, lease_id)
            if lease is None or lease.principal.user_id != principal.user_id:
                raise errors.NotSpeaker(message="lease is not owned by this principal")
            result = await service.release_floor(principal.tenant_id, broadcast_id, lease_id)
        except errors.BroadcastError as exc:
            return await _error_response(
                exc,
                service=service,
                principal=principal,
                broadcast_id=broadcast_id,
            )
        state = await service.public_state(principal.tenant_id, broadcast_id)
        return web.json_response({"state": state, "floor_epoch": result.floor_epoch})

    async def stop(request: web.Request) -> web.Response:
        """``POST /{bid}/stop`` — moderator-only, idempotent, 202.

        The creator gets 403 unless they are also the current moderator.
        """
        principal = await _principal(request)
        broadcast_id = request.match_info["broadcast_id"]
        await _json_body(request)
        try:
            await service.stop(principal, broadcast_id)
        except errors.BroadcastError as exc:
            return await _error_response(exc)
        state = await service.public_state(principal.tenant_id, broadcast_id)
        return web.json_response({"state": state}, status=202)

    base = prefix.rstrip("/")
    app.router.add_post(f"{base}/", create)
    app.router.add_post(base, create)
    app.router.add_get(base + "/{broadcast_id}", get_state)
    app.router.add_post(base + "/{broadcast_id}/viewers", join)
    app.router.add_get(base + "/{broadcast_id}/viewers/{lease_id}/connection", connection)
    app.router.add_delete(base + "/{broadcast_id}/viewers/{lease_id}", leave)
    app.router.add_post(base + "/{broadcast_id}/hands", raise_hand)
    app.router.add_delete(base + "/{broadcast_id}/hands/me", cancel_own_hand)
    app.router.add_delete(base + "/{broadcast_id}/hands/{lease_id}", dismiss_hand)
    app.router.add_post(base + "/{broadcast_id}/floor", set_floor)
    app.router.add_post(base + "/{broadcast_id}/floor/release", release_floor)
    app.router.add_post(base + "/{broadcast_id}/stop", stop)

    app["voice_broadcast_service"] = service
    logger.info("Voice broadcast routes registered at %s", base)


__all__ = [
    "ALLOWED_ORIGINS_ENV",
    "DEFAULT_PREFIX",
    "MAX_BODY_BYTES",
    "RATE_LIMIT_REQUESTS",
    "RATE_LIMIT_WINDOW_S",
    "navigator_principal_resolver",
    "register_voice_broadcast_routes",
]
