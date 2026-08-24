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


class FakeCloudJIRA:
    """Stand-in for a Jira **Cloud** client: offset search is refused and
    only the cursor-based `/search/jql` endpoint pages
    (`jira/client.py:3629-3640`, 3692-3760)."""

    _is_cloud = True

    def __init__(self, pages, *, omit_is_last=False):
        self.pages, self.calls = list(pages), []
        self.omit_is_last = omit_is_last

    def search_issues(self, jql, startAt=0, **kw):  # pragma: no cover - guard
        raise AssertionError("Cloud must never use the offset `search` API")

    def enhanced_search_issues(self, jql, nextPageToken=None, maxResults=100, **kw):
        self.calls.append((jql, nextPageToken, maxResults))
        idx = int(nextPageToken.split("-")[1]) if nextPageToken else 0
        issues = self.pages[idx] if idx < len(self.pages) else []
        is_last = idx >= len(self.pages) - 1
        page = {"issues": issues}
        if not is_last:
            page["nextPageToken"] = f"tok-{idx + 1}"
        if not self.omit_is_last:
            page["isLast"] = is_last
        return page

    def fields(self):
        return []


class TestLazyDependency:
    def test_missing_jira_raises_actionable_error(self, monkeypatch):
        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "jira":
                raise ModuleNotFoundError("No module named 'jira'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked)
        iface = JiraInterface(server_url=BASE, auth_type="token_auth", token="t", verify_credentials=False)
        with pytest.raises(JiraDependencyError, match=r"ai-parrot\[jira\]"):
            asyncio.run(iface.get_projects())

    def test_module_does_not_import_jira_at_load(self):
        import inspect

        import parrot.interfaces.jira.client as mod

        src = inspect.getsource(mod)
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith(("from jira", "import jira")):
                assert line.startswith((" ", "\t")), "the `jira` import must be inside a function body"


class TestAuthResolution:
    @pytest.mark.parametrize(
        "mode,kwargs",
        [
            ("basic_auth", {"username": "u", "password": "p"}),
            ("token_auth", {"token": "t"}),
        ],
    )
    def test_static_modes_resolve(self, mode, kwargs):
        iface = JiraInterface(server_url=BASE, auth_type=mode, verify_credentials=False, **kwargs)
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
            JiraInterface(server_url=BASE, auth_type="basic_auth", verify_credentials=True)._build_client()

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
        iface = JiraInterface(server_url=BASE, token="t", verify_credentials=False)
        assert iface.auth_type == "token_auth"


class TestSearchPagination:
    def test_pages_until_exhausted(self, raw_issue):
        pages = [[raw_issue] * 100, [raw_issue] * 40]
        iface = JiraInterface(server_url=BASE, auth_type="token_auth", token="t", verify_credentials=False)
        iface._client = FakeJIRA(pages)

        async def collect():
            return [r async for r in iface.search_issues("project = NAV")]

        assert len(asyncio.run(collect())) == 140
        assert [c[1] for c in iface._client.calls] == [0, 100, 140] or [c[1] for c in iface._client.calls] == [0, 100]

    def test_missing_total_pages_until_short_page(self, raw_issue):
        """No `total` in the payload must not be read as "done"."""

        class NoTotalJIRA(FakeJIRA):
            def search_issues(self, jql, startAt=0, maxResults=100, **kw):
                page = super().search_issues(jql, startAt=startAt, maxResults=maxResults, **kw)
                page.pop("total")
                return page

        iface = JiraInterface(server_url=BASE, auth_type="token_auth", token="t", verify_credentials=False)
        iface._client = NoTotalJIRA([[raw_issue] * 100, [raw_issue] * 12])

        async def collect():
            return [r async for r in iface.search_issues("project = NAV")]

        assert len(asyncio.run(collect())) == 112

    def test_server_capped_page_size_keeps_paging(self, raw_issue):
        """A Server/DC instance may cap `maxResults` below the requested
        page size — a short page is not proof of exhaustion while `total`
        says otherwise."""

        class CappedJIRA:
            """Serves 50 issues per call regardless of `maxResults`."""

            def __init__(self, total):
                self.total, self.calls = total, []

            def search_issues(self, jql, startAt=0, maxResults=100, **kw):
                self.calls.append(startAt)
                remaining = max(self.total - startAt, 0)
                return {
                    "issues": [raw_issue] * min(50, remaining),
                    "total": self.total,
                    "startAt": startAt,
                }

            def fields(self):
                return []

        iface = JiraInterface(server_url=BASE, auth_type="token_auth", token="t", verify_credentials=False)
        iface._client = CappedJIRA(120)

        async def collect():
            return [r async for r in iface.search_issues("project = NAV")]

        assert len(asyncio.run(collect())) == 120
        assert iface._client.calls == [0, 50, 100]

    def test_empty_first_page_probes_auth(self):
        iface = JiraInterface(server_url=BASE, auth_type="token_auth", token="t", verify_credentials=False)
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
        iface = JiraInterface(server_url=BASE, auth_type="token_auth", token="t", verify_credentials=False)
        iface._client = FakeJIRA([[]])

        async def probe():
            raise JiraAuthError("X-Seraph-Loginreason: AUTHENTICATED_FAILED")

        iface._probe_myself = probe

        async def collect():
            return [r async for r in iface.search_issues("project = NAV")]

        with pytest.raises(JiraAuthError, match="AUTHENTICATED_FAILED"):
            asyncio.run(collect())


class TestCloudSearchPagination:
    """Jira Cloud is cursor-paginated: the offset loop stopped dead after
    the first page because `/search/jql` returns no `total` (the
    "only 100 tickets" `ingest-jira` bug)."""

    def _collect(self, iface):
        async def collect():
            return [r async for r in iface.search_issues("project = NAV")]

        return asyncio.run(collect())

    def _iface(self, client):
        iface = JiraInterface(server_url=BASE, auth_type="token_auth", token="t", verify_credentials=False)
        iface._client = client
        return iface

    def test_follows_next_page_token_until_last(self, raw_issue):
        pages = [[raw_issue] * 100, [raw_issue] * 100, [raw_issue] * 17]
        iface = self._iface(FakeCloudJIRA(pages))

        assert len(self._collect(iface)) == 217
        assert [c[1] for c in iface._client.calls] == [None, "tok-1", "tok-2"]

    def test_stops_on_absent_token_when_is_last_missing(self, raw_issue):
        """`isLast` is not guaranteed — an absent `nextPageToken` ends it."""
        pages = [[raw_issue] * 100, [raw_issue] * 5]
        iface = self._iface(FakeCloudJIRA(pages, omit_is_last=True))

        assert len(self._collect(iface)) == 105
        assert [c[1] for c in iface._client.calls] == [None, "tok-1"]

    def test_repeated_token_raises_instead_of_looping_or_lying(self, raw_issue):
        """A non-advancing cursor must NOT read as "scope exhausted" — that
        silent-stop shape is what let the old offset loop truncate a corpus
        while its caller recorded a complete-looking watermark."""

        class StuckCloudJIRA(FakeCloudJIRA):
            def enhanced_search_issues(self, jql, nextPageToken=None, maxResults=100, **kw):
                self.calls.append((jql, nextPageToken, maxResults))
                return {"issues": [raw_issue], "nextPageToken": "stuck"}

        iface = self._iface(StuckCloudJIRA([]))

        with pytest.raises(RuntimeError, match="repeated nextPageToken"):
            self._collect(iface)
        assert len(iface._client.calls) == 2, "it must stop at the repeat, not loop"

    def test_empty_first_page_probes_auth(self):
        iface = self._iface(FakeCloudJIRA([[]]))
        probed = {"n": 0}

        async def probe():
            probed["n"] += 1
            return {"accountId": "x"}

        iface._probe_myself = probe

        assert self._collect(iface) == []
        assert probed["n"] == 1, "an empty page MUST probe /myself"


class TestAcceptanceCriteriaField:
    def test_config_key_wins(self, monkeypatch):
        monkeypatch.setenv("JIRA_WIKI_AC_FIELD", "customfield_99999")
        iface = JiraInterface(server_url=BASE, auth_type="token_auth", token="t", verify_credentials=False)
        assert asyncio.run(iface.resolve_ac_field_id()) == "customfield_99999"

    def test_dynamic_by_name_fallback(self, monkeypatch):
        monkeypatch.delenv("JIRA_WIKI_AC_FIELD", raising=False)
        iface = JiraInterface(server_url=BASE, auth_type="token_auth", token="t", verify_credentials=False)
        iface._client = FakeJIRA(
            [],
            fields=[
                {"id": "customfield_10101", "name": "Acceptance Criteria"},
                {"id": "customfield_10102", "name": "Story Points"},
            ],
        )
        assert asyncio.run(iface.resolve_ac_field_id()) == "customfield_10101"

    def test_returns_none_and_never_raises_when_absent(self, monkeypatch):
        monkeypatch.delenv("JIRA_WIKI_AC_FIELD", raising=False)
        iface = JiraInterface(server_url=BASE, auth_type="token_auth", token="t", verify_credentials=False)
        iface._client = FakeJIRA([], fields=[{"id": "customfield_1", "name": "Story Points"}])
        assert asyncio.run(iface.resolve_ac_field_id()) is None

    def test_result_is_cached(self, monkeypatch):
        monkeypatch.delenv("JIRA_WIKI_AC_FIELD", raising=False)
        iface = JiraInterface(server_url=BASE, auth_type="token_auth", token="t", verify_credentials=False)
        calls = {"n": 0}

        class CountingFake(FakeJIRA):
            def fields(self):
                calls["n"] += 1
                return [{"id": "customfield_10101", "name": "Acceptance Criteria"}]

        iface._client = CountingFake([])
        asyncio.run(iface.resolve_ac_field_id())
        asyncio.run(iface.resolve_ac_field_id())
        assert calls["n"] == 1


class TestReadOnlySurface:
    def test_no_write_methods_exposed(self):
        """This interface is read-only; writes stay in JiraToolkit."""
        for forbidden in (
            "transition_issue",
            "add_comment",
            "create_issue",
            "assign_issue",
            "update_issue",
            "add_attachment",
        ):
            assert not hasattr(JiraInterface, forbidden)

    def test_parse_issue_is_a_delegating_staticmethod(self, raw_issue):
        from parrot.interfaces.jira import parse as parse_mod

        assert isinstance(JiraInterface.__dict__["parse_issue"], staticmethod)
        a = JiraInterface.parse_issue(raw_issue, base_url=BASE)
        b = parse_mod.parse_issue(raw_issue, base_url=BASE)
        assert a.model_dump_json() == b.model_dump_json()


class _FakeResultList(list):
    """A `list` that also carries `nextPageToken`/`isLast`, mirroring
    pycontribs' `ResultList` shape closely enough for these tests."""

    nextPageToken = None
    isLast = True


class FakeEnhancedJIRA:
    """Fake `jira.JIRA` exercising `projects()`, `issue()` and
    `enhanced_search_issues()` — the JiraToolkit delegation seam
    (TASK-2402)."""

    def __init__(self, *, projects=None, issue=None, pages=None):
        self._projects = projects or []
        self._issue = issue
        self.pages = list(pages or [])
        self.enhanced_calls = []

    def projects(self):
        return self._projects

    def issue(self, key, fields=None, expand=None):
        return self._issue

    def enhanced_search_issues(self, jql, *, maxResults, fields, expand, nextPageToken):
        self.enhanced_calls.append({"fields": fields, "nextPageToken": nextPageToken})
        idx = len(self.enhanced_calls) - 1
        batch = self.pages[idx] if idx < len(self.pages) else []
        return _FakeResultList(batch)


class TestDelegationSeamAdditions:
    """TASK-2402 additions: attach_client, list_projects,
    fetch_issue_object, fetch_issues — the thin, object-returning
    transport primitives JiraToolkit delegates through."""

    def test_attach_client_bypasses_own_resolution(self):
        iface = JiraInterface(auth_type="token_auth", token="t", verify_credentials=False)
        fake = object()
        iface.attach_client(fake)
        assert asyncio.run(iface._ensure_client()) is fake

    def test_attach_client_wins_even_in_oauth2_3lo_mode(self):
        """The delegation seam JiraToolkit relies on: an attached client
        always wins, bypassing this interface's own credential_resolver
        resolution entirely — regardless of auth_type."""
        iface = JiraInterface(auth_type="oauth2_3lo", verify_credentials=False)
        fake = object()
        iface.attach_client(fake)
        assert asyncio.run(iface._ensure_client()) is fake

    def test_list_projects_no_probe_on_empty(self):
        """Unlike get_projects(), list_projects() never probes /myself —
        JiraToolkit already owns its own probe/error-message construction."""
        iface = JiraInterface(auth_type="token_auth", token="t", verify_credentials=False)
        iface.attach_client(FakeEnhancedJIRA(projects=[]))
        assert asyncio.run(iface.list_projects()) == []

    def test_fetch_issue_object_returns_raw_object_unprojected(self):
        iface = JiraInterface(auth_type="token_auth", token="t", verify_credentials=False)
        sentinel = object()
        iface.attach_client(FakeEnhancedJIRA(issue=sentinel))
        result = asyncio.run(iface.fetch_issue_object("NAV-1"))
        assert result is sentinel

    def test_fetch_issues_empty_string_fields_degrades_to_none(self):
        """Adversarial review finding: `fields=""` must degrade to `None`
        (every field), matching JiraToolkit's original inline
        `fields.split(',') if fields else None` — not to `['']`."""
        client = FakeEnhancedJIRA(pages=[[]])
        iface = JiraInterface(auth_type="token_auth", token="t", verify_credentials=False)
        iface.attach_client(client)
        asyncio.run(iface.fetch_issues("project = NAV", fields=""))
        assert client.enhanced_calls[0]["fields"] is None

    def test_fetch_issues_comma_string_fields_still_splits(self):
        client = FakeEnhancedJIRA(pages=[[]])
        iface = JiraInterface(auth_type="token_auth", token="t", verify_credentials=False)
        iface.attach_client(client)
        asyncio.run(iface.fetch_issues("project = NAV", fields="key,status"))
        assert client.enhanced_calls[0]["fields"] == ["key", "status"]

    def test_fetch_issues_list_fields_passthrough(self):
        client = FakeEnhancedJIRA(pages=[[]])
        iface = JiraInterface(auth_type="token_auth", token="t", verify_credentials=False)
        iface.attach_client(client)
        asyncio.run(iface.fetch_issues("project = NAV", fields=["key", "status"]))
        assert client.enhanced_calls[0]["fields"] == ["key", "status"]
