"""Slack command handlers for the Jira OAuth 2.0 (3LO) flow (FEAT-225).

Exposes three user-facing slash commands:

- ``/connect_jira`` — generates a Jira authorization URL and returns an
  ephemeral message with a button linking to the consent page.
- ``/disconnect_jira`` — revokes the user's stored Jira tokens.
- ``/jira_status`` — reports whether a valid Jira connection is on file.

All handlers are registered on a :class:`SlackCommandRouter` via
:func:`register_jira_commands`.

User identity in ``JiraOAuthManager`` is keyed as
``f"{team_id}:{slack_user_id}"`` to be multi-workspace safe.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from parrot.auth.jira_oauth import JiraOAuthManager
    from parrot.integrations.slack.commands import SlackCommandRouter

logger = logging.getLogger(__name__)

_SLACK_CHANNEL = "slack"


def _build_connect_button(url: str) -> Dict[str, Any]:
    """Build a Slack Block Kit section with a Connect Jira button.

    Args:
        url: The Atlassian OAuth2 authorization URL.

    Returns:
        A Slack Block Kit blocks list with a button action.
    """
    return {
        "response_type": "ephemeral",
        "text": "Click the button below to connect your Jira account:",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Click the button below to authorize your *Jira* account:",
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Connect Jira"},
                    "url": url,
                    "action_id": "connect_jira_button",
                },
            }
        ],
    }


async def connect_jira_handler(
    payload: Dict[str, Any],
    oauth_manager: "JiraOAuthManager",
) -> Dict[str, Any]:
    """Handle ``/connect_jira`` slash command.

    Checks whether the user already has a valid Jira token. If yes, returns
    an "already connected" ephemeral. If no, generates an auth URL and sends
    an ephemeral message with a button.

    Args:
        payload: Slack slash-command POST data (team_id, user_id, channel_id, …).
        oauth_manager: Backing Jira OAuth manager.

    Returns:
        An ephemeral response dict suitable for Slack's slash-command response.
    """
    team_id = payload.get("team_id", "")
    slack_user_id = payload.get("user_id", "")
    user_id = f"{team_id}:{slack_user_id}"

    existing = await oauth_manager.validate_token(_SLACK_CHANNEL, user_id)
    if existing is not None:
        return {
            "response_type": "ephemeral",
            "text": (
                f"You're already connected to Jira as *{existing.display_name}*. "
                "Use `/jira_status` to see details or `/disconnect_jira` to unlink."
            ),
        }

    url, _nonce = await oauth_manager.create_authorization_url(
        _SLACK_CHANNEL,
        user_id,
        extra_state={
            "channel": _SLACK_CHANNEL,
            "team_id": team_id,
            "slack_user_id": slack_user_id,
        },
    )
    return _build_connect_button(url)


async def disconnect_jira_handler(
    payload: Dict[str, Any],
    oauth_manager: "JiraOAuthManager",
) -> Dict[str, Any]:
    """Handle ``/disconnect_jira`` slash command.

    Revokes the user's stored Jira tokens and confirms disconnection.

    Args:
        payload: Slack slash-command POST data.
        oauth_manager: Backing Jira OAuth manager.

    Returns:
        An ephemeral response dict confirming disconnection.
    """
    team_id = payload.get("team_id", "")
    slack_user_id = payload.get("user_id", "")
    user_id = f"{team_id}:{slack_user_id}"

    await oauth_manager.revoke(_SLACK_CHANNEL, user_id)
    logger.info(
        "Jira disconnected for Slack user %s (team=%s)", slack_user_id, team_id
    )
    return {
        "response_type": "ephemeral",
        "text": "Your Jira account has been disconnected.",
    }


async def jira_status_handler(
    payload: Dict[str, Any],
    oauth_manager: "JiraOAuthManager",
) -> Dict[str, Any]:
    """Handle ``/jira_status`` slash command.

    Reports whether a valid Jira token is on file for the calling user.

    Args:
        payload: Slack slash-command POST data.
        oauth_manager: Backing Jira OAuth manager.

    Returns:
        An ephemeral response dict with connection status.
    """
    team_id = payload.get("team_id", "")
    slack_user_id = payload.get("user_id", "")
    user_id = f"{team_id}:{slack_user_id}"

    token = await oauth_manager.validate_token(_SLACK_CHANNEL, user_id)
    if token is not None:
        return {
            "response_type": "ephemeral",
            "text": (
                f"Connected to Jira as *{token.display_name}*\n"
                f"Site: {token.site_url}"
            ),
        }
    return {
        "response_type": "ephemeral",
        "text": "Not connected to Jira. Use `/connect_jira` to link your account.",
    }


def register_jira_commands(
    router: "SlackCommandRouter",
    oauth_manager: "JiraOAuthManager",
) -> None:
    """Register the three Jira commands on *router*.

    The handlers are closed over the provided ``oauth_manager``, so there is
    no need to thread it through as a request-time dependency.

    Args:
        router: Target :class:`SlackCommandRouter` instance.
        oauth_manager: Backing Jira OAuth manager.
    """

    async def _connect(payload: Dict[str, Any]) -> Dict[str, Any]:
        return await connect_jira_handler(payload, oauth_manager)

    async def _disconnect(payload: Dict[str, Any]) -> Dict[str, Any]:
        return await disconnect_jira_handler(payload, oauth_manager)

    async def _status(payload: Dict[str, Any]) -> Dict[str, Any]:
        return await jira_status_handler(payload, oauth_manager)

    router.register("connect_jira", _connect)
    router.register("disconnect_jira", _disconnect)
    router.register("jira_status", _status)
    logger.info("Registered Jira commands on SlackCommandRouter")
