"""HTTP routes for OAuth callbacks.

This module exposes the aiohttp route that Atlassian's consent page
redirects to after a user authorizes their Jira account:

- ``GET /api/auth/jira/callback?code=...&state=...``

The handler validates the CSRF state nonce, exchanges the code for
tokens via :class:`JiraOAuthManager`, and renders a browser-friendly
HTML success/error page.  The manager must be stored on
``app['jira_oauth_manager']`` at application startup.

Optionally, a :class:`TelegramOAuthNotifier` stored on
``app['jira_oauth_notifier']`` receives a fire-and-forget notification
after successful callbacks that originated from Telegram (i.e. the
authorization URL included ``extra_state={"chat_id": ...}``).

For web-channel OAuth2 3LO flows the callback instead persists the
credential via :class:`~parrot.integrations.oauth2.service.IntegrationsService`
and renders a ``postMessage`` HTML page that signals the opener popup.
"""
from __future__ import annotations

import asyncio
import html
import logging
import string
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

from aiohttp import web

from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS
from parrot.integrations.oauth2.service import IntegrationsService

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from .jira_oauth import JiraOAuthManager, JiraTokenSet
    from parrot.integrations.telegram.jira_commands import TelegramOAuthNotifier

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_WEB_SUCCESS_TMPL = string.Template(
    (_TEMPLATES_DIR / "web_oauth_success.html").read_text()
)
_WEB_ERROR_TMPL = string.Template(
    (_TEMPLATES_DIR / "web_oauth_error.html").read_text()
)


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


async def _handle_web_callback(
    request: web.Request,
    token_set: "JiraTokenSet",
    state_payload: Dict[str, Any],
) -> web.Response:
    """Process an OAuth callback that originated from the web popup flow.

    Validates the ``return_origin``, persists the credential, and renders
    the ``web_oauth_success.html`` postMessage page.  On failure, renders
    ``web_oauth_error.html``.

    Args:
        request: The incoming aiohttp request (unused beyond signature).
        token_set: Token and identity data returned by :meth:`JiraOAuthManager.handle_callback`.
        state_payload: Full state payload (channel, user_id, extra) from the manager.

    Returns:
        HTML response suitable for the popup window.
    """
    extra: Dict[str, Any] = state_payload.get("extra") or {}
    return_origin: str | None = extra.get("return_origin")
    user_id: str | None = state_payload.get("user_id")
    provider = "jira"

    # Validate return_origin against the server-side allowlist.
    if not return_origin or return_origin not in WEB_OAUTH_ALLOWED_ORIGINS:
        logger.warning(
            "Web OAuth callback rejected: return_origin=%r not in allowlist",
            return_origin,
        )
        safe_origin = html.escape(return_origin or "*")
        return web.Response(
            text=_WEB_ERROR_TMPL.safe_substitute(
                provider=provider,
                error="invalid_origin",
                target_origin=safe_origin,
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

    # Persist the credential to DocumentDB.
    try:
        svc = IntegrationsService()
        await svc.persist_credential(user_id, provider, token_set)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to persist web OAuth credential for user_id=%s provider=%s",
            user_id,
            provider,
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


async def _notify_telegram(
    notifier: "TelegramOAuthNotifier",
    chat_id: int,
    display_name: str,
    site_url: str,
) -> None:
    """Fire-and-forget helper that swallows Telegram errors gracefully."""
    try:
        await notifier.notify_connected(chat_id, display_name, site_url)
    except Exception:
        logger.warning(
            "Failed to send Telegram OAuth notification for chat_id=%s",
            chat_id,
            exc_info=True,
        )


async def jira_oauth_callback(request: web.Request) -> web.Response:
    """Handle ``GET /api/auth/jira/callback``.

    Validates required query parameters, delegates the exchange to
    :class:`JiraOAuthManager`, and renders an HTML page for the browser.
    After a successful exchange, optionally fires a Telegram notification
    via the :class:`TelegramOAuthNotifier` stored on ``app['jira_oauth_notifier']``.
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
        token_set, state_payload = await manager.handle_callback(code, state)
    except ValueError as exc:
        return _error_response(str(exc), status=400)
    except Exception:  # noqa: BLE001
        logger.exception("OAuth callback error")
        return _error_response(
            "An unexpected error occurred while exchanging the authorization code.",
            status=500,
        )

    # Web-channel branch: render postMessage page and persist credential.
    # When channel is absent, default to "telegram" for backward compatibility.
    channel = state_payload.get("channel", "telegram")
    if channel == "web":
        return await _handle_web_callback(request, token_set, state_payload)

    # Stamp the Telegram user session with the Jira identity so prompt
    # enrichment and tool context use the connected Jira account instead
    # of the primary Navigator login identity. The wrapper registers this
    # callable on the app when Jira commands are enabled.
    if state_payload.get("channel") == "telegram":
        telegram_user_id = state_payload.get("user_id")
        stamper = request.app.get("telegram_jira_session_stamper")
        if stamper is not None and telegram_user_id:
            try:
                stamper(str(telegram_user_id), token_set)
            except Exception:  # noqa: BLE001 - never break the browser flow
                logger.warning(
                    "telegram_jira_session_stamper failed for user_id=%s",
                    telegram_user_id,
                    exc_info=True,
                )

    # Fire-and-forget Telegram notification (does not block the browser response).
    notifier: "TelegramOAuthNotifier | None" = request.app.get("jira_oauth_notifier")
    if notifier is not None:
        extra = (state_payload.get("extra") or {})
        chat_id = extra.get("chat_id")
        if chat_id:
            asyncio.create_task(
                _notify_telegram(
                    notifier,
                    int(chat_id),
                    token_set.display_name or "",
                    token_set.site_url or "",
                )
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
    Optionally store a :class:`TelegramOAuthNotifier` at
    ``app['jira_oauth_notifier']`` to enable post-callback Telegram messages.
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
