"""E2E: parrot login -> parrot connect -> credentialed tool (FEAT-774 section 4)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web

from parrot.auth.oauth2.local_cache import build_cli_broker, open_connection_cache
from parrot.auth.oauth2.remote_client import ServerConnectionsClient
from parrot.cli.connect import run_connect
from parrot.cli.login import LoginRecord, LoginStore
from parrot.tools.abstract import AbstractTool, ToolResult, current_credential


class FakeCredentialTool(AbstractTool):
    """Return the credential injected by the CLI broker."""

    name = "fake_credential"
    description = "Return the fake provider credential."
    credential_provider = "fake"

    async def _execute(self, **kwargs: Any) -> ToolResult:
        """Return the credential visible during this tool invocation."""
        return ToolResult(status="success", result=current_credential())


@pytest.fixture
async def fake_parrot_server(aiohttp_server: Any) -> SimpleNamespace:
    """Serve the CLI connections API and retain request counters."""
    state: dict[str, Any] = {"status_calls": 0, "token_calls": 0, "completed": False}

    async def me(_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "user_id": "navigator-user",
                "email": "user@example.test",
                "tenant_id": "tenant-test",
                "roles": [],
                "scopes": [],
            }
        )

    async def start(request: web.Request) -> web.Response:
        assert await request.json() == {"channel": "cli", "scopes": None}
        state["started_at"] = datetime.now(timezone.utc).isoformat()
        return web.json_response(
            {
                "state": "opaque-state",
                "auth_url": "https://provider.example/authorize",
                "expires_in": 60,
            }
        )

    async def status(request: web.Request) -> web.Response:
        state["status_calls"] += 1
        connected = state["status_calls"] > 1
        return web.json_response(
            {
                "provider": request.match_info["provider"],
                "status": "connected" if connected else "disconnected",
                "connected_at": state.get("started_at") if connected else None,
            }
        )

    async def token(request: web.Request) -> web.Response:
        state["token_calls"] += 1
        return web.json_response(
            {
                "provider": request.match_info["provider"],
                "access_token": "fake-access-token",
                "expires_at": time.time() + 3600,
                "scopes": ["fake.read"],
                "account_id": "fake-account",
            }
        )

    async def complete(_request: web.Request) -> web.Response:
        state["completed"] = True
        return web.json_response({"status": "connected"})

    app = web.Application()
    app.router.add_get("/api/v1/connections/me", me)
    app.router.add_get("/api/v1/connections/{provider}", status)
    app.router.add_post("/api/v1/connections/{provider}/start", start)
    app.router.add_post("/api/v1/connections/{provider}/token", token)
    app.router.add_post("/api/v1/connections/{provider}/complete", complete)
    server = await aiohttp_server(app)
    return SimpleNamespace(server=server, state=state)


async def test_e2e_cli_login_connect_tool_call(
    fake_parrot_server: SimpleNamespace,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connected token is cached and reused for two tool executions."""
    login_path = tmp_path / ".parrot" / "login.json"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PARROT_LOGIN_FILE", str(login_path))
    monkeypatch.setattr("parrot.cli.connect.webbrowser.open", lambda _url: True)

    async def no_sleep(_delay: float) -> None:
        """Advance the deterministic fake poll loop without waiting."""

    monkeypatch.setattr("parrot.cli.connect.asyncio.sleep", no_sleep)

    store = LoginStore(login_path)
    store.save(
        LoginRecord(
            server_url=str(fake_parrot_server.server.make_url("")),
            access_token="navigator-access-token",
            refresh_token="navigator-refresh-token",
            expires_at=time.time() + 3600,
            user_id="navigator-user",
            cache_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY",
            issued_at=time.time(),
        )
    )
    assert login_path.stat().st_mode & 0o777 == 0o600

    client = ServerConnectionsClient(store)
    try:
        connected = await run_connect(
            client,
            open_connection_cache(store),
            "fake",
            scopes=None,
            open_browser=False,
            paste=False,
            device=False,
            prompt=lambda message: pytest.fail(f"unexpected prompt: {message}"),
            echo=lambda _message: None,
            poll_interval_s=0,
        )
        assert connected == {"provider": "fake", "account_id": "fake-account", "status": "connected"}

        broker = build_cli_broker(store, ["fake"], client=client)
        tool = FakeCredentialTool()
        first = await tool.execute(_broker=broker, _cred_channel="cli", _cred_user_id="navigator-user")
        second = await tool.execute(_broker=broker, _cred_channel="cli", _cred_user_id="navigator-user")
    finally:
        await client.close()

    assert first.result == "fake-access-token"
    assert second.result == "fake-access-token"
    assert fake_parrot_server.state["status_calls"] == 2
    assert fake_parrot_server.state["token_calls"] == 1
    assert fake_parrot_server.state["completed"] is False
