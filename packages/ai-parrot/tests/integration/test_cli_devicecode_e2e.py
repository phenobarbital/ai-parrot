"""E2E coverage for ``parrot connect o365 --device`` (FEAT-774 section 4)."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web

from parrot.auth.oauth2.local_cache import open_connection_cache
from parrot.auth.oauth2.remote_client import ServerConnectionsClient
from parrot.cli.connect import run_connect
from parrot.cli.login import LoginRecord, LoginStore


@pytest.fixture
async def fake_o365_server(aiohttp_server: Any) -> SimpleNamespace:
    """Serve a pending-then-completed O365 device authorization flow."""
    state: dict[str, Any] = {
        "poll_calls": 0,
        "token_calls": 0,
        "provider_device_code": "provider-secret-device-code",
    }

    async def device_start(request: web.Request) -> web.Response:
        assert request.match_info["provider"] == "o365"
        return web.json_response(
            {
                "handle": "opaque-device-handle",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://microsoft.example/device",
                "verification_uri_complete": "https://microsoft.example/device?code=ABCD-EFGH",
                "expires_in": 600,
                "interval": 0,
            }
        )

    async def device_poll(request: web.Request) -> web.Response:
        assert await request.json() == {"handle": "opaque-device-handle"}
        state["poll_calls"] += 1
        if state["poll_calls"] == 1:
            return web.json_response({"status": "pending", "interval": 0})
        return web.json_response({"status": "completed"})

    async def token(_request: web.Request) -> web.Response:
        state["token_calls"] += 1
        return web.json_response(
            {
                "provider": "o365",
                "access_token": "o365-access-token",
                "expires_at": time.time() + 3600,
                "scopes": ["User.Read"],
                "account_id": "user@example.test",
            }
        )

    app = web.Application()
    app.router.add_post("/api/v1/connections/{provider}/device/start", device_start)
    app.router.add_post("/api/v1/connections/{provider}/device/poll", device_poll)
    app.router.add_post("/api/v1/connections/{provider}/token", token)
    server = await aiohttp_server(app)
    return SimpleNamespace(server=server, state=state)


async def test_e2e_cli_devicecode_e2e(
    fake_o365_server: SimpleNamespace,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server mediates O365 device auth and stores only the pulled access token locally."""
    login_path = tmp_path / ".parrot" / "login.json"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PARROT_LOGIN_FILE", str(login_path))
    opened_urls: list[str] = []
    output: list[str] = []
    monkeypatch.setattr("parrot.cli.connect.webbrowser.open", lambda url: opened_urls.append(url) or True)

    async def no_sleep(_delay: float) -> None:
        """Advance the deterministic fake poll loop without waiting."""

    monkeypatch.setattr("parrot.cli.connect.asyncio.sleep", no_sleep)

    store = LoginStore(login_path)
    store.save(
        LoginRecord(
            server_url=str(fake_o365_server.server.make_url("")),
            access_token="navigator-access-token",
            refresh_token="navigator-refresh-token",
            expires_at=time.time() + 3600,
            user_id="navigator-user",
            cache_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY",
            issued_at=time.time(),
        )
    )

    client = ServerConnectionsClient(store)
    try:
        result = await run_connect(
            client,
            open_connection_cache(store),
            "o365",
            scopes=None,
            open_browser=True,
            paste=False,
            device=True,
            prompt=lambda message: pytest.fail(f"unexpected prompt: {message}"),
            echo=output.append,
        )
    finally:
        await client.close()

    cached = await open_connection_cache(store).get("o365")
    rendered_output = "\n".join(output)
    assert result == {"provider": "o365", "account_id": "user@example.test", "status": "connected"}
    assert fake_o365_server.state["poll_calls"] == 2
    assert fake_o365_server.state["token_calls"] == 1
    assert cached is not None
    assert cached.access_token == "o365-access-token"
    assert opened_urls == ["https://microsoft.example/device?code=ABCD-EFGH"]
    assert "ABCD-EFGH" in rendered_output
    assert fake_o365_server.state["provider_device_code"] not in rendered_output
