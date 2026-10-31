"""Login binding for ``parrot mcp-local`` (FEAT-774 M5)."""

from pathlib import Path

import pytest

from parrot.auth.principal import Principal
from parrot.cli.login import LoginRecord, LoginStore
from parrot.mcp.server_base import LocalServerConfig
from parrot.mcp.toolkit_config import ToolkitSection
from parrot.mcp.toolkit_server import _ToolkitStdioMCPServer
from parrot.tools.toolkit import AbstractToolkit


class CredentialToolkit(AbstractToolkit):
    """Minimal toolkit whose generated tool requires a credential provider."""

    credential_provider = "fake"

    async def fetch(self) -> str:
        """Return a fixed test value."""
        return "ok"


def _write_login(path: Path) -> None:
    """Write a valid private login record without exposing a real token."""
    LoginStore(path).save(
        LoginRecord(
            server_url="https://example.test",
            access_token="test-access-token",
            refresh_token="test-refresh-token",
            expires_at=4_102_444_800,
            user_id="login-user",
            cache_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY",
            issued_at=1_700_000_000,
        )
    )


@pytest.mark.asyncio
async def test_toolkit_server_without_login_unchanged(tmp_path, monkeypatch):
    """A missing or invalid login leaves the server and adapters without a context."""
    login_file = tmp_path / "missing-login.json"
    monkeypatch.setenv("PARROT_LOGIN_FILE", str(login_file))
    toolkit = CredentialToolkit()
    server = _ToolkitStdioMCPServer(LocalServerConfig(name="test"), toolkit, login_file=login_file)
    server.register_tools(toolkit.get_tools())

    await server._bind_identity()

    assert server.execution_context is None
    assert all(adapter.execution_context is None for adapter in server.tools.values())

    login_file.write_text("not-json", encoding="utf-8")
    login_file.chmod(0o600)
    await server._bind_identity()

    assert server.execution_context is None
    assert all(adapter.execution_context is None for adapter in server.tools.values())


@pytest.mark.asyncio
async def test_toolkit_server_binds_principal_from_login_file(tmp_path, monkeypatch):
    """A selected login binds its principal and provider broker to every adapter."""
    login_file = tmp_path / "selected-login.json"
    _write_login(login_file)
    toolkit = CredentialToolkit()
    server = _ToolkitStdioMCPServer(LocalServerConfig(name="test"), toolkit, login_file=login_file)
    server.register_tools(toolkit.get_tools())
    expected_broker = object()
    expected_permission_context = object()
    calls = {}

    async def resolve_with_roles(self, channel, channel_user_id):
        calls["store_path"] = self.store.path
        calls["channel"] = channel
        calls["channel_user_id"] = channel_user_id
        return (
            Principal(user_id="navigator-user", tenant_id="tenant", channel="cli", channel_user_id="login-user"),
            frozenset({"connections:use"}),
        )

    def build_broker(store, providers, *, client=None):
        calls["providers"] = set(providers)
        calls["broker_store_path"] = store.path
        calls["broker_client"] = client
        return expected_broker

    monkeypatch.setattr("parrot.cli.principal.CliPrincipalResolver.resolve_with_roles", resolve_with_roles)
    monkeypatch.setattr(
        "parrot.cli.principal.build_cli_permission_context",
        lambda principal, *, roles: expected_permission_context,
    )
    monkeypatch.setattr("parrot.auth.oauth2.local_cache.build_cli_broker", build_broker)

    await server._bind_identity()

    assert calls["store_path"] == login_file
    assert calls["channel"] == "cli"
    assert calls["channel_user_id"] == "login-user"
    assert calls["providers"] == {"fake"}
    assert calls["broker_store_path"] == login_file
    assert calls["broker_client"] is not None
    assert server.execution_context.permission_context is expected_permission_context
    assert server.execution_context.broker is expected_broker
    assert all(adapter.execution_context is server.execution_context for adapter in server.tools.values())


def test_host_entries_pass_login_file_env(tmp_path, monkeypatch):
    """Install entries inherit a configured login-file path but never replace one."""
    from parrot.knowledge.wiki.claude_code.assets import toolkit_mcp_json_entry
    from parrot.knowledge.wiki.codex.assets import toolkit_mcp_block

    section = ToolkitSection.model_validate({"class": "tests.mcp.stub_toolkit.StubToolkit", "env": {"FOO": "bar"}})
    login_file = tmp_path / "login.json"
    monkeypatch.setenv("PARROT_LOGIN_FILE", str(login_file))

    claude_entry = toolkit_mcp_json_entry(tmp_path, "stub", section)
    codex_block = toolkit_mcp_block(tmp_path, {"stub": section})

    assert claude_entry["env"] == {"FOO": "bar", "PARROT_LOGIN_FILE": str(login_file)}
    assert f'PARROT_LOGIN_FILE = "{login_file}"' in codex_block

    explicit = ToolkitSection.model_validate(
        {"class": "tests.mcp.stub_toolkit.StubToolkit", "env": {"PARROT_LOGIN_FILE": "/explicit/login.json"}}
    )
    assert toolkit_mcp_json_entry(tmp_path, "stub", explicit)["env"]["PARROT_LOGIN_FILE"] == "/explicit/login.json"
    assert 'PARROT_LOGIN_FILE = "/explicit/login.json"' in toolkit_mcp_block(tmp_path, {"stub": explicit})

    monkeypatch.delenv("PARROT_LOGIN_FILE")
    assert "PARROT_LOGIN_FILE" not in toolkit_mcp_json_entry(tmp_path, "stub", section)["env"]
    assert "PARROT_LOGIN_FILE" not in toolkit_mcp_block(tmp_path, {"stub": section})


def test_mcp_local_login_file_option_reaches_factory(tmp_path, monkeypatch):
    """The explicit CLI option is passed separately from toolkit overrides."""
    from click.testing import CliRunner
    from parrot.cli import cli

    captured = {}

    def factory(name, root, *, login_file=None, **overrides):
        captured["name"] = name
        captured["login_file"] = login_file
        captured["overrides"] = overrides
        return object()

    monkeypatch.setattr("parrot.mcp.toolkit_server.create_toolkit_mcp_server", factory)
    monkeypatch.setattr(
        "parrot.mcp.local_cli.asyncio.run", lambda coroutine: getattr(coroutine, "close", lambda: None)()
    )
    monkeypatch.chdir(tmp_path)
    login_file = tmp_path / "chosen-login.json"

    result = CliRunner().invoke(cli, ["mcp-local", "stub", "--login-file", str(login_file)])

    assert result.exit_code == 0, result.output
    assert captured["name"] == "stub"
    assert captured["login_file"] == login_file
    assert captured["overrides"] == {}
