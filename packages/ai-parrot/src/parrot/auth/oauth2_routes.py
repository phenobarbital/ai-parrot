"""Generic OAuth 2.0 callback routes for AI-Parrot.

Each :class:`parrot.auth.oauth2_base.AbstractOAuth2Manager` subclass mounts
a single callback route via :func:`setup_oauth2_routes`. The handler:

- Validates ``code`` and ``state`` query parameters.
- Locates the per-provider manager on the aiohttp app
  (``app[f"oauth2_manager_{provider_id}"]``).
- Delegates the token exchange to ``manager.handle_callback(code, state)``.
- For the web channel, persists the credential via
  :class:`parrot.auth.oauth2.service.IntegrationsService` and
  renders the existing ``web_oauth_success.html`` postMessage page.
- For the **A2A channel** (FEAT-260 / TASK-1645): when
  ``state_payload["a2a_interaction_id"]`` is present, calls the registered
  A2A resume hook — typically
  :meth:`~parrot.a2a.server.A2AServer.resume_from_oauth_callback` — to
  reload the suspended execution and call ``agent.resume()``.  The hook is
  stored on the aiohttp app under ``app["a2a_oauth_resume_hook"]`` via
  :func:`register_a2a_resume_hook`.  The package boundary (core ai-parrot
  vs. satellite ai-parrot-server) is respected: no direct import of
  :class:`~parrot.a2a.server.A2AServer` in this module.

The Jira-specific callback at ``/api/auth/jira/callback`` remains unchanged
(decision: parallel infrastructure, no Jira refactor in this branch).
"""
from __future__ import annotations

import html
import logging
import string
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, Optional

from aiohttp import web

from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS
from parrot.auth.oauth2.service import IntegrationsService
from parrot.mcp.oauth2_state import resolve_pending_callback, is_pending


# ─────────────────────────────────────────────────────────────
# A2A Resume Hook (FEAT-260 / TASK-1645)
# ─────────────────────────────────────────────────────────────

#: Key under which the A2A resume hook is stored on the aiohttp app.
_A2A_RESUME_HOOK_KEY = "a2a_oauth_resume_hook"


def register_a2a_resume_hook(
    app: web.Application,
    hook: Callable[[str], Coroutine[Any, Any, None]],
) -> None:
    """Register an async callable to resume suspended A2A tasks after OAuth.

    The ``hook`` is called after a successful OAuth callback when
    ``state_payload`` contains an ``a2a_interaction_id`` field.  It is
    called with the ``interaction_id`` as its only argument.

    Typically wired as::

        a2a_server = A2AServer(agent, ...)
        register_a2a_resume_hook(
            app,
            a2a_server.resume_from_oauth_callback,
        )

    The indirection keeps the ``ai-parrot`` core package free of any import
    from the ``ai-parrot-server`` satellite.

    Args:
        app: The aiohttp :class:`~aiohttp.web.Application`.
        hook: Async callable ``(interaction_id: str) -> None``.
    """
    app[_A2A_RESUME_HOOK_KEY] = hook
    logger.info(
        "oauth2_routes: A2A resume hook registered (%s)", hook.__qualname__
    )


_TEMPLATES_DIR = Path(__file__).parent / "templates"
_WEB_SUCCESS_TMPL = string.Template(
    (_TEMPLATES_DIR / "web_oauth_success.html").read_text()
)
_WEB_ERROR_TMPL = string.Template(
    (_TEMPLATES_DIR / "web_oauth_error.html").read_text()
)


logger = logging.getLogger(__name__)


_GENERIC_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{provider} Connected</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f5f5f5}}
.container{{text-align:center;padding:2rem}}.check{{font-size:3rem;color:#36b37e}}</style>
</head><body><div class="container">
<div class="check">&#10003;</div>
<h2>{provider} Connected</h2>
<p>Hi {display_name}! Your {provider} account is now linked.</p>
<p>You can close this window and return to your chat.</p>
</div></body></html>"""


_GENERIC_ERROR_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Authorization Failed</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f5f5f5}}
.container{{text-align:center;padding:2rem}}.x{{font-size:3rem;color:#de350b}}</style>
</head><body><div class="container">
<div class="x">&#10007;</div>
<h2>Authorization Failed</h2>
<p>{error}</p>
</div></body></html>"""


def _error_response(message: str, status: int = 400) -> web.Response:
    return web.Response(
        text=_GENERIC_ERROR_HTML.format(error=html.escape(message)),
        content_type="text/html",
        status=status,
    )


async def _handle_web_callback(
    request: web.Request,
    provider_id: str,
    token_set: Any,
    state_payload: Dict[str, Any],
) -> web.Response:
    """Render the popup ``postMessage`` page and persist the credential.

    The web channel always embeds ``return_origin`` and ``provider_id`` in
    ``extra_state``; this handler validates the origin allowlist, calls
    :meth:`IntegrationsService.persist_credential`, and renders the
    standard ``web_oauth_success.html`` template so the calling frontend
    receives a ``postMessage`` event.
    """
    extra: Dict[str, Any] = state_payload.get("extra") or {}
    return_origin = extra.get("return_origin")
    user_id = state_payload.get("user_id")
    # The provider written into extra_state by IntegrationsService.start_connect
    # takes precedence over the URL-bound provider_id, but they should match.
    provider = extra.get("provider_id") or provider_id

    if not return_origin or return_origin not in WEB_OAUTH_ALLOWED_ORIGINS:
        logger.warning(
            "Web OAuth callback rejected: return_origin=%r not in allowlist",
            return_origin,
        )
        return web.Response(
            text=_WEB_ERROR_TMPL.safe_substitute(
                provider=provider,
                error="invalid_origin",
                target_origin=html.escape(return_origin or "*"),
            ),
            content_type="text/html",
            status=400,
        )

    if not user_id:
        logger.warning("Web OAuth callback: state_payload missing user_id")
        return web.Response(
            text=_WEB_ERROR_TMPL.safe_substitute(
                provider=provider,
                error="missing_user",
                target_origin=html.escape(return_origin),
            ),
            content_type="text/html",
            status=400,
        )

    try:
        svc = IntegrationsService()
        await svc.persist_credential(user_id, provider, token_set)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to persist web OAuth credential for user_id=%s provider=%s",
            user_id, provider,
        )
        return web.Response(
            text=_WEB_ERROR_TMPL.safe_substitute(
                provider=provider,
                error="internal_error",
                target_origin=html.escape(return_origin),
            ),
            content_type="text/html",
            status=500,
        )

    return web.Response(
        text=_WEB_SUCCESS_TMPL.safe_substitute(
            provider=provider,
            account_id=html.escape(token_set.account_id or ""),
            display_name=html.escape(token_set.display_name or ""),
            target_origin=html.escape(return_origin),
        ),
        content_type="text/html",
    )


def make_oauth2_callback(provider_id: str):
    """Return a request handler bound to ``provider_id``."""

    async def handler(request: web.Request) -> web.Response:
        code = request.query.get("code")
        state = request.query.get("state")
        if not code or not state:
            return _error_response("Missing code or state parameter.", status=400)

        slot = f"oauth2_manager_{provider_id}"
        manager = request.app.get(slot)
        if manager is None:
            logger.error("%s not registered on the aiohttp app", slot)
            return _error_response(
                f"OAuth manager '{provider_id}' not configured on the server.",
                status=500,
            )

        try:
            token_set, state_payload = await manager.handle_callback(code, state)
        except ValueError as exc:
            return _error_response(str(exc), status=400)
        except Exception:  # noqa: BLE001
            logger.exception("OAuth callback error for provider=%s", provider_id)
            return _error_response(
                "An unexpected error occurred while exchanging the authorization code.",
                status=500,
            )

        # ── FEAT-260 / TASK-1645: A2A resume fan-out ─────────────────────────
        # If the state_payload carries an `a2a_interaction_id` it means this
        # callback is the tail of an A2A-initiated OAuth flow.  The credential
        # is already persisted by `manager.handle_callback`; we only need to
        # trigger the A2A resume so the suspended agent execution can continue.
        # The hook is registered by the satellite ai-parrot-server; if it is
        # absent (web-only deployments) this block is a no-op.
        a2a_interaction_id: Optional[str] = state_payload.get("a2a_interaction_id")
        if a2a_interaction_id:
            hook = request.app.get(_A2A_RESUME_HOOK_KEY)
            if hook is not None:
                try:
                    await hook(a2a_interaction_id)
                    logger.info(
                        "oauth2_routes: A2A resume triggered for interaction_id=%s",
                        a2a_interaction_id,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "oauth2_routes: A2A resume hook failed for interaction_id=%s; "
                        "credential persisted but task may require re-prompt",
                        a2a_interaction_id,
                    )
            else:
                logger.warning(
                    "oauth2_routes: a2a_interaction_id=%s found in state but no "
                    "A2A resume hook registered; task will not be resumed automatically",
                    a2a_interaction_id,
                )
        # ── end A2A fan-out ───────────────────────────────────────────────────

        channel = state_payload.get("channel", "web")
        if channel == "web":
            return await _handle_web_callback(
                request, provider_id, token_set, state_payload,
            )

        return web.Response(
            text=_GENERIC_SUCCESS_HTML.format(
                provider=provider_id,
                display_name=html.escape(
                    token_set.display_name or token_set.account_id or "",
                ),
            ),
            content_type="text/html",
        )

    return handler


def setup_oauth2_routes(
    app: web.Application,
    provider_id: str,
    callback_path: str,
) -> None:
    """Attach the OAuth2 callback route for ``provider_id`` to *app*.

    Idempotent — calling twice with the same arguments is a no-op.
    """
    handler = make_oauth2_callback(provider_id)
    # Avoid registering the same route twice (aiohttp raises otherwise).
    for route in app.router.routes():
        info = route.get_info()
        if info.get("path") == callback_path:
            return
    app.router.add_get(callback_path, handler)

    # Exclude from auth middleware — it IS the auth callback.
    try:  # pragma: no cover - navigator_auth is optional in tests
        from navigator_auth.conf import exclude_list  # type: ignore

        if callback_path not in exclude_list:
            exclude_list.append(callback_path)
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# MCP OAuth2 callback route
# ---------------------------------------------------------------------------

_MCP_CALLBACK_PATH = "/api/auth/oauth2/mcp/callback"


async def handle_mcp_oauth2_callback(request: web.Request) -> web.Response:
    """Handle OAuth2 callback for MCP server authorization code flows.

    This route is called by the authorization server after the user grants
    access.  It dispatches the authorization code to the waiting transport
    coroutine via the shared ``_pending_mcp_callbacks`` dict in
    :mod:`parrot.mcp.oauth2_state`.

    Route: ``GET /api/auth/oauth2/mcp/callback``

    Query parameters:
        code: Authorization code from the authorization server.
        state: OAuth2 state parameter identifying the pending flow.
        error: Error code from the authorization server (optional).
        error_description: Human-readable error description (optional).

    Returns:
        HTML response with success or error message.
    """
    state = request.query.get("state")
    code = request.query.get("code")
    error = request.query.get("error")
    error_description = request.query.get("error_description", "")

    # Handle authorization server errors
    if error:
        error_msg = error_description or error
        logger.warning("MCP OAuth2 callback error: %s — %s", error, error_description)
        return web.Response(
            status=400,
            content_type="text/html",
            text=f"<html><body><h3>OAuth2 error: {html.escape(error_msg)}</h3></body></html>",
        )

    # Validate state
    if not state or not is_pending(state):
        logger.warning("MCP OAuth2 callback: invalid or expired state=%r", state)
        return web.Response(
            status=400,
            content_type="text/html",
            text=(
                "<html><body>"
                "<h3>Invalid or expired OAuth2 state.</h3>"
                "<p>Please try connecting again.</p>"
                "</body></html>"
            ),
        )

    # Validate code
    if not code:
        logger.warning("MCP OAuth2 callback: missing authorization code for state=%r", state)
        return web.Response(
            status=400,
            content_type="text/html",
            text=(
                "<html><body>"
                "<h3>Missing authorization code.</h3>"
                "</body></html>"
            ),
        )

    # Signal the waiting transport coroutine
    resolved = resolve_pending_callback(state, code)
    if not resolved:
        # Race condition: state was consumed between is_pending and resolve
        logger.warning(
            "MCP OAuth2 callback: state=%r was consumed before resolution", state
        )
        return web.Response(
            status=400,
            content_type="text/html",
            text=(
                "<html><body>"
                "<h3>Invalid or expired OAuth2 state.</h3>"
                "<p>Please try connecting again.</p>"
                "</body></html>"
            ),
        )

    logger.info("MCP OAuth2 callback: resolved code exchange for state=%r", state)
    return web.Response(
        content_type="text/html",
        text=(
            "<html><body>"
            "<h3>Authentication complete. You can close this window.</h3>"
            "</body></html>"
        ),
    )


def setup_mcp_oauth2_callback(app: web.Application) -> None:
    """Register the MCP OAuth2 callback route on *app*.

    Idempotent — calling twice is a no-op.  The route is registered at
    ``/api/auth/oauth2/mcp/callback`` and excluded from auth middleware.

    Args:
        app: The aiohttp web application.
    """
    path = _MCP_CALLBACK_PATH

    # Idempotency check — check resources (not routes, since add_get adds HEAD too)
    for resource in app.router.resources():
        info = resource.get_info()
        if info.get("path") == path:
            return

    app.router.add_get(path, handle_mcp_oauth2_callback)
    logger.debug("Registered MCP OAuth2 callback route at %s", path)

    # Exclude from auth middleware
    try:  # pragma: no cover
        from navigator_auth.conf import exclude_list  # type: ignore

        if path not in exclude_list:
            exclude_list.append(path)
    except ImportError:
        pass
