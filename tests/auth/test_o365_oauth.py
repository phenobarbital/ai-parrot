"""Unit tests for :mod:`parrot.auth.o365_oauth`.

Exercise the Microsoft-specific manager by mocking ``aiohttp.ClientSession``
so PKCE exchange, refresh, and identity discovery can be validated
without hitting login.microsoftonline.com.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.o365_oauth import O365OAuthManager, O365TokenSet


pytest.importorskip("fakeredis")
import fakeredis.aioredis  # noqa: E402


@pytest.fixture
async def manager_with_fake_http():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    vault_store: dict = {}

    async def _write(uid, name, payload):
        vault_store[(uid, name)] = payload

    async def _read(uid, name):
        try:
            return vault_store[(uid, name)]
        except KeyError:
            raise KeyError(name)

    async def _delete(uid, name):
        vault_store.pop((uid, name), None)

    mgr = O365OAuthManager(
        client_id="o365cid",
        client_secret="o365csec",
        redirect_uri="https://app.example.com/cb",
        tenant_id="tenant-guid",
        redis_client=redis_client,
        vault_writer=_write,
        vault_reader=_read,
        vault_deleter=_delete,
    )
    yield mgr, vault_store
    close = getattr(redis_client, "aclose", None) or redis_client.close
    res = close()
    if hasattr(res, "__await__"):
        await res
    await mgr.aclose()


def _fake_response(status: int, json_body: Any = None, text_body: str = ""):
    resp = MagicMock()
    resp.status = status
    resp.headers = {"Content-Type": "application/json"} if json_body is not None else {}
    if json_body is not None:
        resp.json = AsyncMock(return_value=json_body)
    resp.text = AsyncMock(return_value=text_body)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _fake_session(post=None, get=None):
    sess = MagicMock()
    sess.closed = False
    if post is not None:
        sess.post = MagicMock(side_effect=post)
    if get is not None:
        sess.get = MagicMock(side_effect=get)
    sess.close = AsyncMock()
    return sess


@pytest.mark.asyncio
async def test_endpoints_use_tenant_id(manager_with_fake_http):
    mgr, _ = manager_with_fake_http
    assert "tenant-guid" in mgr.authorization_url
    assert "tenant-guid" in mgr.token_url
    assert mgr.authorization_url.endswith("/oauth2/v2.0/authorize")


@pytest.mark.asyncio
async def test_authorization_url_extra_params(manager_with_fake_http):
    mgr, _ = manager_with_fake_http
    url, _ = await mgr.create_authorization_url("web", "user-1")
    assert "prompt=select_account" in url
    assert "response_mode=query" in url
    assert "code_challenge=" in url


@pytest.mark.asyncio
async def test_handle_callback_sends_code_verifier(manager_with_fake_http):
    mgr, _ = manager_with_fake_http
    _, nonce = await mgr.create_authorization_url("web", "user-1")

    token_response = {
        "access_token": "AT-1",
        "refresh_token": "RT-1",
        "expires_in": 3600,
        "scope": " ".join(mgr.scopes),
        "id_token": "ID-1",
    }
    identity = {
        "id": "00000000-0000-0000-0000-000000000001",
        "displayName": "Alice Doe",
        "mail": "alice@contoso.com",
        "userPrincipalName": "alice@contoso.com",
    }

    captured_post_data = {}

    def _post(url, data=None, headers=None, **kwargs):
        captured_post_data["data"] = data
        return _fake_response(200, json_body=token_response)

    def _get(url, headers=None, **kwargs):
        assert url == mgr.GRAPH_ME_URL
        assert headers["Authorization"] == "Bearer AT-1"
        return _fake_response(200, json_body=identity)

    mgr._http = _fake_session(post=_post, get=_get)
    mgr._http_owned = False

    token, _ = await mgr.handle_callback("CODE-A", nonce)

    assert isinstance(token, O365TokenSet)
    assert token.access_token == "AT-1"
    assert token.refresh_token == "RT-1"
    assert token.account_id == "00000000-0000-0000-0000-000000000001"
    assert token.email == "alice@contoso.com"
    assert token.user_principal_name == "alice@contoso.com"
    assert token.tenant_id == "tenant-guid"
    assert token.id_token == "ID-1"

    # PKCE: verifier was sent in the form-urlencoded body.
    assert "code_verifier=" in captured_post_data["data"]
    assert "grant_type=authorization_code" in captured_post_data["data"]
    assert "client_secret=o365csec" in captured_post_data["data"]


@pytest.mark.asyncio
async def test_refresh_400_raises_permission_error(manager_with_fake_http):
    mgr, _ = manager_with_fake_http
    response = _fake_response(400, text_body="invalid_grant")
    mgr._http = _fake_session(post=lambda *a, **k: response)
    mgr._http_owned = False

    with pytest.raises(PermissionError):
        await mgr._refresh_request("dead-refresh-token")
