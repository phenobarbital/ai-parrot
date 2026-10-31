"""FEAT-775 AC-13: Teams OAuth lookup uses the AAD oid; PBAC keeps the Navigator id."""
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.permission import PermissionContext, UserSession
from parrot_tools import jiratoolkit
from parrot_tools.o365.oauth_toolkit import Office365Toolkit


def _teams_ctx(channel_user_id: str | None) -> PermissionContext:
    """Build a Teams context with distinct Navigator and channel identities."""
    return PermissionContext(
        session=UserSession(user_id="42", tenant_id="t-1", roles=frozenset()),
        channel="msteams",
        channel_user_id=channel_user_id,
    )


def _telegram_ctx() -> PermissionContext:
    """Build a non-Teams context that retains the Navigator identity."""
    return PermissionContext(
        session=UserSession(user_id="42", tenant_id="t-1", roles=frozenset()),
        channel="telegram",
    )


class _RecordingResolver:
    """Credential resolver fake that records lookup and authorization URL identities."""

    def __init__(self, token_set: Any = None) -> None:
        """Initialize the fake resolver with an optional successful token result."""
        self.token_set = token_set
        self.calls: list[tuple[str, str, str]] = []

    async def resolve(self, channel: str, user_id: str) -> Any:
        """Record a credential lookup and return the configured token set."""
        self.calls.append(("resolve", channel, user_id))
        return self.token_set

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Record authorization URL construction."""
        self.calls.append(("get_auth_url", channel, user_id))
        return "https://example.test/connect"


class _FakeJira:
    """Minimal JIRA client fake for successful per-user toolkit setup."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Accept the Jira client's construction arguments."""
        self.args = args
        self.kwargs = kwargs


def _token() -> SimpleNamespace:
    """Return token fields required by the Jira and Office365 toolkits."""
    return SimpleNamespace(
        access_token="access-token",
        api_base_url="https://api.atlassian.com/ex/jira/cloud-1",
    )


@pytest.mark.asyncio
async def test_teams_oauth_identity_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Teams resolver calls use the trusted AAD oid, including numeric values."""
    principal_calls: list[tuple[str, str]] = []

    async def resolve_principal(channel: str, user_id: str) -> SimpleNamespace:
        """Record Jira's principal resolution without consulting external state."""
        principal_calls.append((channel, user_id))
        return SimpleNamespace(user_id="42")

    monkeypatch.setattr(jiratoolkit, "resolve_principal", resolve_principal)
    jira_resolver = _RecordingResolver()
    o365_resolver = _RecordingResolver()
    jira = jiratoolkit.JiraToolkit(auth_type="oauth2_3lo", credential_resolver=jira_resolver)
    o365 = Office365Toolkit(credential_resolver=o365_resolver)

    with pytest.raises(AuthorizationRequired):
        await jira._pre_execute("jira_get_issue", _permission_context=_teams_ctx("aad-1"))
    with pytest.raises(AuthorizationRequired):
        await o365._pre_execute("o365_read_inbox", _permission_context=_teams_ctx("aad-1"))

    numeric_resolver = _RecordingResolver()
    numeric_o365 = Office365Toolkit(credential_resolver=numeric_resolver)
    with pytest.raises(AuthorizationRequired):
        await numeric_o365._pre_execute("o365_read_inbox", _permission_context=_teams_ctx("12345"))

    assert principal_calls == [("msteams", "aad-1")]
    assert jira_resolver.calls == [
        ("resolve", "msteams", "aad-1"),
        ("get_auth_url", "msteams", "aad-1"),
    ]
    assert o365_resolver.calls == [
        ("resolve", "msteams", "aad-1"),
        ("get_auth_url", "msteams", "aad-1"),
    ]
    assert numeric_resolver.calls == [
        ("resolve", "msteams", "12345"),
        ("get_auth_url", "msteams", "12345"),
    ]


@pytest.mark.asyncio
async def test_teams_missing_oid_fails_closed() -> None:
    """Teams contexts without an AAD oid fail before either resolver is called."""
    jira_resolver = _RecordingResolver()
    o365_resolver = _RecordingResolver()
    jira = jiratoolkit.JiraToolkit(auth_type="oauth2_3lo", credential_resolver=jira_resolver)
    o365 = Office365Toolkit(credential_resolver=o365_resolver)

    with pytest.raises(AuthorizationRequired, match="without a user_id"):
        await jira._pre_execute("jira_get_issue", _permission_context=_teams_ctx(None))
    with pytest.raises(AuthorizationRequired, match="without a user_id"):
        await o365._pre_execute("o365_read_inbox", _permission_context=_teams_ctx(None))

    assert jira_resolver.calls == []
    assert o365_resolver.calls == []


@pytest.mark.asyncio
async def test_non_teams_and_local_cli_unchanged() -> None:
    """Non-Teams lookups keep the Navigator id and local Jira keeps cli/local."""
    async def resolve_principal(channel: str, user_id: str) -> SimpleNamespace:
        """Return the canonical Navigator principal for the non-Teams lookup."""
        return SimpleNamespace(user_id="42")

    jira_resolver = _RecordingResolver(token_set=_token())
    o365_resolver = _RecordingResolver(token_set=_token())
    local_resolver = _RecordingResolver(token_set=_token())
    jira = jiratoolkit.JiraToolkit(auth_type="oauth2_3lo", credential_resolver=jira_resolver)
    o365 = Office365Toolkit(credential_resolver=o365_resolver)
    local_jira = jiratoolkit.JiraToolkit(auth_type="oauth2_local", credential_resolver=local_resolver)

    with patch.object(jiratoolkit, "resolve_principal", resolve_principal), patch.object(
        jiratoolkit, "JIRA", _FakeJira
    ):
        await jira._pre_execute("jira_get_issue", _permission_context=_telegram_ctx())
        await o365._pre_execute("o365_read_inbox", _permission_context=_telegram_ctx())
        await local_jira._pre_execute("jira_get_issue")

    assert jira_resolver.calls == [("resolve", "telegram", "42")]
    assert o365_resolver.calls == [("resolve", "telegram", "42")]
    assert local_resolver.calls == [("resolve", "cli", "local")]
