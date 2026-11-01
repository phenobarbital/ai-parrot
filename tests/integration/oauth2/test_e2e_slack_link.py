"""Slack link → connect flows (FEAT-777 AC-5, AC-6, AC-14)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, patch

import pytest
import redis.asyncio as aioredis
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.auth.channel_link import ChannelLinkIssuer
from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEventPublisher
from parrot.auth.oauth2.jira_provider import JiraOAuth2Provider
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.oauth2_routes import make_oauth2_callback
from parrot.auth.principal import Principal, set_principal_resolver
from parrot.handlers.channel_links import ChannelLinksHandler
from parrot.integrations.slack.commands import SlackCommandRouter
from parrot.integrations.slack.commands.connection_commands import register_connection_commands
from parrot.auth.oauth2.service import IntegrationsService

from .test_connections_isolation_matrix import FakeCredentialStore, FakeManager

pytestmark = pytest.mark.asyncio

REDIS_TEST_URL = "redis://localhost:6379/15"


class _Request(dict):
    """Minimal request carrying the session, route and application state."""

    def __init__(self, *, user_id: str, issuer: object, authdb: object, path: str, body: object = None) -> None:
        super().__init__()
        self.session = {"user_id": user_id}
        self.match_info = {"nonce": "unused"}
        self.app = {"channel_link_issuer": issuer, "authdb": authdb}
        self.path = path
        self._body = body

    def get(self, key: str, default: object = None) -> object:
        """Return no direct identity so handler session extraction is exercised."""
        return default

    async def json(self) -> object:
        """Return the configured JSON body."""
        return self._body


def _nonce(link: str) -> str:
    """Extract the opaque token from a channel-link URL."""
    return parse_qs(urlparse(link).query)["token"][0]


def _handler(request: _Request) -> ChannelLinksHandler:
    """Build a handler without running aiohttp decorators."""
    handler = ChannelLinksHandler.__new__(ChannelLinksHandler)
    handler._request = request
    return handler


def _unwrap(method):
    """Remove authentication decorators for direct handler integration tests."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


@pytest.fixture
async def redis_client():
    """Yield Redis db 15 or skip when the integration dependency is unavailable."""
    client = aioredis.from_url(REDIS_TEST_URL, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        await client.aclose()
        pytest.skip(f"Redis unreachable: {exc}")
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def reset_process_state() -> None:
    """Reset process-wide registries and principal resolution around each flow."""
    OAuth2ProviderRegistry._reset()
    set_principal_resolver(None)
    yield
    OAuth2ProviderRegistry._reset()
    set_principal_resolver(None)


class _IdentityMapping:
    """Exclusive-ownership double used by the channel-link handler."""

    def __init__(self, owners: dict[str, str]) -> None:
        self._owners = owners

    async def claim_channel_identity(self, **kwargs: str) -> SimpleNamespace:
        """Claim a Slack identity once, returning the production status shape."""
        identity = kwargs["provider_user_id"]
        owner = self._owners.get(identity)
        if owner is None:
            self._owners[identity] = kwargs["nav_user_id"]
            return SimpleNamespace(status="claimed")
        if owner == kwargs["nav_user_id"]:
            return SimpleNamespace(status="already_owned")
        return SimpleNamespace(status="conflict")


class _Resolver:
    """Resolver backed by the identity ownership double."""

    def __init__(self, owners: dict[str, str]) -> None:
        self._owners = owners

    async def resolve(self, channel: str, channel_user_id: str) -> Principal | None:
        """Resolve the team-qualified Slack identity when it has an owner."""
        user_id = self._owners.get(channel_user_id) if channel == "slack" else None
        if user_id is None:
            return None
        return Principal(user_id=user_id, channel=channel, channel_user_id=channel_user_id)


class _AllowAuthorizer:
    """Allow-all connection authorizer for the authorized Slack connect path."""

    async def authorize(self, principal: Principal, action: str, provider_id: str | None, scopes: list[str]) -> bool:
        """Allow the test principal to connect the registered provider."""
        del principal, action, provider_id, scopes
        return True


class _SlackNotifier:
    """Record Slack DMs without constructing a network client."""

    channel = "slack"

    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def notify(self, event: object, state_payload: dict[str, object]) -> None:
        """Record the event and the Slack destination metadata."""
        self.messages.append({"event": event, "state": state_payload})


async def test_e2e_slack_link_then_connect(redis_client) -> None:
    """Preview and explicit confirmation bind Slack before an authorized Jira callback."""
    owners: dict[str, str] = {}
    set_principal_resolver(_Resolver(owners))
    issuer = ChannelLinkIssuer(redis_client, base_url="https://app.example.com")
    link_issuer = SimpleNamespace(issue=issuer.issue)
    router = SlackCommandRouter()

    service_manager = FakeManager(
        "client",
        "https://app.example.com/oauth/callback",
        client_secret="secret",
        redis_client=redis_client,
        credential_store=FakeCredentialStore(),
    )
    service_manager.provider_id = "jira"
    notifier = _SlackNotifier()
    registry = ChannelNotifierRegistry()
    registry.register(notifier)
    publisher = ConnectionEventPublisher(notifiers=registry)
    service_manager._events = publisher
    OAuth2ProviderRegistry().register(JiraOAuth2Provider(manager=service_manager))
    service = IntegrationsService(authorizer=_AllowAuthorizer())
    register_connection_commands(router, link_issuer=link_issuer, service_factory=lambda: service)

    login = await router.dispatch("login", {"team_id": "T01", "user_id": "U02", "text": ""})
    link = login["blocks"][0]["accessory"]["url"]
    nonce = _nonce(link)

    preview_request = _Request(
        user_id="1042",
        issuer=issuer,
        authdb=object(),
        path=f"/api/v1/channel-links/{nonce}",
    )
    preview_request.match_info["nonce"] = nonce
    preview = await _unwrap(ChannelLinksHandler.get)(_handler(preview_request))
    assert preview.status == 200
    assert json.loads(preview.body) == {
        "channel": "slack",
        "channel_user_id": "T01:U02",
        "team_id": "T01",
        "nav_user_id": "1042",
    }
    assert await issuer.peek(nonce) is not None

    confirm_request = _Request(
        user_id="1042",
        issuer=issuer,
        authdb=object(),
        path=f"/api/v1/channel-links/{nonce}/confirm",
        body={"confirm": True},
    )
    confirm_request.match_info["nonce"] = nonce
    with patch("parrot.handlers.channel_links.IdentityMappingService", lambda _: _IdentityMapping(owners)):
        confirmed = await _unwrap(ChannelLinksHandler.post)(_handler(confirm_request))
    assert confirmed.status == 200
    assert owners == {"T01:U02": "1042"}
    assert await issuer.peek(nonce) is None

    connect = await router.dispatch(
        "connect",
        {"team_id": "T01", "user_id": "U02", "text": "jira"},
    )
    assert connect["blocks"][0]["accessory"]["url"].startswith("https://idp.example/authorize?")
    state = parse_qs(urlparse(connect["blocks"][0]["accessory"]["url"]).query)["state"][0]

    app = web.Application()
    app["oauth2_manager_jira"] = service_manager
    request = make_mocked_request("GET", f"/api/auth/jira/callback?code=code-1&state={state}", app=app)
    with patch.object(IntegrationsService, "persist_credential", new=AsyncMock()):
        response = await make_oauth2_callback("jira")(request)

    assert response.status == 200
    assert await service_manager.get_valid_token("slack", "1042") is not None
    assert service_manager._store.rows[("1042", "jira")]["account_id"] == "account-1"
    assert len(notifier.messages) == 1
    assert notifier.messages[0]["event"].kind == "connection.completed"
    assert notifier.messages[0]["state"]["extra"]["slack_user_id"] == "U02"


async def test_e2e_forwarded_slack_link(redis_client) -> None:
    """Another web user can preview a forwarded link but cannot claim or consume it."""
    owners: dict[str, str] = {}
    set_principal_resolver(_Resolver(owners))
    issuer = ChannelLinkIssuer(redis_client, base_url="https://app.example.com")
    link = await issuer.issue("slack", "T01:U02", {"team_id": "T01", "slack_user_id": "U02"})
    nonce = _nonce(link)
    request = _Request(
        user_id="2077",
        issuer=issuer,
        authdb=object(),
        path=f"/api/v1/channel-links/{nonce}",
    )
    request.match_info["nonce"] = nonce
    preview = await _unwrap(ChannelLinksHandler.get)(_handler(request))

    assert preview.status == 200
    payload = json.loads(preview.body)
    assert payload["channel_user_id"] == "T01:U02"
    assert payload["nav_user_id"] == "2077"
    assert await issuer.peek(nonce) is not None
    assert await _Resolver(owners).resolve("slack", "T01:U02") is None
