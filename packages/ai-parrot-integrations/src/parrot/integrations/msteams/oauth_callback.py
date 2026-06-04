"""MS Teams OAuth callback helpers for Jira 3LO flow (FEAT-225).

After a Teams user authorizes their Jira account, Atlassian redirects to
``/api/auth/jira/callback``.  When ``extra_state["channel"] == "msteams"``
this module handles:

1. Writing an ``auth.user_identities`` row via :class:`IdentityMappingService`.
2. Returning a plain HTML success/error page shown in the user's browser.
3. Sending a proactive message to the Teams conversation using the Bot
   Framework adapter and the stored ``conversation_reference``.

Unlike Slack (DM via Web API), Teams uses the Bot Framework proactive
messaging pattern: ``adapter.continue_conversation(ref, callback, app_id)``.
The ``conversation_reference`` was serialized to JSON and stored in
``extra_state`` during ``/connect_jira`` command handling.

The notifier must be registered on the aiohttp app as
``app["msteams_jira_oauth_notifier"]`` by :class:`MSTeamsAgentWrapper` during
``__init__`` (wired in TASK-1473).
"""
from __future__ import annotations

import asyncio
import html
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from aiohttp import web
    from botbuilder.core import BotFrameworkAdapter
    from parrot.auth.jira_oauth import JiraTokenSet

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

_MSTEAMS_SUCCESS_HTML = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Jira Connected</title>
<style>
body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#f5f5f5}}
.container{{text-align:center;padding:2rem}}
.check{{font-size:3rem;color:#36b37e}}
.teams{{color:#6264A7;font-weight:bold}}
</style>
</head><body><div class="container">
<div class="check">&#10003;</div>
<h2>Jira Connected!</h2>
<p>Hi <strong>{display_name}</strong>! Your Jira account
(<strong>{site_url}</strong>) is now linked.</p>
<p>You can close this tab and return to <span class="teams">Microsoft Teams</span>.</p>
</div></body></html>"""

_MSTEAMS_ERROR_HTML = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Authorization Failed</title>
<style>
body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#f5f5f5}}
.container{{text-align:center;padding:2rem}}
.x{{font-size:3rem;color:#de350b}}
.teams{{color:#6264A7;font-weight:bold}}
</style>
</head><body><div class="container">
<div class="x">&#10007;</div>
<h2>Authorization Failed</h2>
<p>{error}</p>
<p>Please return to <span class="teams">Microsoft Teams</span> and try again.</p>
</div></body></html>"""


# ---------------------------------------------------------------------------
# Notifier
# ---------------------------------------------------------------------------

class MSTeamsOAuthNotifier:
    """Send a proactive message to a Teams user after a successful Jira OAuth callback.

    Uses ``adapter.continue_conversation`` from the Bot Framework to push a
    confirmation into the existing 1:1 conversation.

    Args:
        adapter: The Bot Framework adapter (from :class:`MSTeamsAgentWrapper`).
        app_id: The Microsoft App ID (``MSTeamsAgentConfig.client_id``).
    """

    def __init__(self, adapter: "BotFrameworkAdapter", app_id: str) -> None:
        self._adapter = adapter
        self._app_id = app_id
        self.logger = logger

    async def notify_connected(
        self,
        conversation_ref_dict: Dict[str, Any],
        display_name: str,
        site_url: str,
    ) -> None:
        """Send a proactive "connected" message to the Teams conversation.

        Args:
            conversation_ref_dict: Serialized ``ConversationReference`` dict
                (stored in ``extra_state`` during ``/connect_jira``).
            display_name: Jira display name from the token set.
            site_url: Atlassian site URL from the token set.
        """
        try:
            from botbuilder.schema import ConversationReference

            conv_ref = ConversationReference.deserialize(conversation_ref_dict)

            async def _callback(turn_context: Any) -> None:
                from botbuilder.schema import Activity
                await turn_context.send_activity(
                    Activity(
                        type="message",
                        text=(
                            f"Jira connected as **{display_name}** ({site_url}). "
                            "You can now use the Jira tools in this conversation."
                        ),
                    )
                )

            await self._adapter.continue_conversation(
                conv_ref, _callback, self._app_id
            )
        except Exception:  # noqa: BLE001 — notification must never break callback
            self.logger.exception(
                "Failed to send proactive Teams message for Jira connection",
            )

    async def notify_failure(
        self,
        conversation_ref_dict: Dict[str, Any],
        reason: str,
    ) -> None:
        """Send a proactive error message to the Teams conversation.

        Args:
            conversation_ref_dict: Serialized ``ConversationReference`` dict.
            reason: Human-readable error description.
        """
        try:
            from botbuilder.schema import ConversationReference

            conv_ref = ConversationReference.deserialize(conversation_ref_dict)

            async def _callback(turn_context: Any) -> None:
                from botbuilder.schema import Activity
                await turn_context.send_activity(
                    Activity(
                        type="message",
                        text=f"Jira authorization failed: {reason}",
                    )
                )

            await self._adapter.continue_conversation(
                conv_ref, _callback, self._app_id
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "Failed to send proactive Teams failure message",
            )


# ---------------------------------------------------------------------------
# Callback handler helper
# ---------------------------------------------------------------------------

async def handle_msteams_jira_callback(
    request: "web.Request",
    token_set: "JiraTokenSet",
    state_payload: Dict[str, Any],
) -> "web.Response":
    """Process a Jira OAuth callback originating from the MS Teams integration.

    Responsibilities:
    1. Return an HTML error page when Atlassian reports a consent denial
       (``?error=`` query param is present), and optionally send a proactive
       Teams message to the user.
    2. Write an ``auth.user_identities`` row (if
       ``identity_mapping_service`` is available on the app).
    3. Fire a proactive Teams notification via
       ``app["msteams_jira_oauth_notifier"]`` (fire-and-forget).
    4. Return an HTML success page that instructs the user to return to Teams.

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
            "MS Teams Jira OAuth callback received error: %s — %s",
            error_code,
            error_description,
        )
        conv_ref_err: Dict[str, Any] = state_payload.get("conversation_reference") or {}
        notifier_err: Optional[MSTeamsOAuthNotifier] = request.app.get(
            "msteams_jira_oauth_notifier"
        )
        if notifier_err is not None and conv_ref_err:
            asyncio.create_task(
                notifier_err.notify_failure(
                    conversation_ref_dict=conv_ref_err,
                    reason=error_description,
                )
            )
        return web.Response(
            text=_MSTEAMS_ERROR_HTML.format(error=html.escape(error_description)),
            content_type="text/html",
        )

    conv_ref: Dict[str, Any] = state_payload.get("conversation_reference") or {}
    nav_user_id: str = state_payload.get("user_id", "")

    # 1. Persist identity mapping row
    identity_service = request.app.get("identity_mapping_service")
    if identity_service is not None and nav_user_id:
        try:
            await identity_service.upsert_identity(
                nav_user_id=nav_user_id,
                auth_provider="msteams",
                auth_data={
                    "aad_object_id": nav_user_id,
                    # tenant_id may be available from the conversation_reference
                    "tenant_id": (
                        conv_ref.get("conversation", {}).get("tenantId")
                        or conv_ref.get("activity", {}).get("channelData", {}).get("tenant", {}).get("id")
                        or ""
                    ),
                },
                display_name=token_set.display_name or None,
                email=token_set.email or None,
            )
        except Exception:  # noqa: BLE001 — identity write must not break browser flow
            logger.exception(
                "Failed to write auth.user_identities for Teams user=%s",
                nav_user_id,
            )

    # 2. Fire-and-forget proactive notification
    notifier: Optional[MSTeamsOAuthNotifier] = request.app.get(
        "msteams_jira_oauth_notifier"
    )
    if notifier is not None and conv_ref:
        asyncio.create_task(
            notifier.notify_connected(
                conversation_ref_dict=conv_ref,
                display_name=token_set.display_name or "",
                site_url=token_set.site_url or "",
            )
        )

    # 3. Return HTML success page
    return web.Response(
        text=_MSTEAMS_SUCCESS_HTML.format(
            display_name=html.escape(token_set.display_name or ""),
            site_url=html.escape(token_set.site_url or ""),
        ),
        content_type="text/html",
    )
