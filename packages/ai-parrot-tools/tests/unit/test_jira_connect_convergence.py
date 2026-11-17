"""Jira converges on parrot connect (FEAT-774 M10, AC-12)."""

import importlib
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from parrot.auth.exceptions import AuthorizationRequired
from parrot_tools.jiratoolkit import JiraToolkit


@pytest.mark.asyncio
async def test_jiratoolkit_local_mode_removed() -> None:
    """The old local credential module and implicit identity are unavailable."""
    with pytest.raises(ValueError, match="oauth2_local.*removed"):
        JiraToolkit(auth_type="oauth2_local")

    toolkit = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=object())
    with pytest.raises(AuthorizationRequired):
        await toolkit._pre_execute("jira_get_issue")

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("parrot_tools.jira_local_auth")


def test_jira_cli_auth_aliases_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    """The legacy command calls the generic connect helper with paste enabled."""
    from parrot_tools import jira_cli

    calls: dict[str, object] = {}

    class Client:
        def __init__(self, store) -> None:
            self.store = store

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

    async def run_connect(client, cache, provider, **kwargs):
        calls.update(provider=provider, paste=kwargs["paste"])
        return {"provider": "jira", "status": "connected", "account_id": "account-1"}

    monkeypatch.setattr(
        jira_cli,
        "LoginStore",
        lambda: SimpleNamespace(load_optional=lambda: SimpleNamespace(user_id="user-1")),
    )
    monkeypatch.setattr(jira_cli, "ServerConnectionsClient", Client)
    monkeypatch.setattr(jira_cli, "open_connection_cache", lambda store: object())
    monkeypatch.setattr("parrot.cli.connect.run_connect", run_connect)

    result = CliRunner().invoke(jira_cli.cli, ["auth"])

    assert result.exit_code == 0, result.output
    assert calls == {"provider": "jira", "paste": True}
    assert jira_cli.parse_pasted_redirect is importlib.import_module("parrot.auth.oauth2.paste").parse_pasted_redirect
