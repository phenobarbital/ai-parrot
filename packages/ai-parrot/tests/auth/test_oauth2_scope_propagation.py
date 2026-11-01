"""FEAT-775 AC-15: per-call scopes reach the provider consent URL."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import pytest

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.oauth2_base import AbstractOAuth2Manager, AbstractOAuth2TokenSet
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.principal import Principal


class InMemoryRedis:
    """Provide the nonce storage operations used by authorization URL creation."""

    def __init__(self) -> None:
        self.rows: Dict[str, str] = {}

    async def get(self, key: str) -> Optional[str]:
        """Return a stored state payload."""
        return self.rows.get(key)

    async def set(self, key: str, value: str, *, ex: Optional[int] = None) -> bool:
        """Store a state payload after yielding to concurrent callers."""
        del ex
        await asyncio.sleep(0)
        self.rows[key] = value
        return True


class ScopeManager(AbstractOAuth2Manager):
    """Minimal concrete manager used to exercise base URL construction."""

    provider_id = "scope-test"
    authorization_url = "https://idp.example/authorize"
    token_url = "https://idp.example/token"
    default_scopes = ["default"]

    def __init__(self, *args: Any, extra_params: Optional[Dict[str, str]] = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._extra_params = extra_params or {}

    async def _exchange_code(self, code: str, code_verifier: Optional[str]) -> Dict[str, Any]:
        """Provide an unused concrete hook for the abstract manager."""
        del code, code_verifier
        return {}

    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:
        """Provide an unused concrete hook for the abstract manager."""
        del refresh_token
        return {}

    async def _discover_identity(self, access_token: str) -> Dict[str, Any]:
        """Provide an unused concrete hook for the abstract manager."""
        del access_token
        return {}

    def _build_token_set(
        self,
        token_response: Dict[str, Any],
        identity: Dict[str, Any],
    ) -> AbstractOAuth2TokenSet:
        """Provide an unused concrete hook for the abstract manager."""
        del token_response, identity
        return AbstractOAuth2TokenSet(access_token="unused")

    def authorization_url_extra_params(self) -> Dict[str, str]:
        """Return scripted provider-specific URL parameters."""
        return dict(self._extra_params)


def _principal() -> Principal:
    """Build the principal passed to authorization URL creation."""
    return Principal(user_id="nav-user", channel="msteams", channel_user_id="teams-user")


def _permission_context() -> PermissionContext:
    """Build the trusted context matching the test principal."""
    return PermissionContext(
        session=UserSession(user_id="nav-user", tenant_id="tenant", roles=frozenset()),
        channel="msteams",
        channel_user_id="teams-user",
    )


def _manager(*, extra_params: Optional[Dict[str, str]] = None) -> tuple[ScopeManager, InMemoryRedis]:
    """Build a manager with deterministic in-memory nonce persistence."""
    redis = InMemoryRedis()
    return (
        ScopeManager(
            "client-id",
            "https://app.example/callback",
            client_secret="secret",
            redis_client=redis,
            scopes=["a"],
            extra_params=extra_params,
        ),
        redis,
    )


async def _state(redis: InMemoryRedis, manager: ScopeManager, nonce: str) -> Dict[str, Any]:
    """Load a stored nonce state payload."""
    payload = await redis.get(manager._nonce_key(nonce))
    assert payload is not None
    return json.loads(payload)


@pytest.mark.asyncio
async def test_default_scopes_unchanged() -> None:
    """Omitting scopes preserves manager scopes and records the request."""
    manager, redis = _manager()

    url, nonce = await manager.create_authorization_url("msteams", "teams-user", principal=_principal())

    assert parse_qs(urlparse(url).query)["scope"] == ["a"]
    assert (await _state(redis, manager, nonce))["requested_scopes"] == ["a"]


@pytest.mark.asyncio
async def test_per_call_scopes_override_and_win_over_extra_params() -> None:
    """Per-call scopes override provider scope extras and persist in state."""
    manager, redis = _manager(extra_params={"scope": "provider-scope", "prompt": "consent"})

    url, nonce = await manager.create_authorization_url(
        "msteams", "teams-user", principal=_principal(), scopes=["b", "c"]
    )

    query = parse_qs(urlparse(url).query)
    assert query["scope"] == ["b c"]
    assert query["prompt"] == ["consent"]
    assert (await _state(redis, manager, nonce))["requested_scopes"] == ["b", "c"]


@pytest.mark.asyncio
async def test_concurrent_requests_isolated() -> None:
    """Concurrent per-call scopes do not mutate or leak through manager state."""
    manager, _ = _manager()

    first_url, second_url = await asyncio.gather(
        manager.create_authorization_url("msteams", "teams-one", principal=_principal(), scopes=["one"]),
        manager.create_authorization_url("msteams", "teams-two", principal=_principal(), scopes=["two", "three"]),
    )

    assert parse_qs(urlparse(first_url[0]).query)["scope"] == ["one"]
    assert parse_qs(urlparse(second_url[0]).query)["scope"] == ["two three"]
    assert manager.scopes == ["a"]


@pytest.mark.asyncio
async def test_service_start_connect_passes_requested_scopes() -> None:
    """The service passes its resolved requested scopes to the OAuth manager."""
    OAuth2ProviderRegistry._reset()
    calls: List[Dict[str, Any]] = []

    async def create_authorization_url(**kwargs: Any) -> tuple[str, str]:
        """Record service arguments and return a deterministic response."""
        calls.append(kwargs)
        return "https://idp.example/authorize", "nonce"

    provider = SimpleNamespace(
        provider_id="scope-test",
        display_name="Scope Test",
        icon=None,
        default_scopes=["default"],
        manager=SimpleNamespace(create_authorization_url=create_authorization_url),
    )
    OAuth2ProviderRegistry().register(provider)

    class _AllowAuthorizer:
        """Allow the request without involving an HTTP PBAC dependency."""

        async def authorize(self, *_: Any) -> bool:
            return True

    requested_scopes = ["scope-a", "scope-b"]
    try:
        await IntegrationsService(authorizer=_AllowAuthorizer()).start_connect(
            "nav-user",
            "scope-test",
            channel="msteams",
            principal=_principal(),
            scopes=requested_scopes,
            permission_context=_permission_context(),
        )
    finally:
        OAuth2ProviderRegistry._reset()

    assert calls[0]["scopes"] == requested_scopes


@pytest.mark.asyncio
async def test_service_empty_scopes_fall_back_to_manager_scopes() -> None:
    """Without caller-supplied scopes the manager keeps its own defaults instead of receiving ``scope=""``."""
    OAuth2ProviderRegistry._reset()
    calls: List[Dict[str, Any]] = []

    async def create_authorization_url(**kwargs: Any) -> tuple[str, str]:
        """Record service arguments and return a deterministic response."""
        calls.append(kwargs)
        return "https://idp.example/authorize", "nonce"

    provider = SimpleNamespace(
        provider_id="empty-scope-test",
        display_name="Empty Scope Test",
        icon=None,
        default_scopes=[],
        manager=SimpleNamespace(create_authorization_url=create_authorization_url),
    )
    OAuth2ProviderRegistry().register(provider)

    class _AllowAuthorizer:
        """Allow the request without involving an HTTP PBAC dependency."""

        async def authorize(self, *_: Any) -> bool:
            return True

    try:
        await IntegrationsService(authorizer=_AllowAuthorizer()).start_connect(
            "nav-user",
            "empty-scope-test",
            channel="msteams",
            principal=_principal(),
            permission_context=_permission_context(),
        )
    finally:
        OAuth2ProviderRegistry._reset()

    assert "scopes" not in calls[0]
