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


# ---------------------------------------------------------------------------
# No silent default auth — the env-var fallback is gone
# ---------------------------------------------------------------------------


class TestNoSilentDefaultAuth:
    """The toolkit no longer fabricates a shared account when auth is
    unconfigured. It enters an *unauthenticated* state and surfaces an
    explicit ``AuthorizationRequired`` to the LLM at tool-call time."""

    def test_no_auth_type_enters_unauthenticated_state(self) -> None:
        with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
            tk = JiraToolkit(server_url="https://acme.atlassian.net")
        assert tk.auth_type is None
        assert tk.jira is None
        assert tk._auth_error is not None
        # No client was fabricated from a heuristic/default.
        assert _FakeJIRA.instances == []

    def test_atlassian_url_no_longer_implies_basic_auth(self) -> None:
        with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
            tk = JiraToolkit(server_url="https://acme.atlassian.net")
        # Old heuristic mapped atlassian.net → basic_auth; that is gone.
        assert tk.auth_type is None

    def test_env_credentials_not_used_without_explicit_auth_type(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("JIRA_INSTANCE", "https://acme.atlassian.net")
        monkeypatch.setenv("JIRA_USERNAME", "bot@acme.com")
        monkeypatch.setenv("JIRA_PASSWORD", "env-token")
        with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
            tk = JiraToolkit()
        assert tk.auth_type is None
        assert tk.jira is None
        assert _FakeJIRA.instances == []

    @pytest.mark.asyncio
    async def test_tool_call_raises_authorization_required(self) -> None:
        with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
            tk = JiraToolkit(server_url="https://acme.atlassian.net")
        with pytest.raises(AuthorizationRequired) as exc_info:
            await tk._pre_execute("jira_get_issue")
        exc = exc_info.value
        assert exc.provider == "jira"
        assert exc.tool_name == "jira_get_issue"
        assert "not authenticated" in exc.message.lower()

    def test_explicit_basic_auth_with_env_creds_still_works(
        self, monkeypatch
    ) -> None:
        # Regression: explicit service-account config is preserved.
        monkeypatch.setenv("JIRA_USERNAME", "bot@acme.com")
        monkeypatch.setenv("JIRA_PASSWORD", "env-token")
        with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
            tk = JiraToolkit(
                auth_type="basic_auth",
                server_url="https://jira.example.com",
            )
        assert tk.auth_type == "basic_auth"
        assert tk._auth_error is None
        assert tk.jira is not None
        assert len(_FakeJIRA.instances) == 1

    @pytest.mark.asyncio
    async def test_explicit_static_mode_missing_creds_defers_to_llm(
        self,
    ) -> None:
        # Explicit basic_auth but no credentials anywhere: construction must
        # NOT crash (tools stay registered); the error reaches the LLM.
        with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
            tk = JiraToolkit(
                auth_type="basic_auth",
                server_url="https://jira.example.com",
            )
        assert tk.jira is None
        assert tk._auth_error is not None
        assert _FakeJIRA.instances == []
        with pytest.raises(AuthorizationRequired) as exc_info:
            await tk._pre_execute("jira_get_issue")
        assert exc_info.value.provider == "jira"


# ---------------------------------------------------------------------------
# jira_get_projects — runtime auth failure must be explicit
# ---------------------------------------------------------------------------


class TestGetProjectsAuthProbe:
    """A 401/silent-auth failure must raise AuthorizationRequired, never
    return an empty-but-successful payload the LLM has to interpret."""

    def _toolkit(self) -> JiraToolkit:
        with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
            tk = JiraToolkit(
                auth_type="basic_auth",
                server_url="https://acme.atlassian.net",
                username="bot@acme.com",
                password="token",
            )
        return tk

    @pytest.mark.asyncio
    async def test_empty_list_with_failed_probe_raises(self) -> None:
        tk = self._toolkit()
        tk.jira = MagicMock()
        tk.jira.projects.return_value = []
        tk._probe_auth_sync = MagicMock(
            return_value={
                "authenticated": False,
                "status_code": 401,
                "seraph_login_reason": "AUTHENTICATED_FAILED",
                "error": "HTTP 401 — AUTHENTICATED_FAILED",
            }
        )
        with pytest.raises(AuthorizationRequired) as exc_info:
            await tk.jira_get_projects()
        exc = exc_info.value
        assert exc.provider == "jira"
        assert exc.tool_name == "jira_get_projects"
        assert "401" in exc.message

    @pytest.mark.asyncio
    async def test_empty_list_with_probe_exception_raises(self) -> None:
        # The probe itself swallows transport/JiraError exceptions and
        # reports authenticated=False with only an ``error`` field.
        tk = self._toolkit()
        tk.jira = MagicMock()
        tk.jira.projects.return_value = []
        tk._probe_auth_sync = MagicMock(
            return_value={
                "authenticated": False,
                "error": "JIRAError: HTTP 401",
            }
        )
        with pytest.raises(AuthorizationRequired) as exc_info:
            await tk.jira_get_projects()
        assert "JIRAError" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_empty_list_authenticated_returns_success(self) -> None:
        tk = self._toolkit()
        tk.jira = MagicMock()
        tk.jira.projects.return_value = []
        tk._probe_auth_sync = MagicMock(
            return_value={"authenticated": True, "status_code": 200}
        )
        result = await tk.jira_get_projects()
        assert result["count"] == 0
        assert result["authenticated"] is True
        assert "no accessible projects" in result["hint"]

    @pytest.mark.asyncio
    async def test_nonempty_list_skips_probe(self) -> None:
        tk = self._toolkit()
        tk.jira = MagicMock()
        tk.jira.projects.return_value = [
            SimpleNamespace(id="1", key="NAV", name="Navigator"),
        ]
        tk._probe_auth_sync = MagicMock()
        result = await tk.jira_get_projects()
        assert result["count"] == 1
        assert result["authenticated"] is True
        tk._probe_auth_sync.assert_not_called()
