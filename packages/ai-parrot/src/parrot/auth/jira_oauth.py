"""Jira OAuth 2.0 provider backed by the standard OAuth engine."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlencode

import aiohttp
from pydantic import Field

from parrot.auth.oauth2.descriptor import (
    OAuth2ProviderDescriptor,
    RefreshPolicy,
    StandardOAuth2Manager,
    post_exchange_hooks,
)
from parrot.auth.oauth2_base import AbstractOAuth2TokenSet, CredentialStore, _legacy_window_open
from parrot.auth.principal import Principal, resolve_principal

AUTHORIZATION_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ACCESSIBLE_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"

_TOKEN_KEY_PREFIX = "jira:oauth"
# Historical Jira layout (read-only during the migration window): jira:oauth:{channel}:{channel_user_id}
_LEGACY_JIRA_TOKEN_KEY_TEMPLATE = "{prefix}:{channel}:{channel_user_id}"

DEFAULT_SCOPES: List[str] = [
    "read:jira-work",
    "write:jira-work",
    "read:jira-user",
    "offline_access",
]


class JiraTokenSet(AbstractOAuth2TokenSet):
    """OAuth token set enriched with the selected Atlassian cloud site."""

    cloud_id: str = ""
    site_url: str = ""
    available_sites: List[Dict[str, Any]] = Field(default_factory=list)

    @property
    def api_base_url(self) -> str:
        """Return the Atlassian REST API base URL for this cloud."""
        return f"https://api.atlassian.com/ex/jira/{self.cloud_id}"


JIRA_DESCRIPTOR = OAuth2ProviderDescriptor(
    provider_id="jira",
    display_name="Jira",
    icon="mdi:jira",
    authorization_url=AUTHORIZATION_URL,
    token_url=TOKEN_URL,
    default_scopes=list(DEFAULT_SCOPES),
    client_type="confidential",
    pkce="none",
    refresh_policy=RefreshPolicy(rotating=True, sliding=True, refresh_lifetime_s=90 * 86400),
    extra_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
    post_exchange="atlassian_accessible_resources",
)


_MAX_ERROR_BODY_CHARS = 200


def _truncate(text: str, limit: int = _MAX_ERROR_BODY_CHARS) -> str:
    """Bound an HTTP error body before it is embedded in an exception message."""
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…[truncated]"


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: Sequence[str] = DEFAULT_SCOPES,
    authorization_url: str = AUTHORIZATION_URL,
) -> str:
    """Build the Atlassian 3LO authorization URL.

    Args:
        client_id: OAuth app client id.
        redirect_uri: Registered callback URL.
        state: CSRF state nonce.
        scopes: Scopes to request.
        authorization_url: Authorization endpoint override.

    Returns:
        The full authorization URL with query string.
    """
    params = {
        "audience": "api.atlassian.com",
        "client_id": client_id,
        "scope": " ".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    return f"{authorization_url}?{urlencode(params)}"


async def exchange_code(
    session: aiohttp.ClientSession,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    token_url: str = TOKEN_URL,
) -> Dict[str, Any]:
    """Exchange an authorization code for tokens.

    Raises:
        ValueError: If the token endpoint answers with a non-200 status.
    """
    async with session.post(
        token_url,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
    ) as response:
        if response.status != 200:
            text = await response.text()
            raise ValueError(f"Token exchange failed with status {response.status}: {_truncate(text)}")
        return await response.json()


async def refresh_access_token(
    session: aiohttp.ClientSession,
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    token_url: str = TOKEN_URL,
) -> Dict[str, Any]:
    """Refresh an access token using the rotating refresh token.

    Raises:
        ValueError: If the token endpoint answers with a non-200 status.
    """
    async with session.post(
        token_url,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
    ) as response:
        if response.status != 200:
            text = await response.text()
            raise ValueError(f"Token refresh failed with status {response.status}: {_truncate(text)}")
        return await response.json()


async def fetch_accessible_resources(
    session: aiohttp.ClientSession,
    access_token: str,
    url: str = ACCESSIBLE_RESOURCES_URL,
) -> List[Dict[str, Any]]:
    """Fetch the Atlassian sites available to an access token."""
    async with session.get(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    ) as response:
        if response.status != 200:
            raise ValueError(f"accessible-resources failed with status {response.status}")
        data = await response.json()
    if not isinstance(data, list):
        raise ValueError("accessible-resources returned a non-list payload.")
    return data


async def fetch_myself(session: aiohttp.ClientSession, access_token: str, cloud_id: str) -> Dict[str, Any]:
    """Fetch the authenticated user's profile from an Atlassian cloud."""
    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself"
    async with session.get(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    ) as response:
        if response.status != 200:
            raise ValueError(f"/myself failed with status {response.status}")
        data = await response.json()
    if not isinstance(data, dict):
        raise ValueError("/myself returned a non-object payload.")
    return data


async def _atlassian_accessible_resources(
    manager: Any,
    token_response: Dict[str, Any],
    token_set: AbstractOAuth2TokenSet,
) -> JiraTokenSet:
    """Fill the selected Atlassian site and profile after token exchange."""
    del token_response
    session = await manager._get_session()
    sites = await fetch_accessible_resources(session, token_set.access_token)
    if not sites:
        raise ValueError("No accessible Atlassian resources for this user.")
    primary = sites[0]
    cloud_id = str(primary.get("id", ""))
    site_url = str(primary.get("url", ""))
    if not cloud_id or not site_url:
        raise ValueError("Accessible Atlassian resource is missing id or url.")
    myself = await fetch_myself(session, token_set.access_token, cloud_id)
    return JiraTokenSet(
        **token_set.model_dump(),
        cloud_id=cloud_id,
        site_url=site_url,
        available_sites=sites,
        account_id=str(myself.get("accountId", "")),
        display_name=str(myself.get("displayName", "")),
        email=myself.get("emailAddress"),
    )


post_exchange_hooks.register("atlassian_accessible_resources", _atlassian_accessible_resources)


class JiraOAuthManager(StandardOAuth2Manager):
    """Atlassian 3LO manager on the generic OAuth engine."""

    token_set_cls = JiraTokenSet

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        app: Any = None,
        redis_url: Optional[str] = None,
        redis_client: Any = None,
        scopes: Optional[List[str]] = None,
        http_session: Optional[aiohttp.ClientSession] = None,
        credential_store: Optional[CredentialStore] = None,
        event_publisher: Any = None,
        callback_path: str = "/api/auth/jira/callback",
    ) -> None:
        super().__init__(
            JIRA_DESCRIPTOR,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            app=app,
            redis_url=redis_url,
            redis_client=redis_client,
            scopes=scopes,
            http_session=http_session,
            credential_store=credential_store,
            event_publisher=event_publisher,
            callback_path=callback_path,
        )

    def setup(self) -> None:
        """Mount the Jira compatibility callback route once."""
        if self._setup_done:
            return
        if self._app is None:
            raise RuntimeError("JiraOAuthManager.setup() requires app= in the constructor.")
        app = self._app
        for key in ("jira_oauth_manager", "oauth2_manager_jira"):
            existing = app.get(key)
            if existing is not None and existing is not self:
                raise RuntimeError(f"app[{key!r}] is already set to a different JiraOAuthManager instance.")
        app["jira_oauth_manager"] = self
        app["oauth2_manager_jira"] = self
        app.on_startup.append(self._on_startup)
        app.on_cleanup.append(self._on_cleanup)
        from parrot.auth.routes import setup_jira_oauth_routes

        setup_jira_oauth_routes(app)
        self._setup_done = True

    async def validate_token(self, channel: str, user_id: str) -> Optional[JiraTokenSet]:
        """Return a live Jira token, removing it when Atlassian rejects it."""
        principal = await resolve_principal(channel, user_id)
        if principal is None:
            return None
        token = await self.get_valid_token(channel, principal.user_id, channel_user_id=principal.channel_user_id)
        if token is None:
            return None
        session = await self._get_session()
        try:
            async with session.get(
                f"{token.api_base_url}/rest/api/3/myself",
                headers={"Authorization": f"Bearer {token.access_token}", "Accept": "application/json"},
            ) as response:
                status = response.status
        except aiohttp.ClientError as exc:
            self.logger.warning("Jira /myself probe transport error: %s", exc)
            return token
        if status in (401, 403):
            await self.revoke(channel, principal.user_id, channel_user_id=principal.channel_user_id)
            return None
        return token  # type: ignore[return-value]

    async def _read_legacy_token(
        self,
        channel: str,
        channel_user_id: str,
        user_id: str,
    ) -> Optional[JiraTokenSet]:
        """Migrate generic or historical Jira channel-scoped tokens once."""
        token = await super()._read_legacy_token(channel, channel_user_id, user_id)
        if token is not None or not _legacy_window_open():
            return token  # type: ignore[return-value]

        legacy_key = _LEGACY_JIRA_TOKEN_KEY_TEMPLATE.format(
            prefix=_TOKEN_KEY_PREFIX, channel=channel, channel_user_id=channel_user_id
        )
        raw = await self.redis.get(legacy_key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            legacy_token = JiraTokenSet.model_validate_json(raw)
        except Exception as exc:  # pragma: no cover - corrupted legacy payload
            self.logger.warning("Corrupted Jira legacy token for channel %s: %s", channel, type(exc).__name__)
            return None
        principal = Principal(user_id=user_id, channel=channel, channel_user_id=channel_user_id)
        await self._persist_token(principal, legacy_token, minted=True)
        try:
            await self.redis.delete(legacy_key)
        except Exception as exc:  # pragma: no cover - delete failures retain an idempotent source
            self.logger.warning("Jira legacy cache delete failed for principal %s: %s", user_id, type(exc).__name__)
        return legacy_token

    def _public_metadata(self, token_set: Any) -> Dict[str, Any]:
        """Expose Jira site metadata without exposing token material."""
        return {"site_url": getattr(token_set, "site_url", ""), "cloud_id": getattr(token_set, "cloud_id", "")}
