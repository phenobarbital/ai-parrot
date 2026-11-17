"""CliPrincipalResolver (FEAT-774 M2)."""

import time

import aiohttp
import pytest
from click.testing import CliRunner

from parrot.auth.oauth2.models import WhoAmI
from parrot.auth.principal import Principal
from parrot.cli.login import LoginRecord, LoginStore, _fill_from_me, whoami
from parrot.cli.principal import CliPrincipalResolver, build_cli_permission_context


class _StubClient:
    """Return a configured whoami response or error without making HTTP calls."""

    def __init__(self, response: WhoAmI | Exception) -> None:
        self.response = response

    async def me(self) -> WhoAmI:
        """Return the configured identity or raise the configured error."""
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _record() -> LoginRecord:
    """Build a valid login record for resolver tests."""
    return LoginRecord(
        server_url="https://parrot.example.test",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=time.time() + 3600,
        user_id="1042",
        email="login@example.test",
        cache_key="k" * 43,
        issued_at=time.time(),
    )


def _identity(*, tenant_id: str | None = "troc") -> WhoAmI:
    """Build the server-issued identity used by resolver tests."""
    return WhoAmI(
        user_id="1042",
        tenant_id=tenant_id,
        email="server@example.test",
        roles=["agents:use"],
        scopes=["connections:read"],
    )


@pytest.mark.asyncio
async def test_cli_principal_resolver_channels(tmp_path):
    """CLI channels resolve from /me while other channels and missing logins do not."""
    store = LoginStore(tmp_path / "login.json")
    store.save(_record())
    resolver = CliPrincipalResolver(store, _StubClient(_identity()))

    cli_principal = await resolver.resolve("cli", "1042")
    agentd_principal = await resolver.resolve("agentd", "local-user")

    assert cli_principal == Principal(
        user_id="1042",
        canonical_identity="server@example.test",
        tenant_id="troc",
        channel="cli",
        channel_user_id="1042",
    )
    assert agentd_principal is not None
    assert agentd_principal.channel == "agentd"
    assert agentd_principal.channel_user_id == "local-user"
    assert await resolver.resolve("telegram", "1042") is None

    missing_store = LoginStore(tmp_path / "missing.json")
    missing_resolver = CliPrincipalResolver(missing_store, _StubClient(_identity()))
    assert await missing_resolver.resolve("cli", "1042") is None


@pytest.mark.asyncio
async def test_cli_principal_roles_from_server(tmp_path):
    """Permission contexts retain server roles, scopes, and tenant discipline."""
    store = LoginStore(tmp_path / "login.json")
    store.save(_record())
    resolver = CliPrincipalResolver(store, _StubClient(_identity()))

    resolved = await resolver.resolve_with_roles("cli", "1042")

    assert resolved is not None
    principal, roles = resolved
    assert roles == frozenset({"agents:use", "connections:read"})
    context = build_cli_permission_context(principal, roles=roles)
    assert context.session.tenant_id == "troc"
    assert context.session.tenant_id != principal.user_id
    assert context.session.roles == roles

    fallback_principal = principal.model_copy(update={"tenant_id": None})
    fallback_context = build_cli_permission_context(fallback_principal, roles=roles)
    assert fallback_context.session.tenant_id == "default"
    assert fallback_context.session.tenant_id != fallback_principal.user_id


@pytest.mark.asyncio
async def test_resolver_returns_none_on_network_error(tmp_path):
    """Network failures preserve the existing caller fallback behavior."""
    store = LoginStore(tmp_path / "login.json")
    store.save(_record())
    resolver = CliPrincipalResolver(store, _StubClient(aiohttp.ClientConnectionError("offline")))

    assert await resolver.resolve("cli", "1042") is None


@pytest.mark.asyncio
async def test_fill_from_me_saves_server_roles_and_tenant(tmp_path, monkeypatch):
    """Post-login enrichment persists identity claims issued by the server."""
    store = LoginStore(tmp_path / "login.json")
    record = _record()
    store.save(record)

    class StubConnectionsClient:
        """Async context manager used by the lazy client import."""

        def __init__(self, client_store: LoginStore) -> None:
            assert client_store is store

        async def __aenter__(self) -> "StubConnectionsClient":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def me(self) -> WhoAmI:
            return _identity()

    monkeypatch.setattr("parrot.auth.oauth2.remote_client.ServerConnectionsClient", StubConnectionsClient)

    updated = await _fill_from_me(store, record)

    assert updated.roles == ["agents:use"]
    assert updated.tenant_id == "troc"
    assert store.load_optional() == updated


def test_whoami_prints_server_identity(tmp_path, monkeypatch):
    """The command displays all required server identity fields."""

    class StubConnectionsClient:
        """Async context manager used by the lazy whoami client import."""

        def __init__(self, _store: LoginStore) -> None:
            self.store = _store

        async def __aenter__(self) -> "StubConnectionsClient":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def me(self) -> WhoAmI:
            return _identity()

    monkeypatch.setattr("parrot.auth.oauth2.remote_client.ServerConnectionsClient", StubConnectionsClient)

    result = CliRunner().invoke(whoami, env={"PARROT_LOGIN_FILE": str(tmp_path / "login.json")})

    assert result.exit_code == 0, result.output
    assert "User ID: 1042" in result.output
    assert "Email: server@example.test" in result.output
    assert "Tenant: troc" in result.output
    assert "Roles: agents:use" in result.output


def test_whoami_not_logged_in_exit_1(tmp_path, monkeypatch):
    """The command gives a login hint and status 1 when no record exists."""
    monkeypatch.setenv("PARROT_LOGIN_FILE", str(tmp_path / "missing.json"))

    result = CliRunner().invoke(whoami)

    assert result.exit_code == 1
    assert "Not logged in" in result.output
    assert "parrot login" in result.output
