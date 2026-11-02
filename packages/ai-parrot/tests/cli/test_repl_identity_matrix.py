"""(login, --user, --server) identity matrix (FEAT-774 M7, AC-3, AC-4)."""

from unittest.mock import MagicMock

import pytest

from parrot.cli.agent_repl import _declared_providers


@pytest.mark.parametrize(
    "has_manager,providers,expected",
    [
        (False, (), set()),
        (True, ("o365", None, "jira"), {"o365", "jira"}),
    ],
)
def test_declared_provider_matrix(has_manager, providers, expected):
    """Only explicitly declared tool providers are selected for the broker."""
    bot = MagicMock()
    if not has_manager:
        del bot.tool_manager
    else:
        bot.tool_manager.get_all_tools.return_value = [
            type("Tool", (), {"credential_provider": provider})() for provider in providers
        ]
    assert _declared_providers(bot) == expected


def test_identity_o365_bootstrap_removed():
    """The previous O365 environment bootstrap remains absent."""
    import parrot.cli.identity as identity

    assert not hasattr(identity, "resolve_cli_o365_principal")
    assert not hasattr(identity, "bot_declares_o365_device_code")


# ---------------------------------------------------------------------------
# Entry-point identity regimes (AC-3, AC-14) — driven through `parrot agent`.
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, patch  # noqa: E402

from click.testing import CliRunner  # noqa: E402

from parrot.auth.principal import Principal  # noqa: E402
from parrot.cli.agent_repl import _same_origin  # noqa: E402
from parrot.cli.agent_repl import agent as agent_cmd  # noqa: E402
from parrot.cli.loaders import ServerAgentProxy  # noqa: E402
from parrot.cli.login import LoginRecord, LoginStore  # noqa: E402

LOGIN_SERVER = "https://nav.example.test"
LOGIN_TOKEN = "login-access-token"


def _save_login(path, server_url: str = LOGIN_SERVER) -> None:
    """Write a private login record for the isolated login path."""
    LoginStore(path).save(
        LoginRecord(
            server_url=server_url,
            access_token=LOGIN_TOKEN,
            refresh_token="login-refresh-token",
            expires_at=4_102_444_800,
            user_id="login-user",
            cache_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY",
            issued_at=1_700_000_000,
        )
    )


def _bot() -> MagicMock:
    bot = MagicMock()
    bot.name = "a"
    bot.get_tools_count.return_value = 0
    bot.has_tools.return_value = False
    bot.cleanup = AsyncMock()
    bot.tool_manager.get_all_tools.return_value = []
    return bot


def _loader(bot) -> AsyncMock:
    loader = AsyncMock()
    loader.load = AsyncMock(return_value=bot)
    return loader


class _RecordingProxy(ServerAgentProxy):
    """Real ServerAgentProxy subclass (keeps isinstance checks) that records its auth inputs."""

    instances: list = []

    def __init__(self, server_url, timeout=30, *, token=None, login_store=None):
        super().__init__(server_url, timeout, token=token, login_store=login_store)
        self.kwargs = {"token": token, "login_store": login_store}
        _RecordingProxy.instances.append(self)

    async def load(self, name):
        return _bot()

    async def close(self) -> None:
        return None


def _invoke(args, *, resolved=None):
    """Run `parrot agent` in batch mode with loaders, REPL and the resolver patched."""
    with (
        patch("parrot.cli.agent_repl.StandaloneAgentLoader") as standalone_cls,
        patch("parrot.cli.agent_repl.ServerAgentProxy", _RecordingProxy),
        patch("parrot.cli.agent_repl.AgentREPL") as repl_cls,
        patch("parrot.cli.agent_repl.ServerConnectionsClient"),
        patch("parrot.cli.agent_repl.CliPrincipalResolver") as resolver_cls,
    ):
        standalone_cls.return_value = _loader(_bot())
        _RecordingProxy.instances.clear()
        repl_cls.return_value.run_batch = AsyncMock(return_value=0)
        resolver_cls.return_value.resolve_with_roles = AsyncMock(return_value=resolved)
        result = CliRunner().invoke(agent_cmd, ["a", "--ui", "inline", *args], input="hi\n")
        config = repl_cls.call_args.kwargs["config"] if repl_cls.call_args else None
        proxy = _RecordingProxy.instances[0] if _RecordingProxy.instances else None
        return result, config, proxy, resolver_cls


def test_user_flag_with_login_refused_exit_2(_isolated_login_file):
    """AC-3: `--user` together with a login is refused before any agent loads."""
    _save_login(_isolated_login_file)
    result, config, _, _ = _invoke(["--user", "bob"])
    assert result.exit_code == 2 and "parrot login" in result.output
    assert config is None


def test_standalone_login_runs_as_navigator_principal(_isolated_login_file):
    """AC-3: standalone turns carry the Navigator id and a cli PermissionContext with server roles + tenant."""
    _save_login(_isolated_login_file)
    principal = Principal(user_id="nav-42", tenant_id="acme", channel="cli", channel_user_id="login-user")
    result, config, _, resolver_cls = _invoke([], resolved=(principal, frozenset({"connections:use"})))
    assert result.exit_code == 0, result.output
    resolver_cls.return_value.resolve_with_roles.assert_awaited_once_with("cli", "login-user")
    assert config.user_id == "nav-42"
    assert config.permission_context.channel == "cli"
    assert config.permission_context.session.user_id == "nav-42"
    assert config.permission_context.session.tenant_id == "acme"
    assert "connections:use" in config.permission_context.session.roles


def test_standalone_unresolved_login_fails_closed(_isolated_login_file):
    """A login whose principal cannot be resolved never falls back to the local `cli-user` identity."""
    _save_login(_isolated_login_file)
    result, config, _, _ = _invoke([], resolved=None)
    assert result.exit_code == 2 and "could not resolve" in result.output
    assert config is None


def test_standalone_without_login_keeps_local_identity():
    """No login: today's behaviour (`cli-user`, no permission context, no resolver)."""
    result, config, _, resolver_cls = _invoke([])
    assert result.exit_code == 0, result.output
    assert config.user_id == "cli-user" and config.permission_context is None
    resolver_cls.assert_not_called()


def test_server_mode_same_origin_uses_login_bearer_and_no_principal(_isolated_login_file):
    """AC-3 / AC-14: --server builds no local principal, sends no user_id, and uses the login bearer."""
    _save_login(_isolated_login_file)
    result, config, server_cls, resolver_cls = _invoke(["--server", "https://NAV.example.test:443/"])
    assert result.exit_code == 0, result.output
    resolver_cls.assert_not_called()
    assert config.user_id is None and config.permission_context is None
    assert server_cls.kwargs["token"] == LOGIN_TOKEN
    assert server_cls.kwargs["login_store"] is not None
    assert config.server_token == LOGIN_TOKEN


@pytest.mark.parametrize(
    "server",
    ["https://evil.example.test", "http://nav.example.test", "https://nav.example.test:8443"],
)
def test_server_mode_other_origin_never_gets_login_bearer(_isolated_login_file, server):
    """The login token is never sent to a server other than the one that issued it."""
    _save_login(_isolated_login_file)
    result, config, server_cls, _ = _invoke(["--server", server])
    assert result.exit_code == 0, result.output
    assert server_cls.kwargs["token"] is None
    assert server_cls.kwargs["login_store"] is None
    assert config.server_token is None and config.user_id is None
    assert LOGIN_TOKEN not in result.output and "--token" in result.output


def test_server_mode_explicit_token_wins(_isolated_login_file):
    """An explicit --token is always used, and the login refresh path stays off."""
    _save_login(_isolated_login_file)
    result, _, server_cls, _ = _invoke(["--server", "https://other.example.test", "--token", "explicit"])
    assert result.exit_code == 0, result.output
    assert server_cls.kwargs["token"] == "explicit"
    assert server_cls.kwargs["login_store"] is None


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("https://a.test", "https://A.test:443/path", True),
        ("http://a.test", "http://a.test:80", True),
        ("https://a.test", "http://a.test", False),
        ("https://a.test", "https://a.test:8443", False),
        ("https://a.test", "https://b.test", False),
        ("a.test", "a.test", False),
        ("ftp://a.test", "ftp://a.test", False),
    ],
)
def test_same_origin(left, right, expected):
    """Origins compare scheme, host (case-insensitive) and effective port; non-http(s) never match."""
    assert _same_origin(left, right) is expected


# ---------------------------------------------------------------------------
# TASK-5084 (issue:73db45b2286a a, d): insecure http warning + broker client lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "server,warned",
    [("http://parrot.example.com", True), ("https://parrot.example.com", False), ("http://localhost:5000", False)],
)
def test_server_mode_warns_before_sending_bearer_over_plain_http(server, warned):
    """A bearer bound for a non-loopback http:// server triggers a warning; https and loopback do not."""
    result, config, _, _ = _invoke(["--server", server, "--token", "explicit"])
    assert result.exit_code == 0, result.output
    assert ("plaintext http://" in result.output) is warned
    assert config.server_token == "explicit"


def test_standalone_broker_client_closed_on_exit(_isolated_login_file):
    """The REPL owns the broker's ServerConnectionsClient and closes it when the REPL exits."""
    _save_login(_isolated_login_file)
    principal = Principal(user_id="nav-42", tenant_id="acme", channel="cli", channel_user_id="login-user")
    bot = _bot()
    bot.tool_manager.get_all_tools.return_value = [type("Tool", (), {"credential_provider": "jira"})()]
    broker_client = MagicMock()
    broker_client.close = AsyncMock()
    resolver_client = MagicMock()
    resolver_client.__aenter__ = AsyncMock(return_value=resolver_client)
    resolver_client.__aexit__ = AsyncMock(return_value=None)
    built = {}

    def build_broker(store, providers, *, client=None):
        built["client"] = client
        built["providers"] = set(providers)
        return object()

    with (
        patch("parrot.cli.agent_repl.StandaloneAgentLoader") as standalone_cls,
        patch("parrot.cli.agent_repl.AgentREPL") as repl_cls,
        patch("parrot.cli.agent_repl.ServerConnectionsClient", side_effect=[resolver_client, broker_client]),
        patch("parrot.cli.agent_repl.CliPrincipalResolver") as resolver_cls,
        patch("parrot.cli.agent_repl.build_cli_broker", build_broker),
    ):
        standalone_cls.return_value = _loader(bot)
        repl_cls.return_value.run_batch = AsyncMock(return_value=0)
        resolver_cls.return_value.resolve_with_roles = AsyncMock(return_value=(principal, frozenset()))
        result = CliRunner().invoke(agent_cmd, ["a", "--ui", "inline"], input="hi\n")

    assert result.exit_code == 0, result.output
    assert built == {"client": broker_client, "providers": {"jira"}}
    broker_client.close.assert_awaited_once()
