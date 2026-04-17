"""Unit tests for :class:`JiraToolkit` OAuth 2.0 (3LO) mode (TASK-753)."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.auth.exceptions import AuthorizationRequired

from parrot_tools.jiratoolkit import JiraToolkit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeJIRA:
    """Drop-in replacement for ``jira.JIRA`` used in tests."""

    instances: list["_FakeJIRA"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        _FakeJIRA.instances.append(self)


def _make_token(access_token: str = "at-1") -> SimpleNamespace:
    return SimpleNamespace(
        access_token=access_token,
        api_base_url="https://api.atlassian.com/ex/jira/cloud-1",
        display_name="Jesus",
        site_url="https://acme.atlassian.net",
    )


def _permission_context(user_id: str = "user-1", channel: str = "telegram"):
    return SimpleNamespace(user_id=user_id, channel=channel)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove Jira env vars so tests aren't polluted by developer config."""
    for var in (
        "JIRA_INSTANCE",
        "JIRA_AUTH_TYPE",
        "JIRA_USERNAME",
        "JIRA_PASSWORD",
        "JIRA_API_TOKEN",
        "JIRA_SECRET_TOKEN",
        "JIRA_DEFAULT_PROJECT",
        "JIRA_DEFAULT_ISSUE_TYPE",
        "JIRA_DEFAULT_LABELS",
        "JIRA_DEFAULT_COMPONENTS",
        "JIRA_DEFAULT_DUE_DATE_OFFSET",
        "JIRA_DEFAULT_ESTIMATE",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _stub_nav_config(monkeypatch):
    """Force the toolkit to ignore any project-level nav_config."""
    monkeypatch.setattr(
        "parrot_tools.jiratoolkit.nav_config", None, raising=False,
    )


@pytest.fixture(autouse=True)
def _clean_jira_instances():
    _FakeJIRA.instances.clear()
    yield
    _FakeJIRA.instances.clear()


# ---------------------------------------------------------------------------
# __init__ behaviour
# ---------------------------------------------------------------------------


class TestJiraToolkitOAuthInit:
    def test_oauth2_3lo_requires_resolver(self) -> None:
        with pytest.raises(ValueError, match="credential_resolver"):
            JiraToolkit(auth_type="oauth2_3lo")

    def test_oauth2_3lo_no_client_in_init(self) -> None:
        resolver = MagicMock()
        tk = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=resolver)
        assert tk.jira is None
        assert tk.auth_type == "oauth2_3lo"
        assert tk.credential_resolver is resolver
        # Legacy _init_jira_client must NOT have been invoked.
        assert _FakeJIRA.instances == []

    def test_oauth2_3lo_does_not_need_server_url(self) -> None:
        resolver = MagicMock()
        tk = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=resolver)
        # server_url falls back to empty string but does not raise.
        assert tk.server_url == ""


# ---------------------------------------------------------------------------
# _pre_execute
# ---------------------------------------------------------------------------


class TestPreExecute:
    @pytest.mark.asyncio
    async def test_legacy_modes_are_noop(self) -> None:
        with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
            tk = JiraToolkit(
                auth_type="basic_auth",
                server_url="https://jira.example.com",
                username="bot",
                password="secret",
            )
        # Clear the client that was created during __init__, then confirm the
        # pre-hook does not rebuild it.
        original_client = tk.jira
        await tk._pre_execute("jira_get_issue")
        assert tk.jira is original_client

    @pytest.mark.asyncio
    async def test_raises_without_permission_context(self) -> None:
        resolver = MagicMock()
        tk = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=resolver)
        with pytest.raises(AuthorizationRequired) as exc_info:
            await tk._pre_execute("jira_get_issue")
        exc = exc_info.value
        assert exc.provider == "jira"
        assert exc.tool_name == "jira_get_issue"

    @pytest.mark.asyncio
    async def test_raises_when_no_user_id(self) -> None:
        resolver = MagicMock()
        tk = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=resolver)
        ctx = SimpleNamespace(user_id=None, channel="telegram")
        with pytest.raises(AuthorizationRequired, match="user_id"):
            await tk._pre_execute("jira_get_issue", _permission_context=ctx)

    @pytest.mark.asyncio
    async def test_raises_authorization_required_when_no_creds(self) -> None:
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=None)
        resolver.get_auth_url = AsyncMock(return_value="https://auth.url")
        tk = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=resolver)

        ctx = _permission_context()
        with pytest.raises(AuthorizationRequired) as exc_info:
            await tk._pre_execute("jira_get_issue", _permission_context=ctx)

        exc = exc_info.value
        assert exc.auth_url == "https://auth.url"
        assert exc.provider == "jira"
        resolver.resolve.assert_awaited_once_with("telegram", "user-1")
        resolver.get_auth_url.assert_awaited_once_with("telegram", "user-1")

    @pytest.mark.asyncio
    async def test_pre_execute_sets_jira_client(self) -> None:
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=_make_token())
        tk = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=resolver)

        with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
            await tk._pre_execute(
                "jira_get_issue", _permission_context=_permission_context(),
            )

        assert tk.jira is not None
        assert isinstance(tk.jira, _FakeJIRA)
        # Bearer token forwarded via options.headers.
        headers = tk.jira.kwargs["options"]["headers"]
        assert headers["Authorization"].startswith("Bearer ")
        assert tk.jira.kwargs["options"]["server"] == (
            "https://api.atlassian.com/ex/jira/cloud-1"
        )

    @pytest.mark.asyncio
    async def test_client_is_cached_when_token_unchanged(self) -> None:
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=_make_token())
        tk = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=resolver)
        ctx = _permission_context()

        with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
            await tk._pre_execute("tool1", _permission_context=ctx)
            first_client = tk.jira
            await tk._pre_execute("tool2", _permission_context=ctx)

        assert tk.jira is first_client
        # Only a single JIRA() instantiation should have happened.
        assert len(_FakeJIRA.instances) == 1

    @pytest.mark.asyncio
    async def test_client_cache_invalidated_when_token_hash_changes(self) -> None:
        resolver = MagicMock()
        tokens = [_make_token("at-old"), _make_token("at-new")]
        resolver.resolve = AsyncMock(side_effect=tokens)
        tk = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=resolver)
        ctx = _permission_context()

        with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
            await tk._pre_execute("tool1", _permission_context=ctx)
            first_client = tk.jira
            await tk._pre_execute("tool2", _permission_context=ctx)

        assert tk.jira is not first_client
        assert len(_FakeJIRA.instances) == 2

    @pytest.mark.asyncio
    async def test_different_users_get_separate_clients(self) -> None:
        resolver = MagicMock()
        # Same token string but different user keys → different cache entries.
        resolver.resolve = AsyncMock(
            side_effect=[_make_token("at-a"), _make_token("at-b")],
        )
        tk = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=resolver)

        with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
            await tk._pre_execute(
                "tool1",
                _permission_context=_permission_context(user_id="alice"),
            )
            client_a = tk.jira
            await tk._pre_execute(
                "tool1",
                _permission_context=_permission_context(user_id="bob"),
            )
            client_b = tk.jira

        assert client_a is not client_b
        assert len(_FakeJIRA.instances) == 2
        assert set(tk._client_cache.keys()) == {
            "telegram:alice", "telegram:bob",
        }
