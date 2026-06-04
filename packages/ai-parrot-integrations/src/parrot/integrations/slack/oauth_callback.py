"""Slack OAuth callback helpers for Jira 3LO flow (FEAT-225).

After a Slack user authorizes their Jira account, Atlassian redirects to
``/api/auth/jira/callback``.  When ``extra_state["channel"] == "slack"``
this module handles:

1. Writing an ``auth.user_identities`` row via :class:`IdentityMappingService`.
2. Returning a plain HTML success/error page shown in the user's browser.
3. Firing a DM notification via :class:`SlackOAuthNotifier` (fire-and-forget).

The notifier must be registered on the aiohttp app as
``app["slack_jira_oauth_notifier"]`` by :class:`SlackAgentWrapper` during
``__init__`` (wired in TASK-1470).
"""
from __future__ import annotations

import asyncio
import html
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from aiohttp import web
    from parrot.auth.jira_oauth import JiraTokenSet

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

_SLACK_SUCCESS_HTML = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Jira Connected</title>
<style>
body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#f5f5f5}}
.container{{text-align:center;padding:2rem}}
.check{{font-size:3rem;color:#36b37e}}
.slack{{color:#4A154B;font-weight:bold}}
</style>
</head><body><div class="container">
<div class="check">&#10003;</div>
<h2>Jira Connected!</h2>
<p>Hi <strong>{display_name}</strong>! Your Jira account
(<strong>{site_url}</strong>) is now linked.</p>
<p>You can close this tab and return to <span class="slack">Slack</span>.</p>
</div></body></html>"""

_SLACK_ERROR_HTML = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Authorization Failed</title>
<style>
body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#f5f5f5}}
.container{{text-align:center;padding:2rem}}
.x{{font-size:3rem;color:#de350b}}
.slack{{color:#4A154B;font-weight:bold}}
</style>
</head><body><div class="container">
<div class="x">&#10007;</div>
<h2>Authorization Failed</h2>
<p>{error}</p>
<p>Please return to <span class="slack">Slack</span> and try again.</p>
</div></body></html>"""


# ---------------------------------------------------------------------------
# Notifier
# ---------------------------------------------------------------------------

class SlackOAuthNotifier:
    """Push a DM confirmation to a Slack user after a successful Jira OAuth callback.

    Uses the Slack Web API ``chat.postMessage`` method with the user's Slack ID
    as the ``channel`` parameter, which opens a DM thread.

    Args:
        bot_token: Slack bot token (``xoxb-…``) used to authenticate API calls.
    """

    def __init__(self, bot_token: str) -> None:
        try:
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "slack-sdk is required for SlackOAuthNotifier. "
                "Install it with: pip install slack-sdk"
            ) from exc

        self._bot_token = bot_token
        self._client = AsyncWebClient(token=bot_token)
        self.logger = logger

    async def notify_connected(
        self,
        team_id: str,
        slack_user_id: str,
        display_name: str,
        site_url: str,
    ) -> None:
        """Send a DM to *slack_user_id* confirming Jira connection.

        Args:
            team_id: Slack workspace team ID (used for logging).
            slack_user_id: Slack user ID who connected their Jira account.
            display_name: Jira display name from the token set.
            site_url: Atlassian site URL from the token set.
        """
        try:
            await self._client.chat_postMessage(
                channel=slack_user_id,
                text=(
                    f"Jira connected as *{display_name}* ({site_url}). "
                    "You can now use the Jira tools in this workspace."
                ),
            )
        except Exception:  # noqa: BLE001 — DM failure must never break the callback
            self.logger.exception(
                "Failed to DM Slack user %s (team=%s) for Jira connection",
                slack_user_id,
                team_id,
            )

    async def notify_failure(
        self,
        team_id: str,
        slack_user_id: str,
        reason: str,
    ) -> None:
        """Send a DM to *slack_user_id* reporting a Jira OAuth failure.

        Args:
            team_id: Slack workspace team ID (used for logging).
            slack_user_id: Slack user ID who attempted to connect.
            reason: Human-readable error description.
        """
        try:
            await self._client.chat_postMessage(
                channel=slack_user_id,
                text=f"Jira authorization failed: {reason}",
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "Failed to DM Slack user %s (team=%s) for Jira failure",
                slack_user_id,
                team_id,
            )


# ---------------------------------------------------------------------------
# Callback handler helper
# ---------------------------------------------------------------------------

async def handle_slack_jira_callback(
    request: "web.Request",
    token_set: "JiraTokenSet",
    state_payload: Dict[str, Any],
) -> "web.Response":
    """Process a Jira OAuth callback originating from the Slack integration.

    Responsibilities:
    1. Return an HTML error page when Atlassian reports a consent denial
       (``?error=`` query param is present), and optionally DM the user.
    2. Write an ``auth.user_identities`` row (if
       ``identity_mapping_service`` is available on the app).
    3. Fire a DM notification via ``app["slack_jira_oauth_notifier"]``
       (fire-and-forget).
    4. Return an HTML success page that instructs the user to return to Slack.

    Args:
        request: The incoming aiohttp request.
        token_set: Token and identity data from ``JiraOAuthManager.handle_callback``.
        state_payload: Parsed ``extra_state`` from the CSRF nonce.

    Returns:
        HTML :class:`aiohttp.web.Response` for the browser.
    """
    from aiohttp import web

    # Handle Atlassian consent denial or other OAuth errors carried as query params.
    error_code = request.rel_url.query.get("error")
    if error_code:
        error_description = request.rel_url.query.get(
            "error_description", error_code
        )
        logger.warning(
            "Slack Jira OAuth callback received error: %s — %s",
            error_code,
            error_description,
        )
        team_id_err: str = state_payload.get("team_id", "")
        slack_user_id_err: str = state_payload.get("slack_user_id", "")
        notifier_err: Optional[SlackOAuthNotifier] = request.app.get(
            "slack_jira_oauth_notifier"
        )
        if notifier_err is not None and slack_user_id_err:
            asyncio.create_task(
                notifier_err.notify_failure(
                    team_id=team_id_err,
                    slack_user_id=slack_user_id_err,
                    reason=error_description,
                )
            )
        return web.Response(
            text=_SLACK_ERROR_HTML.format(error=html.escape(error_description)),
            content_type="text/html",
        )

    team_id: str = state_payload.get("team_id", "")
    slack_user_id: str = state_payload.get("slack_user_id", "")
    # The composite user_id used in JiraOAuthManager
    nav_user_id: str = state_payload.get("user_id", f"{team_id}:{slack_user_id}")

    # 1. Persist identity mapping row
    identity_service = request.app.get("identity_mapping_service")
    if identity_service is not None and slack_user_id:
        try:
            await identity_service.upsert_identity(
                nav_user_id=nav_user_id,
                auth_provider="slack",
                auth_data={
                    "team_id": team_id,
                    "slack_user_id": slack_user_id,
                },
                display_name=token_set.display_name or None,
                email=token_set.email or None,
            )
        except Exception:  # noqa: BLE001 — identity write must not break browser flow
            logger.exception(
                "Failed to write auth.user_identities for Slack user=%s team=%s",
                slack_user_id,
                team_id,
            )

    # 2. Fire-and-forget DM notification
    notifier: Optional[SlackOAuthNotifier] = request.app.get("slack_jira_oauth_notifier")
    if notifier is not None and slack_user_id:
        asyncio.create_task(
            notifier.notify_connected(
                team_id=team_id,
                slack_user_id=slack_user_id,
                display_name=token_set.display_name or "",
                site_url=token_set.site_url or "",
            )
        )

    # 3. Return HTML success page
    return web.Response(
        text=_SLACK_SUCCESS_HTML.format(
            display_name=html.escape(token_set.display_name or ""),
            site_url=html.escape(token_set.site_url or ""),
        ),
        content_type="text/html",
    )
