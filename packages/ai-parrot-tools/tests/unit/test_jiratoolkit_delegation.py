"""FEAT-454 M2 — the toolkit delegates reads; nothing else moves.

Regenerate ``ENVELOPE_KEYS_BASELINE`` ONLY if FEAT-138/TASK-948
intentionally changes the envelope shape — never to make this test pass.
Captured pre-refactor via:
``python -c "from parrot_tools.jiratoolkit import JiraToolEnvelope as E;
print(sorted(E.__annotations__))"`` -> ``['data', 'message', 'query', 'status']``.
"""

import inspect
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.interfaces.jira import JiraAuthError
from parrot_tools.jiratoolkit import (
    JiraAuthenticationError,
    JiraToolEnvelope,
    JiraToolkit,
)

ENVELOPE_KEYS_BASELINE: set[str] = {"data", "message", "query", "status"}

INIT_PARAMS_BASELINE: tuple[str, ...] = (
    "self",
    "server_url",
    "auth_type",
    "username",
    "password",
    "token",
    "oauth_consumer_key",
    "oauth_key_cert",
    "oauth_access_token",
    "oauth_access_token_secret",
    "default_project",
    "credential_resolver",
    "workflow_paths",
    "verify_credentials",
    "kwargs",
)


class _FakeJIRA:
    """Drop-in replacement for ``jira.JIRA`` (mirrors test_jiratoolkit_oauth.py)."""

    instances: ClassVar[list["_FakeJIRA"]] = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        _FakeJIRA.instances.append(self)


class _FakeReadInterface:
    """Stand-in for ``JiraInterface`` used to assert the delegation seam."""

    def __init__(self):
        self.attach_client = MagicMock()
        self.fetch_issue_object = AsyncMock(return_value=MagicMock(raw={"id": "1", "key": "NAV-1"}))
        self.get_changelog = AsyncMock(return_value=[])
        self.fetch_issues = AsyncMock(return_value=[])
        self.list_projects = AsyncMock(return_value=[])


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
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("parrot_tools.jiratoolkit.nav_config", None, raising=False)


@pytest.fixture(autouse=True)
def _clean_jira_instances():
    _FakeJIRA.instances.clear()
    yield
    _FakeJIRA.instances.clear()


@pytest.fixture
def toolkit() -> JiraToolkit:
    with patch("parrot_tools.jiratoolkit.JIRA", _FakeJIRA):
        return JiraToolkit(
            server_url="https://x.atlassian.net",
            auth_type="token_auth",
            token="t",
            verify_credentials=False,
        )


def _attach_fake_interface(tk: JiraToolkit, fake: _FakeReadInterface) -> None:
    """Install a stub interface, bypassing the property's lazy construction."""
    tk._JiraToolkit__read_interface = fake


class TestFrozenPublicSurface:
    def test_init_signature_unchanged(self):
        params = tuple(inspect.signature(JiraToolkit.__init__).parameters)
        assert params == INIT_PARAMS_BASELINE

    def test_envelope_annotations_unchanged(self):
        assert set(JiraToolEnvelope.__annotations__) == ENVELOPE_KEYS_BASELINE

    @pytest.mark.parametrize(
        "method,expected",
        [
            (
                "jira_search_issues",
                (
                    "self",
                    "jql",
                    "start_at",
                    "max_results",
                    "fields",
                    "expand",
                    "json_result",
                    "store_as_dataframe",
                    "dataframe_name",
                    "summary_only",
                    "structured",
                ),
            ),
            ("jira_count_issues", ("self", "jql", "group_by")),
        ],
    )
    def test_tool_signatures_unchanged(self, method, expected):
        params = tuple(inspect.signature(getattr(JiraToolkit, method)).parameters)
        assert params == expected


class TestDelegation:
    def test_read_methods_have_no_direct_transport(self):
        """G1: no read method builds its own JIRA client or raw request."""
        for name in (
            "jira_get_issue",
            "jira_search_issues",
            "jira_count_issues",
            "jira_get_projects",
            "_get_full_changelog",
        ):
            src = inspect.getsource(getattr(JiraToolkit, name))
            for banned in ("_init_jira_client(", "JIRA(", "requests.", "self.jira._session"):
                assert banned not in src, f"{name} still does {banned}"

    @pytest.mark.asyncio
    async def test_get_issue_reaches_the_interface(self, toolkit):
        fake = _FakeReadInterface()
        _attach_fake_interface(toolkit, fake)
        await toolkit.jira_get_issue("NAV-1")
        fake.fetch_issue_object.assert_awaited_once_with("NAV-1", fields=None, expand=None)

    @pytest.mark.asyncio
    async def test_search_issues_reaches_the_interface(self, toolkit):
        fake = _FakeReadInterface()
        _attach_fake_interface(toolkit, fake)
        await toolkit.jira_search_issues("project = NAV")
        fake.fetch_issues.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_full_changelog_reaches_the_interface(self, toolkit):
        fake = _FakeReadInterface()
        _attach_fake_interface(toolkit, fake)
        await toolkit._get_full_changelog("NAV-1")
        fake.get_changelog.assert_awaited_once_with("NAV-1", page_size=100)

    @pytest.mark.asyncio
    async def test_get_projects_reaches_the_interface(self, toolkit):
        fake = _FakeReadInterface()
        fake.list_projects = AsyncMock(return_value=[{"id": "1", "key": "NAV", "name": "Navigator"}])
        _attach_fake_interface(toolkit, fake)
        result = await toolkit.jira_get_projects()
        fake.list_projects.assert_awaited_once()
        assert result["projects"] == [{"id": "1", "key": "NAV", "name": "Navigator"}]

    def test_interface_built_once_per_toolkit(self, toolkit):
        """No second credential resolution (G1) — the same JiraInterface
        instance is reused across every delegated call."""
        first = toolkit._read_interface
        second = toolkit._read_interface
        assert first is second

    def test_write_methods_still_use_self_jira(self):
        for name in ("jira_transition_issue", "jira_add_comment", "jira_create_issue"):
            method = getattr(JiraToolkit, name, None)
            if method is None:
                continue
            assert "self.jira" in inspect.getsource(method)


class TestErrorTaxonomyPreserved:
    @pytest.mark.asyncio
    async def test_interface_auth_error_is_translated(self, toolkit):
        """A JiraAuthError from the interface must NOT leak to callers."""
        fake = _FakeReadInterface()
        fake.list_projects = AsyncMock(side_effect=JiraAuthError("nope"))
        _attach_fake_interface(toolkit, fake)
        with pytest.raises(JiraAuthenticationError):
            await toolkit.jira_get_projects()

    @pytest.mark.asyncio
    async def test_get_full_changelog_auth_error_is_translated(self, toolkit):
        """Adversarial review finding: _get_full_changelog has no
        try/except of its own (matching its pre-refactor shape) and is
        called from jira_get_issue's include_history block, which runs
        AFTER that method's own try/except has already exited — so a
        JiraAuthError from the interface must be translated here, not
        left to leak as a brand-new exception type."""
        fake = _FakeReadInterface()
        fake.get_changelog = AsyncMock(side_effect=JiraAuthError("nope"))
        _attach_fake_interface(toolkit, fake)
        with pytest.raises(JiraAuthenticationError):
            await toolkit._get_full_changelog("NAV-1")

    @pytest.mark.asyncio
    async def test_get_issue_auth_error_is_translated(self, toolkit):
        """Adversarial review finding: jira_get_issue's own docstring
        promises "Authentication and permission errors are re-raised
        rather than wrapped" — a JiraAuthError from the interface must
        honour that, not fall into the trailing except Exception and get
        silently downgraded to a generic status="error" envelope."""
        fake = _FakeReadInterface()
        fake.fetch_issue_object = AsyncMock(side_effect=JiraAuthError("nope"))
        _attach_fake_interface(toolkit, fake)
        with pytest.raises(JiraAuthenticationError):
            await toolkit.jira_get_issue("NAV-1")

    @pytest.mark.asyncio
    async def test_search_issues_auth_error_is_translated(self, toolkit):
        """jira_search_issues's own docstring promises "Authentication
        errors are re-raised" — same contract as jira_get_issue."""
        fake = _FakeReadInterface()
        fake.fetch_issues = AsyncMock(side_effect=JiraAuthError("nope"))
        _attach_fake_interface(toolkit, fake)
        with pytest.raises(JiraAuthenticationError):
            await toolkit.jira_search_issues("project = NAV")

    def test_missing_jira_dependency_message_is_actionable(self):
        """The toolkit module hard-imports `jira` at load time
        (jiratoolkit.py ~:46), so it cannot even be imported without the
        distribution installed — JiraInterface's lazy JiraDependencyError
        path is architecturally unreachable through this toolkit. This
        documents that fact rather than asserting an unreachable behavior.
        """
        import parrot_tools.jiratoolkit as mod

        src = inspect.getsource(mod)
        assert "from jira import JIRA" in src
        assert "raise ImportError" in src


class TestOAuth3LO:
    def test_toolkit_scopes_not_narrowed_by_interface(self):
        """The toolkit needs write scope (jiratoolkit.py:1030-1033)."""
        assert "write:jira-work" in JiraToolkit._OAUTH_SCOPES

    def test_per_user_token_resolved_once_per_call(self):
        """The interface must reuse the toolkit's already-resolved client
        (attached via attach_client), never resolve the token itself."""
        resolver = MagicMock()
        tk = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=resolver)
        fake_client = MagicMock()
        # Simulate what _pre_execute would have done: resolve once, set self.jira.
        tk.jira = fake_client

        iface = tk._read_interface

        assert iface._client is fake_client
        # JiraInterface's own (zero-arg) credential_resolver.resolve() must
        # never be called — the toolkit's resolver only ever gets invoked
        # via its OWN _pre_execute, with the (channel, user_id) it has.
        resolver.resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_bypassing_pre_execute_raises_clean_auth_error_not_typeerror(self):
        """Adversarial review finding: if a read method is ever reached
        with self.jira still None (e.g. a direct call bypassing
        _pre_execute), the interface's own oauth2_3lo path must not be
        reachable with this toolkit's 2-arg credential_resolver — it would
        raise a confusing TypeError (arity mismatch) instead of a clean,
        catchable JiraAuthError. _read_interface deliberately does not
        forward credential_resolver, so this degrades to a clear message
        instead."""
        resolver = MagicMock()
        tk = JiraToolkit(auth_type="oauth2_3lo", credential_resolver=resolver)
        assert tk.jira is None  # _pre_execute never ran

        with pytest.raises(JiraAuthError, match="credential_resolver"):
            await tk._read_interface.list_projects()
        resolver.resolve.assert_not_called()


class TestCountDoesNotPage:
    @pytest.mark.asyncio
    async def test_count_issues_delegates_to_search_with_max_results_none(self, toolkit):
        """jira_count_issues fetches ALL matching issues by design (its own
        docstring: "Fetches ALL matching issues to provide accurate
        counts") — it delegates entirely to jira_search_issues(max_results
        =None), which is unchanged by this refactor. This corrects the
        task's stale "does not page" assumption against the real code."""
        fake = _FakeReadInterface()
        fake.fetch_issues = AsyncMock(return_value=[])
        _attach_fake_interface(toolkit, fake)
        await toolkit.jira_count_issues("project = NAV")
        _, kwargs = fake.fetch_issues.call_args
        assert kwargs["max_results"] is None
