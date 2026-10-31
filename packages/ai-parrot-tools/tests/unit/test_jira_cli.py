"""Tests for Jira CLI compatibility commands (FEAT-774 M10)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from parrot.auth.jira_oauth import JiraTokenSet
from parrot_tools import jira_cli
from parrot_tools.jira_cli import cli, parse_pasted_redirect


class _Client:
    """Async test double for the remote connections client."""

    def __init__(self, store) -> None:
        self.store = store
        self.disconnected: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def list(self):
        return [
            {"provider": "github", "status": "connected"},
            {"provider": "jira", "status": "connected", "account_id": "account-1", "scopes_granted": ["read"]},
        ]

    async def disconnect(self, provider: str) -> None:
        self.disconnected.append(provider)


def _login_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jira_cli, "LoginStore", lambda: SimpleNamespace(load_optional=lambda: SimpleNamespace(user_id="user-1")))


def test_parse_pasted_redirect_is_core_reexport() -> None:
    """The legacy import is the exact core parser object."""
    from parrot.auth.oauth2.paste import parse_pasted_redirect as core_parser

    assert parse_pasted_redirect is core_parser


def test_auth_delegates_to_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deprecated auth command invokes the generic Jira connect flow."""
    _login_store(monkeypatch)
    calls: dict[str, object] = {}

    async def run_connect(client, cache, provider, **kwargs):
        calls.update(provider=provider, paste=kwargs["paste"], scopes=kwargs["scopes"])
        return {"provider": provider, "status": "connected", "account_id": "account-1"}

    monkeypatch.setattr("parrot.cli.connect.run_connect", run_connect)
    monkeypatch.setattr(jira_cli, "ServerConnectionsClient", _Client)
    monkeypatch.setattr(jira_cli, "open_connection_cache", lambda store: object())

    result = CliRunner().invoke(cli, ["auth", "--scopes", "read,write"])

    assert result.exit_code == 0, result.output
    assert calls == {"provider": "jira", "paste": True, "scopes": ["read", "write"]}
    assert "deprecated" in result.output


def test_status_filters_to_jira(monkeypatch: pytest.MonkeyPatch) -> None:
    """Status prints the Jira row and does not expose other connections."""
    _login_store(monkeypatch)
    monkeypatch.setattr(jira_cli, "ServerConnectionsClient", _Client)

    result = CliRunner().invoke(cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "jira" in result.output
    assert "github" not in result.output


def test_logout_disconnects_and_clears_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Logout delegates to the remote disconnect and deletes the Jira cache entry."""
    _login_store(monkeypatch)
    client = _Client(None)
    deleted: list[str] = []

    class Cache:
        async def delete(self, provider: str) -> None:
            deleted.append(provider)

    monkeypatch.setattr(jira_cli, "ServerConnectionsClient", lambda store: client)
    monkeypatch.setattr(jira_cli, "open_connection_cache", lambda store: Cache())

    result = CliRunner().invoke(cli, ["logout"])

    assert result.exit_code == 0, result.output
    assert client.disconnected == ["jira"]
    assert deleted == ["jira"]


def test_load_fresh_token_uses_remote_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """KB sync gets only an access token from the encrypted connection cache."""
    _login_store(monkeypatch)

    class Resolver:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def resolve(self, channel: str, user_id: str):
            assert (channel, user_id) == ("cli", "user-1")
            return "access-token"

    async def resources(session, access_token: str):
        assert access_token == "access-token"
        return [{"id": "cloud-1", "url": "https://acme.atlassian.net"}]

    monkeypatch.setattr(jira_cli, "ServerConnectionsClient", _Client)
    monkeypatch.setattr(jira_cli, "open_connection_cache", lambda store: object())
    monkeypatch.setattr(jira_cli, "RemoteConnectionResolver", Resolver)
    monkeypatch.setattr(jira_cli, "fetch_accessible_resources", resources)

    token = jira_cli._load_fresh_token()

    assert isinstance(token, JiraTokenSet)
    assert token.access_token == "access-token"
    assert token.refresh_token == ""
    assert token.cloud_id == "cloud-1"
