"""ServerConnectionsClient (FEAT-774 M4)."""

from __future__ import annotations

import time
from typing import Any

import pytest
from aiohttp import web

from parrot.auth.oauth2.remote_client import NotConnected, NotLoggedIn, ServerConnectionsClient
from parrot.cli.login import LoginExpired, LoginRecord, LoginStore


def _login_record(server_url: str, *, access_token: str = "old-access-token") -> LoginRecord:
    """Build a complete login record for client tests."""
    return LoginRecord(
        server_url=server_url,
        access_token=access_token,
        refresh_token="refresh-token",
        expires_at=time.time() + 3600,
        user_id="user-1",
        cache_key="cache-key",
        issued_at=time.time(),
    )


async def test_me_and_bearer_header(aiohttp_server: Any, tmp_path: Any) -> None:
    """The whoami call validates its model and sends the login bearer."""
    seen_headers: list[str | None] = []

    async def me(request: web.Request) -> web.Response:
        seen_headers.append(request.headers.get("Authorization"))
        return web.json_response({"user_id": "user-1", "roles": ["developer"]})

    app = web.Application()
    app.router.add_get("/api/v1/connections/me", me)
    server = await aiohttp_server(app)
    store = LoginStore(tmp_path / "login.json")
    store.save(_login_record(str(server.make_url(""))))

    async with ServerConnectionsClient(store) as client:
        identity = await client.me()

    assert identity.user_id == "user-1"
    assert identity.roles == ["developer"]
    assert seen_headers == ["Bearer old-access-token"]


async def test_401_refreshes_once_then_retries(aiohttp_server: Any, tmp_path: Any, monkeypatch: Any) -> None:
    """A 401 refreshes and saves once; rejection of the retry expires the login."""
    seen_tokens: list[str | None] = []
    reject_refreshed_token = False

    async def me(request: web.Request) -> web.Response:
        authorization = request.headers.get("Authorization")
        seen_tokens.append(authorization)
        if authorization == "Bearer old-access-token" or reject_refreshed_token:
            return web.Response(text="bearer rejected", status=401)
        return web.json_response({"user_id": "user-1"})

    app = web.Application()
    app.router.add_get("/api/v1/connections/me", me)
    server = await aiohttp_server(app)
    store = LoginStore(tmp_path / "login.json")
    store.save(_login_record(str(server.make_url(""))))
    refresh_calls: list[str] = []

    async def fake_refresh(record: LoginRecord, session: Any) -> LoginRecord:
        refresh_calls.append(record.access_token)
        return record.model_copy(update={"access_token": "new-access-token"})

    monkeypatch.setattr("parrot.auth.oauth2.remote_client.refresh_login", fake_refresh)
    async with ServerConnectionsClient(store) as client:
        identity = await client.me()
        assert identity.user_id == "user-1"

        store.save(_login_record(str(server.make_url(""))))
        reject_refreshed_token = True
        with pytest.raises(LoginExpired, match="refreshed login was rejected"):
            await client.me()

    assert seen_tokens == [
        "Bearer old-access-token",
        "Bearer new-access-token",
        "Bearer old-access-token",
        "Bearer new-access-token",
    ]
    assert refresh_calls == ["old-access-token", "old-access-token"]
    assert store.load_optional().access_token == "new-access-token"


async def test_pull_token_409_raises_not_connected(aiohttp_server: Any, tmp_path: Any) -> None:
    """A 409 response is exposed as NotConnected with its typed auth payload."""
    async def token(request: web.Request) -> web.Response:
        return web.json_response(
            {"provider": request.match_info["provider"], "auth_url": "https://auth.example/connect"}, status=409
        )

    app = web.Application()
    app.router.add_post("/api/v1/connections/{provider}/token", token)
    server = await aiohttp_server(app)
    store = LoginStore(tmp_path / "login.json")
    store.save(_login_record(str(server.make_url(""))))

    async with ServerConnectionsClient(store) as client:
        with pytest.raises(NotConnected) as raised:
            await client.pull_token("jira")

    assert raised.value.payload.provider == "jira"
    assert raised.value.payload.auth_url == "https://auth.example/connect"


async def test_no_login_raises_not_logged_in(tmp_path: Any) -> None:
    """Requests fail before opening a session when no login record exists."""
    client = ServerConnectionsClient(LoginStore(tmp_path / "missing.json"))

    with pytest.raises(NotLoggedIn, match="run `parrot login`"):
        await client.me()

    assert client._session is None


async def test_remaining_connection_methods(aiohttp_server: Any, tmp_path: Any, monkeypatch: Any) -> None:
    """The remaining public methods use their specified routes and request bodies."""
    requests: list[tuple[str, str, Any]] = []

    async def handler(request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else None
        requests.append((request.method, request.path, body))
        if request.path == "/api/v1/connections":
            return web.json_response([{"provider": "jira"}])
        if request.path.endswith("/device/start"):
            return web.json_response({"handle": "device-handle"})
        if request.path.endswith("/device/poll"):
            return web.json_response({"status": "pending"})
        if request.path.endswith("/start"):
            return web.json_response(
                {"auth_url": "https://auth.example/connect", "state": "opaque-state", "expires_in": 300}
            )
        if request.method == "DELETE":
            return web.json_response({"disconnected": True})
        return web.json_response({"provider": "jira", "status": "connected"})

    app = web.Application()
    app.router.add_route("*", "/api/v1/connections", handler)
    app.router.add_route("*", "/api/v1/connections/{provider}", handler)
    app.router.add_route("*", "/api/v1/connections/{provider}/{operation}", handler)
    app.router.add_route("*", "/api/v1/connections/{provider}/device/{operation}", handler)
    server = await aiohttp_server(app)
    store = LoginStore(tmp_path / "login.json")
    store.save(_login_record(str(server.make_url(""))))
    monkeypatch.setattr("parrot.auth.oauth2.remote_client.time.time", lambda: 123.5)

    async with ServerConnectionsClient(store) as client:
        assert await client.list() == [{"provider": "jira"}]
        assert (await client.status("jira"))["status"] == "connected"
        attempt = await client.start_connect("jira", scopes=["read"])
        assert attempt.started_at == 123.5
        assert attempt.expires_in == 300
        assert (await client.complete("jira", code="code", state="opaque-state"))["provider"] == "jira"
        await client.disconnect("jira")
        assert await client.device_start("jira") == {"handle": "device-handle"}
        assert await client.device_poll("jira", "device-handle") == {"status": "pending"}

    assert requests == [
        ("GET", "/api/v1/connections", None),
        ("GET", "/api/v1/connections/jira", None),
        ("POST", "/api/v1/connections/jira/start", {"channel": "cli", "scopes": ["read"]}),
        ("POST", "/api/v1/connections/jira/complete", {"code": "code", "state": "opaque-state"}),
        ("DELETE", "/api/v1/connections/jira", None),
        ("POST", "/api/v1/connections/jira/device/start", None),
        ("POST", "/api/v1/connections/jira/device/poll", {"handle": "device-handle"}),
    ]
