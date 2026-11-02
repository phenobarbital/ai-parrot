"""Provider-generic Slack connection commands (FEAT-777 M2)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, Mapping, Optional

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.principal import resolve_principal

if TYPE_CHECKING:
    from parrot.auth.oauth2.service import IntegrationsService
    from parrot.auth.principal import Principal
    from parrot.integrations.slack.commands import SlackCommandRouter

logger = logging.getLogger(__name__)

_SLACK = "slack"
_LINK_FIRST = "Link your Slack account first: run `/login`."
_NOT_CONFIGURED = "Account linking is not configured."
_DENIED = "You are not permitted to do that."


def _ephemeral(text: str, **extra: Any) -> Dict[str, Any]:
    """Return an ephemeral Slack response."""
    return {"response_type": "ephemeral", "text": text, **extra}


def _ids(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return Slack team, user, and team-qualified user identifiers."""
    team_id = str(payload.get("team_id") or "")
    slack_user_id = str(payload.get("user_id") or "")
    return team_id, slack_user_id, f"{team_id}:{slack_user_id}"


def _provider_arg(payload: Mapping[str, Any], command: str) -> str:
    """Extract the provider argument from either Slack command payload shape."""
    words = str(payload.get("text") or "").split()
    if words and words[0].lower() == command:
        words.pop(0)
    return words[0].lower() if words else ""


def _provider_ids() -> list[str]:
    """Return registered OAuth provider IDs in registry order."""
    return [provider.provider_id for provider in OAuth2ProviderRegistry().all()]


def _unknown_provider_response() -> Dict[str, Any]:
    """Return the provider-selection response without creating OAuth state."""
    provider_ids = _provider_ids()
    if provider_ids:
        return _ephemeral(f"Choose a provider: {', '.join(provider_ids)}.")
    return _ephemeral("No connection providers are configured.")


def _connect_button(provider_id: str, url: str) -> Dict[str, Any]:
    """Build the Slack Block Kit authorization button response."""
    return _ephemeral(
        f"Click the button below to connect your {provider_id} account:",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Authorize your *{provider_id}* account:"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"Connect {provider_id}"},
                    "url": url,
                    "action_id": f"connect_{provider_id}_button",
                },
            }
        ],
    )


async def _principal(payload: Mapping[str, Any]) -> Optional["Principal"]:
    """Resolve the team-qualified Slack user to a platform principal."""
    team_id, slack_user_id, composite = _ids(payload)
    if not team_id or not slack_user_id:
        return None
    return await resolve_principal(_SLACK, composite)


class AppLinkIssuer:
    """Resolve ``app[\"channel_link_issuer\"]`` lazily at command time."""

    def __init__(self, app: Mapping[str, Any]) -> None:
        self._app = app

    async def issue(self, channel: str, channel_user_id: str, extra: Optional[Dict[str, str]] = None) -> str:
        """Issue a link through the startup-configured channel-link issuer."""
        issuer = self._app.get("channel_link_issuer")
        if issuer is None:
            raise LookupError("channel_link_issuer is not configured")
        return await issuer.issue(channel, channel_user_id, extra)


async def login_handler(payload: Dict[str, Any], link_issuer: Any) -> Dict[str, Any]:
    """Issue a one-time link for associating the Slack account with the web account."""
    team_id, slack_user_id, composite = _ids(payload)
    if await _principal(payload) is not None:
        return _ephemeral("Your Slack account is already linked to the platform.")
    try:
        url = await link_issuer.issue(_SLACK, composite, {"team_id": team_id, "slack_user_id": slack_user_id})
    except (ValueError, LookupError):
        logger.warning("Slack /login unavailable: channel linking is not configured")
        return _ephemeral(_NOT_CONFIGURED)
    return _ephemeral(
        "This link expires in 10 minutes. Open it while you are logged in to the platform.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "This link expires in 10 minutes. Open it while you are logged in to the platform.",
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Link account"},
                    "url": url,
                    "action_id": "link_account_button",
                },
            }
        ],
    )


async def connect_handler(
    payload: Dict[str, Any], provider_id: str, service_factory: Callable[[], "IntegrationsService"]
) -> Dict[str, Any]:
    """Start a provider connection for the linked Slack principal."""
    principal = await _principal(payload)
    if principal is None:
        return _ephemeral(_LINK_FIRST)
    provider_id = provider_id.strip().lower()
    if not provider_id or provider_id not in _provider_ids():
        return _unknown_provider_response()
    team_id, slack_user_id, _ = _ids(payload)
    try:
        response = await service_factory().start_connect(
            principal.user_id,
            provider_id,
            channel=_SLACK,
            principal=principal,
            extra_state={"team_id": team_id, "slack_user_id": slack_user_id},
        )
    except PermissionError:
        return _ephemeral(_DENIED)
    except ValueError:
        return _unknown_provider_response()
    return _connect_button(provider_id, response.auth_url)


async def disconnect_handler(
    payload: Dict[str, Any], provider_id: str, service_factory: Callable[[], "IntegrationsService"]
) -> Dict[str, Any]:
    """Disconnect a provider for the linked Slack principal."""
    principal = await _principal(payload)
    if principal is None:
        return _ephemeral(_LINK_FIRST)
    provider_id = provider_id.strip().lower()
    if not provider_id or provider_id not in _provider_ids():
        return _unknown_provider_response()
    try:
        await service_factory().disconnect(principal.user_id, provider_id, principal=principal)
    except PermissionError:
        return _ephemeral(_DENIED)
    except ValueError:
        return _unknown_provider_response()
    return _ephemeral(f"Disconnected {provider_id}.")


async def status_handler(
    payload: Dict[str, Any], provider_id: str, service_factory: Callable[[], "IntegrationsService"]
) -> Dict[str, Any]:
    """Report a provider connection status for the linked Slack principal."""
    principal = await _principal(payload)
    if principal is None:
        return _ephemeral(_LINK_FIRST)
    provider_id = provider_id.strip().lower()
    if not provider_id or provider_id not in _provider_ids():
        return _unknown_provider_response()
    try:
        descriptor = await service_factory().status(principal.user_id, provider_id, principal=principal)
    except PermissionError:
        return _ephemeral(_DENIED)
    except ValueError:
        return _unknown_provider_response()
    if descriptor.status == "connected":
        return _ephemeral(f"Connected as {descriptor.display_account_name or descriptor.display_name}.")
    return _ephemeral(f"Not connected to {descriptor.display_name}.")


async def connections_handler(
    payload: Dict[str, Any], service_factory: Callable[[], "IntegrationsService"]
) -> Dict[str, Any]:
    """List visible provider connections for the linked Slack principal."""
    principal = await _principal(payload)
    if principal is None:
        return _ephemeral(_LINK_FIRST)
    try:
        connections = await service_factory().list_for_principal(principal.user_id, principal=principal)
    except PermissionError:
        return _ephemeral(_DENIED)
    if not connections:
        return _ephemeral("No connections available.")
    lines = [
        f"{connection.display_name} — {connection.status} — {connection.display_account_name or 'No account'}"
        for connection in connections
    ]
    return _ephemeral("\n".join(lines))


def register_connection_commands(
    router: "SlackCommandRouter", *, link_issuer: Any, service_factory: Callable[[], "IntegrationsService"]
) -> None:
    """Register generic Slack connection commands and Jira aliases on ``router``."""

    async def _login(payload: Dict[str, Any]) -> Dict[str, Any]:
        return await login_handler(payload, link_issuer)

    async def _connect(payload: Dict[str, Any]) -> Dict[str, Any]:
        return await connect_handler(payload, _provider_arg(payload, "connect"), service_factory)

    async def _disconnect(payload: Dict[str, Any]) -> Dict[str, Any]:
        return await disconnect_handler(payload, _provider_arg(payload, "disconnect"), service_factory)

    async def _connections(payload: Dict[str, Any]) -> Dict[str, Any]:
        return await connections_handler(payload, service_factory)

    async def _connect_jira(payload: Dict[str, Any]) -> Dict[str, Any]:
        return await connect_handler(payload, "jira", service_factory)

    async def _disconnect_jira(payload: Dict[str, Any]) -> Dict[str, Any]:
        return await disconnect_handler(payload, "jira", service_factory)

    async def _jira_status(payload: Dict[str, Any]) -> Dict[str, Any]:
        return await status_handler(payload, "jira", service_factory)

    for name, handler in (
        ("login", _login),
        ("connect", _connect),
        ("disconnect", _disconnect),
        ("connections", _connections),
        ("connect_jira", _connect_jira),
        ("disconnect_jira", _disconnect_jira),
        ("jira_status", _jira_status),
    ):
        router.register(name, handler)
    logger.info("Registered Slack connection commands")
