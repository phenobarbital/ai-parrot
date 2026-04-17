"""HTTP routes for OAuth callbacks.

This module exposes the aiohttp route that Atlassian's consent page
redirects to after a user authorizes their Jira account:

- ``GET /api/auth/jira/callback?code=...&state=...``

The handler validates the CSRF state nonce, exchanges the code for
tokens via :class:`JiraOAuthManager`, and renders a browser-friendly
HTML success/error page.  The manager must be stored on
``app['jira_oauth_manager']`` at application startup.
"""
from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from .jira_oauth import JiraOAuthManager


logger = logging.getLogger(__name__)


_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Jira Connected</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f5f5f5}}
.container{{text-align:center;padding:2rem}}.check{{font-size:3rem;color:#36b37e}}</style>
</head><body><div class="container">
<div class="check">&#10003;</div>
<h2>Jira Connected</h2>
<p>Hi {display_name}! Your Jira account ({site_url}) is now linked.</p>
<p>You can close this window and return to your chat.</p>
</div></body></html>"""


_ERROR_HTML = """<!DOCTYPE html>
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
        text=_ERROR_HTML.format(error=html.escape(message)),
        content_type="text/html",
        status=status,
    )


async def jira_oauth_callback(request: web.Request) -> web.Response:
    """Handle ``GET /api/auth/jira/callback``.

    Validates required query parameters, delegates the exchange to
    :class:`JiraOAuthManager`, and renders an HTML page for the browser.
    """
    code = request.query.get("code")
    state = request.query.get("state")

    if not code or not state:
        return _error_response("Missing code or state parameter.", status=400)

    manager: "JiraOAuthManager | None" = request.app.get("jira_oauth_manager")
    if manager is None:
        logger.error("jira_oauth_manager not registered on the aiohttp app")
        return _error_response(
            "OAuth manager not configured on the server.", status=500,
        )

    try:
        token_set = await manager.handle_callback(code, state)
    except ValueError as exc:
        return _error_response(str(exc), status=400)
    except Exception:  # noqa: BLE001
        logger.exception("OAuth callback error")
        return _error_response(
            "An unexpected error occurred while exchanging the authorization code.",
            status=500,
        )

    return web.Response(
        text=_SUCCESS_HTML.format(
            display_name=html.escape(token_set.display_name or ""),
            site_url=html.escape(token_set.site_url or ""),
        ),
        content_type="text/html",
    )


def setup_jira_oauth_routes(app: web.Application) -> None:
    """Attach the Jira OAuth callback route to *app*.

    Call this once at application startup, after the
    :class:`JiraOAuthManager` has been stored at ``app['jira_oauth_manager']``.
    """
    app.router.add_get("/api/auth/jira/callback", jira_oauth_callback)

    # Ensure the route is not subjected to the auth middleware — it IS the
    # authorization callback itself.
    try:  # pragma: no cover - navigator_auth is optional in tests
        from navigator_auth.conf import exclude_list  # type: ignore

        if "/api/auth/jira/callback" not in exclude_list:
            exclude_list.append("/api/auth/jira/callback")
    except ImportError:
        pass
