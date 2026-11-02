"""Tests for descriptor-backed OAuth2 managers and providers."""

from __future__ import annotations

import json
import time
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from parrot.auth.oauth2 import descriptor as descriptor_module
from parrot.auth.oauth2.descriptor import (
    OAuth2ProviderDescriptor,
    StandardOAuth2Manager,
    register_descriptor_providers,
)
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.oauth2_base import InvalidGrantError, RefreshTransientError
from parrot.auth.principal import Principal

from ._oauth2_fakes import FakeCredentialStore, MemRedis


class PingRedis(MemRedis):
    """MemRedis variant satisfying the manager startup health check."""

    async def ping(self) -> bool:
        """Report that the in-memory backend is available."""
        return True


def _descriptor(base_url: str, **overrides: Any) -> OAuth2ProviderDescriptor:
    """Build a complete dummy provider descriptor."""
    values: Dict[str, Any] = {
        "provider_id": "dummy",
        "display_name": "Dummy",
        "icon": "dummy",
        "authorization_url": f"{base_url}/authorize",
        "token_url": f"{base_url}/token",
        "revoke_url": f"{base_url}/revoke",
        "default_scopes": ["read", "profile"],
        "client_type": "confidential",
        "pkce": "required",
        "identity_probe": {
            "url": f"{base_url}/me",
            "account_id_path": "accounts.0.id",
            "display_name_path": "accounts.0.profile.name",
            "email_path": "accounts.0.profile.email",
        },
        "extra_authorize_params": {"audience": "dummy-api"},
    }
    values.update(overrides)
    return OAuth2ProviderDescriptor.model_validate(values)


def _idp_application(records: Dict[str, Any]) -> web.Application:
    """Create a local IdP with token, identity and revoke endpoints."""

    async def token(request: web.Request) -> web.Response:
        form = dict(await request.post())
        records.setdefault("token_forms", []).append(form)
        if form.get("grant_type") == "authorization_code":
            return web.json_response(
                {
                    "access_token": "access-one",
                    "refresh_token": "refresh-one",
                    "expires_in": 3600,
                    "scope": "read profile",
                }
            )
        refresh_token = form.get("refresh_token")
        if refresh_token == "invalid":
            return web.json_response({"error": "invalid_grant", "error_description": "sensitive"}, status=400)
        if refresh_token == "rate-limited":
            return web.json_response({"error": "slow_down"}, status=429)
        if refresh_token == "server-error":
            return web.json_response({"error": "unavailable"}, status=503)
        if refresh_token == "invalid-client":
            return web.json_response({"error": "invalid_client"}, status=400)
        if refresh_token == "malformed":
            return web.Response(text="not-json", content_type="application/json")
        return web.json_response(
            {
                "access_token": "access-two",
                "refresh_token": "refresh-two",
                "expires_in": 7200,
                "scope": "read profile",
            }
        )

    async def identity(request: web.Request) -> web.Response:
        records["authorization"] = request.headers.get("Authorization")
        return web.json_response(
            {
                "accounts": [
                    {
                        "id": "account-123",
                        "profile": {"name": "Dummy User", "email": "dummy@example.test"},
                    }
                ]
            }
        )

    async def revoke(request: web.Request) -> web.Response:
        records["revoke_form"] = dict(await request.post())
        return web.Response(status=204)

    app = web.Application()
    app.router.add_post("/token", token)
    app.router.add_get("/me", identity)
    app.router.add_post("/revoke", revoke)
    return app


@pytest.mark.asyncio
async def test_standard_manager_exchange_refresh_probe() -> None:
    """Exchange, probe, refresh and revoke use descriptor-driven HTTP behaviour."""
    records: Dict[str, Any] = {}
    async with TestServer(_idp_application(records)) as server, aiohttp.ClientSession() as session:
        descriptor = _descriptor(str(server.make_url("/")).rstrip("/"))
        redis = MemRedis()
        store = FakeCredentialStore()
        manager = StandardOAuth2Manager(
            descriptor,
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://client.test/callback",
            redis_client=redis,
            credential_store=store,
            http_session=session,
        )
        principal = Principal(user_id="42", channel="web", channel_user_id="42")

        authorization_url, state = await manager.create_authorization_url("web", "42", principal=principal)
        authorization_query = parse_qs(urlparse(authorization_url).query)
        assert authorization_query["code_challenge_method"] == ["S256"]
        assert authorization_query["audience"] == ["dummy-api"]

        token_set, _ = await manager.handle_callback("authorization-code", state)
        assert token_set.account_id == "account-123"
        assert token_set.display_name == "Dummy User"
        assert token_set.email == "dummy@example.test"
        assert records["authorization"] == "Bearer access-one"
        exchange_form = records["token_forms"][0]
        assert exchange_form["client_secret"] == "client-secret"
        assert exchange_form["code_verifier"]

        expired = token_set.model_copy(update={"expires_at": time.time() - 1})
        store.rows[("42", "dummy")] = expired.model_dump(mode="json")
        await redis.set(manager._token_key("42"), expired.model_dump_json())
        refreshed = await manager.get_valid_token("web", "42")
        assert refreshed is not None
        assert refreshed.access_token == "access-two"
        assert refreshed.refresh_token == "refresh-two"

        await manager._revoke_remote(refreshed)
        assert records["revoke_form"] == {
            "token": "refresh-two",
            "token_type_hint": "refresh_token",
            "client_id": "client-id",
            "client_secret": "client-secret",
        }

        public_manager = StandardOAuth2Manager(
            descriptor.model_copy(update={"client_type": "public", "pkce": "none"}),
            client_id="public-client",
            client_secret=None,
            redirect_uri="https://client.test/public-callback",
            redis_client=MemRedis(),
            http_session=session,
        )
        public_url, _ = await public_manager.create_authorization_url("web", "42", principal=principal)
        assert "code_challenge" not in parse_qs(urlparse(public_url).query)


@pytest.mark.asyncio
async def test_standard_manager_refresh_error_classification() -> None:
    """Refresh errors are typed without exposing provider response bodies."""
    records: Dict[str, Any] = {}
    async with TestServer(_idp_application(records)) as server, aiohttp.ClientSession() as session:
        manager = StandardOAuth2Manager(
            _descriptor(str(server.make_url("/")).rstrip("/")),
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://client.test/callback",
            redis_client=MemRedis(),
            http_session=session,
        )

        with pytest.raises(InvalidGrantError, match="grant is invalid") as invalid_grant:
            await manager._refresh_request("invalid")
        assert "sensitive" not in str(invalid_grant.value)
        for refresh_token in ("rate-limited", "server-error"):
            with pytest.raises(RefreshTransientError):
                await manager._refresh_request(refresh_token)
        with pytest.raises(RuntimeError, match="status 400"):
            await manager._refresh_request("invalid-client")
        with pytest.raises(RuntimeError, match="invalid JSON"):
            await manager._refresh_request("malformed")


@pytest.mark.asyncio
async def test_dummy_provider_end_to_end_via_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """A descriptor and navconfig secrets are sufficient for registry use."""
    records: Dict[str, Any] = {}
    OAuth2ProviderRegistry._reset()
    async with TestServer(_idp_application(records)) as idp_server:
        base_url = str(idp_server.make_url("/")).rstrip("/")
        descriptor = _descriptor(base_url)
        values = {
            "OAUTH2_DUMMY_CLIENT_ID": "configured-id",
            "OAUTH2_DUMMY_CLIENT_SECRET": "configured-secret",
            "OAUTH2_DUMMY_REDIRECT_URI": "https://client.test/callback",
        }
        monkeypatch.setattr(descriptor_module.config, "get", lambda name: values.get(name))
        redis = PingRedis()
        oauth_app = web.Application()
        oauth_app["redis"] = redis
        providers = register_descriptor_providers(
            [descriptor],
            app=oauth_app,
            credential_store=FakeCredentialStore(),
            event_publisher=None,
        )

        async with TestServer(oauth_app):
            provider = OAuth2ProviderRegistry().get("dummy")
            assert provider is providers[0]
            assert provider is not None
            assert provider.toolkit_factory(object()) is None
            principal = Principal(user_id="84", channel="web", channel_user_id="84")
            _, state = await provider.manager.create_authorization_url("web", "84", principal=principal)
            token_set, _ = await provider.manager.handle_callback("registry-code", state)
            loaded = await provider.manager.get_valid_token("web", "84")
            assert loaded == token_set
            assert provider.manager.client_id == "configured-id"
            assert provider.manager.client_secret == "configured-secret"
    OAuth2ProviderRegistry._reset()


def test_unconfigured_descriptor_is_skipped(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Missing navconfig credentials skip a descriptor with a warning."""
    descriptor = _descriptor("https://idp.example")
    monkeypatch.setattr(descriptor_module.config, "get", lambda name: None)
    OAuth2ProviderRegistry._reset()

    providers = register_descriptor_providers(
        [descriptor],
        app=web.Application(),
        credential_store=FakeCredentialStore(),
        event_publisher=None,
    )

    assert providers == []
    assert OAuth2ProviderRegistry().get("dummy") is None
    assert "client id is not configured" in caplog.text
    OAuth2ProviderRegistry._reset()


def test_public_descriptor_does_not_require_client_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Public clients register from navconfig without a client secret."""
    descriptor = _descriptor("https://idp.example", client_type="public")
    values = {
        "OAUTH2_DUMMY_CLIENT_ID": "public-id",
        "OAUTH2_DUMMY_REDIRECT_URI": "https://client.test/callback",
    }
    monkeypatch.setattr(descriptor_module.config, "get", lambda name: values.get(name))
    app = web.Application()
    OAuth2ProviderRegistry._reset()

    providers = register_descriptor_providers(
        [descriptor],
        app=app,
        credential_store=FakeCredentialStore(),
        event_publisher=None,
    )

    assert len(providers) == 1
    assert providers[0].manager.client_secret == ""
    OAuth2ProviderRegistry._reset()
