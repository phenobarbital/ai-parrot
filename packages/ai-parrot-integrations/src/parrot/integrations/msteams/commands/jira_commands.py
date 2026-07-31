"""MS Teams command handlers for the Jira OAuth 2.0 (3LO) flow (FEAT-225).

Exposes three user-facing text commands:

- ``/connect_jira`` — generates a Jira authorization URL and sends an
  Adaptive Card with a "Connect Jira" button.
- ``/disconnect_jira`` — revokes the user's stored Jira tokens.
- ``/jira_status`` — reports whether a valid Jira connection is on file.
- ``jira`` / ``integrations`` — shows an Adaptive Card menu for Jira commands.

User identity is the ``aad_object_id`` (Azure AD object ID), falling back to
``from_property.id`` for non-AAD environments.

The ``conversation_reference`` is stored in ``extra_state`` so the OAuth
callback can send a proactive message after the user returns from Atlassian.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict

from botbuilder.core import TurnContext
from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION

if TYPE_CHECKING:
    from parrot.auth.jira_oauth import JiraOAuthManager
    from parrot.integrations.msteams.commands import MSTeamsCommandRouter

logger = logging.getLogger(__name__)

_MSTEAMS_CHANNEL = "msteams"


# ---------------------------------------------------------------------------
# Adaptive Card builders
# ---------------------------------------------------------------------------

def _connect_jira_card(auth_url: str) -> Dict[str, Any]:
    """Build an Adaptive Card with a 'Connect Jira' button.

    Args:
        auth_url: The Atlassian OAuth2 authorization URL.

    Returns:
        An Adaptive Card schema dict (version 1.4).
    """
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": DEFAULT_ADAPTIVE_CARD_VERSION,
        "body": [
            {
                "type": "TextBlock",
                "text": "Click the button below to authorize your **Jira** account:",
                "wrap": True,
            }
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "Connect Jira",
                "url": auth_url,
            }
        ],
    }


def _jira_menu_card() -> Dict[str, Any]:
    """Build an Adaptive Card menu listing all Jira commands.

    Returns:
        An Adaptive Card schema dict with three SubmitAction buttons.
    """
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": DEFAULT_ADAPTIVE_CARD_VERSION,
        "body": [
            {
                "type": "TextBlock",
                "text": "**Jira Integration Commands**",
                "weight": "Bolder",
                "size": "Medium",
            },
            {
                "type": "TextBlock",
                "text": "Use the commands below to manage your Jira connection:",
                "wrap": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Connect Jira",
                "data": {"command": "/connect_jira"},
            },
            {
                "type": "Action.Submit",
                "title": "Disconnect Jira",
                "data": {"command": "/disconnect_jira"},
            },
            {
                "type": "Action.Submit",
                "title": "Jira Status",
                "data": {"command": "/jira_status"},
            },
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_id(turn_context: "TurnContext") -> str:
    """Extract the Teams user identity.

    Prefers ``aad_object_id`` (globally unique across Azure AD tenants).
    Falls back to ``from_property.id`` for non-AAD environments.

    Args:
        turn_context: The current Bot Framework turn context.

    Returns:
        The user identity string used as the ``user_id`` in JiraOAuthManager.
    """
    aad_id = getattr(
        turn_context.activity.from_property, "aad_object_id", None
    )
    if aad_id:
        return aad_id
    return turn_context.activity.from_property.id


def _get_conversation_reference(turn_context: TurnContext) -> Dict[str, Any]:
    """Serialise the conversation reference for proactive messaging.

    Args:
        turn_context: The current Bot Framework turn context.

    Returns:
        A JSON-safe dict representation of the conversation reference.
    """
    try:
        conv_ref = TurnContext.get_conversation_reference(turn_context.activity)
        # serialize — ConversationReference is a Serializable object
        return json.loads(json.dumps(conv_ref.serialize()))
    except Exception:
        logger.warning(
            "Could not serialise conversation reference; proactive "
            "notification will not be available for this callback.",
            exc_info=True,
        )
        return {}


async def _send_adaptive_card(
    turn_context: "TurnContext", card: Dict[str, Any]
) -> None:
    """Send an Adaptive Card as an attachment.

    Args:
        turn_context: The current Bot Framework turn context.
        card: The Adaptive Card schema dict.
    """
    from botbuilder.schema import Activity, Attachment

    attachment = Attachment(
        content_type="application/vnd.microsoft.card.adaptive",
        content=card,
    )
    reply = Activity(
        type="message",
        attachments=[attachment],
    )
    await turn_context.send_activity(reply)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def connect_jira_handler(
    turn_context: "TurnContext",
    oauth_manager: "JiraOAuthManager",
) -> None:
    """Handle ``/connect_jira`` text command.

    Checks whether the user already has a valid Jira token. If yes, sends
    an "already connected" reply. Otherwise generates an auth URL and sends
    an Adaptive Card with a button.

    Args:
        turn_context: The current Bot Framework turn context.
        oauth_manager: Backing Jira OAuth manager.
    """
    user_id = _get_user_id(turn_context)
    existing = await oauth_manager.validate_token(_MSTEAMS_CHANNEL, user_id)
    if existing is not None:
        from botbuilder.schema import Activity
        await turn_context.send_activity(
            Activity(
                type="message",
                text=(
                    f"You're already connected to Jira as **{existing.display_name}**. "
                    "Use `/jira_status` to see details or `/disconnect_jira` to unlink."
                ),
            )
        )
        return

    conv_ref = _get_conversation_reference(turn_context)
    url, _nonce = await oauth_manager.create_authorization_url(
        _MSTEAMS_CHANNEL,
        user_id,
        extra_state={
            "channel": _MSTEAMS_CHANNEL,
            "user_id": user_id,
            "conversation_reference": conv_ref,
        },
    )
    await _send_adaptive_card(turn_context, _connect_jira_card(url))


async def disconnect_jira_handler(
    turn_context: "TurnContext",
    oauth_manager: "JiraOAuthManager",
) -> None:
    """Handle ``/disconnect_jira`` text command.

    Revokes stored Jira tokens and sends a confirmation reply.

    Args:
        turn_context: The current Bot Framework turn context.
        oauth_manager: Backing Jira OAuth manager.
    """
    user_id = _get_user_id(turn_context)
    await oauth_manager.revoke(_MSTEAMS_CHANNEL, user_id)
    from botbuilder.schema import Activity
    await turn_context.send_activity(
        Activity(type="message", text="Your Jira account has been disconnected.")
    )


async def jira_status_handler(
    turn_context: "TurnContext",
    oauth_manager: "JiraOAuthManager",
) -> None:
    """Handle ``/jira_status`` text command.

    Reports whether a valid Jira token is on file.

    Args:
        turn_context: The current Bot Framework turn context.
        oauth_manager: Backing Jira OAuth manager.
    """
    user_id = _get_user_id(turn_context)
    token = await oauth_manager.validate_token(_MSTEAMS_CHANNEL, user_id)
    from botbuilder.schema import Activity
    if token is not None:
        await turn_context.send_activity(
            Activity(
                type="message",
                text=(
                    f"Connected to Jira as **{token.display_name}**\n"
                    f"Site: {token.site_url}"
                ),
            )
        )
    else:
        await turn_context.send_activity(
            Activity(
                type="message",
                text="Not connected to Jira. Use `/connect_jira` to link your account.",
            )
        )


async def jira_menu_handler(
    turn_context: "TurnContext",
    oauth_manager: "JiraOAuthManager",  # noqa: ARG001 — kept for consistent signature
) -> None:
    """Show a discoverability menu with all Jira commands.

    Triggered by typing ``jira`` or ``integrations`` (without ``/`` prefix).
    Registered as plain-text handlers (not slash commands).

    Args:
        turn_context: The current Bot Framework turn context.
        oauth_manager: Backing Jira OAuth manager (unused, for signature parity).
    """
    await _send_adaptive_card(turn_context, _jira_menu_card())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_jira_commands(
    router: "MSTeamsCommandRouter",
    oauth_manager: "JiraOAuthManager",
) -> None:
    """Register Jira commands on *router*.

    Registers the three slash commands plus the ``jira`` and ``integrations``
    plain-text menu triggers.

    Args:
        router: Target :class:`MSTeamsCommandRouter` instance.
        oauth_manager: Backing Jira OAuth manager.
    """

    async def _connect(turn_context: "TurnContext") -> None:
        await connect_jira_handler(turn_context, oauth_manager)

    async def _disconnect(turn_context: "TurnContext") -> None:
        await disconnect_jira_handler(turn_context, oauth_manager)

    async def _status(turn_context: "TurnContext") -> None:
        await jira_status_handler(turn_context, oauth_manager)

    async def _menu(turn_context: "TurnContext") -> None:
        await jira_menu_handler(turn_context, oauth_manager)

    router.register("connect_jira", _connect)
    router.register("disconnect_jira", _disconnect)
    router.register("jira_status", _status)
    # Plain-text triggers for discoverability.  "jira" and "integrations" are
    # NOT slash commands, so they won't be caught by try_dispatch's
    # startswith("/") guard.  Register them directly under the plain-text keys
    # so that try_dispatch_plain can resolve them by exact match.
    router.register("jira", _menu)
    router.register("integrations", _menu)
    logger.info("Registered Jira commands on MSTeamsCommandRouter")
