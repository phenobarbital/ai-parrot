"""parrot connect (FEAT-774 M6, AC-9)."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.auth.oauth2.remote_client import ConnectAttempt
from parrot.cli import connect as connect_module
from parrot.cli.commands import SlashCommandDispatcher
from parrot.cli.connect import ConnectFailed, run_connect


class _Cache:
    """Capture cache writes made by ``run_connect``."""

    def __init__(self) -> None:
        self.entries = []

    async def put(self, entry) -> None:
        """Record one cached connection."""
        self.entries.append(entry)


def _pulled(provider: str = "jira") -> SimpleNamespace:
    """Return a pulled-token-shaped object."""
    return SimpleNamespace(
        provider=provider,
        access_token="secret-access-token",
        expires_at=999.0,
        scopes=["read"],
        account_id="acct-1",
    )


@pytest.mark.asyncio
async def test_connect_poll_completes_only_new_connection():
    """A pre-existing connection does not satisfy a new connect attempt."""
    client = SimpleNamespace(
        start_connect=AsyncMock(
            return_value=ConnectAttempt(
                provider="jira", state="state-1", auth_url="https://auth.example", started_at=100.0, expires_in=10
            )
        ),
        status=AsyncMock(
            side_effect=[
                {
                    "status": "connected",
                    "connected_at": "1970-01-01T00:01:00+00:00",
                    "updated_at": "1970-01-01T00:01:00+00:00",
                },
                {
                    "status": "connected",
                    "connected_at": "1970-01-01T00:01:00+00:00",
                    "updated_at": "1970-01-01T00:01:40+00:00",
                },
            ]
        ),
        complete=AsyncMock(),
        pull_token=AsyncMock(return_value=_pulled()),
    )
    cache = _Cache()

    result = await run_connect(
        client,
        cache,
        "jira",
        scopes=None,
        open_browser=False,
        paste=False,
        device=False,
        prompt=lambda _: pytest.fail("poll completion must not prompt"),
        echo=lambda _: None,
        poll_interval_s=0,
    )

    assert client.status.await_count == 2
    client.complete.assert_not_awaited()
    assert result == {"provider": "jira", "account_id": "acct-1", "status": "connected"}
    assert cache.entries[0].access_token == "secret-access-token"


@pytest.mark.asyncio
async def test_connect_paste_fallback_state_check():
    """Pasted redirects require the exact attempt state before completion."""
    attempt = ConnectAttempt(
        provider="jira", state="expected-state", auth_url="https://auth.example", started_at=100.0, expires_in=10
    )
    client = SimpleNamespace(
        start_connect=AsyncMock(return_value=attempt),
        complete=AsyncMock(),
        pull_token=AsyncMock(return_value=_pulled()),
    )

    with pytest.raises(ConnectFailed, match="state mismatch"):
        await run_connect(
            client,
            _Cache(),
            "jira",
            scopes=None,
            open_browser=False,
            paste=True,
            device=False,
            prompt=lambda _: "https://callback.example?code=private-code&state=wrong-state",
            echo=lambda _: None,
        )
    client.complete.assert_not_awaited()
    client.pull_token.assert_not_awaited()

    cache = _Cache()
    await run_connect(
        client,
        cache,
        "jira",
        scopes=None,
        open_browser=False,
        paste=True,
        device=False,
        prompt=lambda _: "https://callback.example?code=private-code&state=expected-state",
        echo=lambda _: None,
    )
    client.complete.assert_awaited_once_with("jira", code="private-code", state="expected-state")
    assert len(cache.entries) == 1


@pytest.mark.asyncio
async def test_connect_device_flow():
    """Device connect uses only the server device endpoints before token pull."""
    client = SimpleNamespace(
        device_start=AsyncMock(
            return_value={
                "handle": "handle-1",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://device.example",
                "expires_in": 30,
                "interval": 0,
            }
        ),
        device_poll=AsyncMock(side_effect=[{"status": "pending", "interval": 0}, {"status": "completed"}]),
        pull_token=AsyncMock(return_value=_pulled("o365")),
    )
    cache = _Cache()
    output = []

    result = await run_connect(
        client,
        cache,
        "o365",
        scopes=None,
        open_browser=False,
        paste=False,
        device=True,
        prompt=lambda _: pytest.fail("device flow must not request a pasted redirect"),
        echo=output.append,
    )

    assert client.device_poll.await_count == 2
    client.device_poll.assert_awaited_with("o365", "handle-1")
    assert "ABCD-EFGH" in output[0]
    assert result["status"] == "connected"
    assert cache.entries[0].provider == "o365"


class _SlashContext:
    """Minimal command context that tracks terminal suspension."""

    def __init__(self) -> None:
        self.dispatcher = SlashCommandDispatcher()
        self.renderer = SimpleNamespace(
            print=lambda *args, **kwargs: None, render_error=lambda exc: pytest.fail(str(exc))
        )
        self.suspended = False
        self.suspend_entries = 0

    @contextlib.contextmanager
    def suspend(self):
        """Record the lifetime of a terminal suspension."""
        self.suspended = True
        self.suspend_entries += 1
        try:
            yield
        finally:
            self.suspended = False


@pytest.mark.asyncio
async def test_slash_connect_uses_suspend(monkeypatch):
    """The slash command owns the terminal while the paste prompt runs."""
    ctx = _SlashContext()

    class _Store:
        def load_optional(self):
            return object()

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

    async def fake_run_connect(client, cache, provider, **kwargs):
        assert ctx.suspended is True
        assert provider == "jira"
        kwargs["prompt"]("Paste the redirected URL")
        return {"provider": provider, "account_id": "acct-1", "status": "connected"}

    def fake_prompt(_text, **_kwargs):
        assert ctx.suspended is True
        return "https://callback.example?code=private-code&state=private-state"

    monkeypatch.setattr("parrot.cli.login.LoginStore", _Store)
    monkeypatch.setattr("parrot.auth.oauth2.remote_client.ServerConnectionsClient", lambda store: _Client())
    monkeypatch.setattr("parrot.auth.oauth2.local_cache.open_connection_cache", lambda store: object())
    monkeypatch.setattr(connect_module, "run_connect", fake_run_connect)
    monkeypatch.setattr("click.prompt", fake_prompt)

    assert await ctx.dispatcher.dispatch_async("/connect jira --paste", ctx) is True
    assert ctx.suspend_entries == 1
