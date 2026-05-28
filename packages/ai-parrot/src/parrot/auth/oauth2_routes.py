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

The Jira-specific callback at ``/api/auth/jira/callback`` remains unchanged
(decision: parallel infrastructure, no Jira refactor in this branch).
"""
from __future__ import annotations

import html
import logging
import string
from pathlib import Path
from typing import Any, Dict

from aiohttp import web

from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS
from parrot.auth.oauth2.service import IntegrationsService


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
