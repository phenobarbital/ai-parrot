"""Tests for `JiraInterface` — auth resolution + read surface (FEAT-454, M1)."""
import asyncio
import builtins

import pytest
from parrot.interfaces.jira import JiraAuthError, JiraDependencyError, JiraInterface

BASE = "https://example.atlassian.net"


class FakeJIRA:
    """Minimal stand-in for pycontribs `jira.JIRA` (synchronous)."""

    def __init__(self, pages, *, myself=None, fields=None, **kwargs):
        self.pages, self.calls, self.kwargs = list(pages), [], kwargs
        self._myself, self._fields = myself, fields or []

    def search_issues(self, jql, startAt=0, maxResults=100, **kw):
        self.calls.append((jql, startAt, maxResults))
        idx = startAt // max(maxResults, 1)
        issues = self.pages[idx] if idx < len(self.pages) else []
        total = sum(len(p) for p in self.pages)
        return {"issues": issues, "total": total, "startAt": startAt}

    def fields(self):
        return self._fields


class TestLazyDependency:
    def test_missing_jira_raises_actionable_error(self, monkeypatch):
        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "jira":
                raise ModuleNotFoundError("No module named 'jira'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked)
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        with pytest.raises(JiraDependencyError, match=r"ai-parrot\[jira\]"):
            asyncio.run(iface.get_projects())

    def test_module_does_not_import_jira_at_load(self):
        import inspect

        import parrot.interfaces.jira.client as mod
        src = inspect.getsource(mod)
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith(("from jira", "import jira")):
                assert line.startswith((" ", "\t")), \
                    "the `jira` import must be inside a function body"


class TestAuthResolution:
    @pytest.mark.parametrize("mode,kwargs", [
        ("basic_auth", {"username": "u", "password": "p"}),
        ("token_auth", {"token": "t"}),
    ])
    def test_static_modes_resolve(self, mode, kwargs):
        iface = JiraInterface(server_url=BASE, auth_type=mode,
                              verify_credentials=False, **kwargs)
        assert iface.auth_type == mode
        assert iface.server_url == BASE

    def test_basic_auth_without_credentials_raises(self, monkeypatch):
        # This dev environment's real navconfig/.env carries live Jira
        # credentials. navconfig's dotenv loading has a side effect of
        # populating os.environ directly (not just its own internal store),
        # so JIRA_USERNAME/JIRA_PASSWORD/JIRA_API_TOKEN are real env vars in
        # this process regardless of the nav_config object — `_cfg` would
        # otherwise silently satisfy the "requires username and password"
        # check below, or worse, construct a real client against the fake
        # BASE url. Neutralize both layers so this test is hermetic
        # regardless of the local environment.
        monkeypatch.setattr("parrot.interfaces.jira.client.nav_config", None)
        for leaked in ("JIRA_USERNAME", "JIRA_PASSWORD", "JIRA_API_TOKEN"):
            monkeypatch.delenv(leaked, raising=False)
        with pytest.raises(ValueError, match="basic_auth requires"):
            JiraInterface(server_url=BASE, auth_type="basic_auth",
                          verify_credentials=True)._build_client()

    def test_oauth2_3lo_does_not_require_server_url(self):
        """3LO resolves the URL per-user at runtime (jiratoolkit.py:780)."""
        iface = JiraInterface(auth_type="oauth2_3lo", verify_credentials=False)
        assert iface.auth_type == "oauth2_3lo"

    def test_unresolved_auth_type_never_uses_env(self, monkeypatch):
        """jiratoolkit.py:767-775 — no heuristic, no silent service account."""
        monkeypatch.setattr("parrot.interfaces.jira.client.nav_config", None)
        monkeypatch.setenv("JIRA_USERNAME", "leaked")
        monkeypatch.setenv("JIRA_API_TOKEN", "leaked")
        monkeypatch.delenv("JIRA_AUTH_TYPE", raising=False)
        iface = JiraInterface(server_url=BASE)
        assert iface.auth_type is None
        with pytest.raises(JiraAuthError, match="JIRA_AUTH_TYPE"):
            asyncio.run(iface.get_issue("NAV-1"))

    def test_env_auth_type_is_honoured_and_lowercased(self, monkeypatch):
        monkeypatch.setattr("parrot.interfaces.jira.client.nav_config", None)
        monkeypatch.setenv("JIRA_AUTH_TYPE", "TOKEN_AUTH")
        iface = JiraInterface(server_url=BASE, token="t",
                              verify_credentials=False)
        assert iface.auth_type == "token_auth"


class TestSearchPagination:
    def test_pages_until_exhausted(self, raw_issue):
        pages = [[raw_issue] * 100, [raw_issue] * 40]
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        iface._client = FakeJIRA(pages)

        async def collect():
            return [r async for r in iface.search_issues("project = NAV")]

        assert len(asyncio.run(collect())) == 140
        assert [c[1] for c in iface._client.calls] == [0, 100, 140] or \
               [c[1] for c in iface._client.calls] == [0, 100]

    def test_empty_first_page_probes_auth(self):
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        iface._client = FakeJIRA([[]])
        probed = {"n": 0}

        async def probe():
            probed["n"] += 1
            return {"accountId": "x"}

        iface._probe_myself = probe

        async def collect():
            return [r async for r in iface.search_issues("project = NAV")]

        assert asyncio.run(collect()) == []
        assert probed["n"] == 1, "an empty page MUST probe /myself"

    def test_seraph_failure_on_empty_page_raises(self):
        """The AUTHENTICATED_FAILED trap — jiratoolkit.py:2259-2266."""
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        iface._client = FakeJIRA([[]])

        async def probe():
            raise JiraAuthError("X-Seraph-Loginreason: AUTHENTICATED_FAILED")

        iface._probe_myself = probe

        async def collect():
            return [r async for r in iface.search_issues("project = NAV")]

        with pytest.raises(JiraAuthError, match="AUTHENTICATED_FAILED"):
            asyncio.run(collect())


class TestAcceptanceCriteriaField:
    def test_config_key_wins(self, monkeypatch):
        monkeypatch.setenv("JIRA_WIKI_AC_FIELD", "customfield_99999")
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        assert asyncio.run(iface.resolve_ac_field_id()) == "customfield_99999"

    def test_dynamic_by_name_fallback(self, monkeypatch):
        monkeypatch.delenv("JIRA_WIKI_AC_FIELD", raising=False)
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        iface._client = FakeJIRA([], fields=[
            {"id": "customfield_10101", "name": "Acceptance Criteria"},
            {"id": "customfield_10102", "name": "Story Points"},
        ])
        assert asyncio.run(iface.resolve_ac_field_id()) == "customfield_10101"

    def test_returns_none_and_never_raises_when_absent(self, monkeypatch):
        monkeypatch.delenv("JIRA_WIKI_AC_FIELD", raising=False)
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        iface._client = FakeJIRA([], fields=[{"id": "customfield_1",
                                              "name": "Story Points"}])
        assert asyncio.run(iface.resolve_ac_field_id()) is None

    def test_result_is_cached(self, monkeypatch):
        monkeypatch.delenv("JIRA_WIKI_AC_FIELD", raising=False)
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        calls = {"n": 0}

        class CountingFake(FakeJIRA):
            def fields(self):
                calls["n"] += 1
                return [{"id": "customfield_10101",
                         "name": "Acceptance Criteria"}]

        iface._client = CountingFake([])
        asyncio.run(iface.resolve_ac_field_id())
        asyncio.run(iface.resolve_ac_field_id())
        assert calls["n"] == 1


class TestReadOnlySurface:
    def test_no_write_methods_exposed(self):
        """This interface is read-only; writes stay in JiraToolkit."""
        for forbidden in ("transition_issue", "add_comment", "create_issue",
                          "assign_issue", "update_issue", "add_attachment"):
            assert not hasattr(JiraInterface, forbidden)

    def test_parse_issue_is_a_delegating_staticmethod(self, raw_issue):
        from parrot.interfaces.jira import parse as parse_mod
        assert isinstance(
            JiraInterface.__dict__["parse_issue"], staticmethod)
        a = JiraInterface.parse_issue(raw_issue, base_url=BASE)
        b = parse_mod.parse_issue(raw_issue, base_url=BASE)
        assert a.model_dump_json() == b.model_dump_json()
