"""Unit tests for `BaseResearchToolkit` (FEAT-426 Module 1)."""
from unittest.mock import AsyncMock

from parrot.tools.toolkit import AbstractToolkit
from parrot_tools.research.base import BaseResearchToolkit
from parrot_tools.research.models import ResearchResult


class _Probe(BaseResearchToolkit, AbstractToolkit):
    """Minimal concrete toolkit used to exercise the mixin in isolation."""

    async def do_thing(self, query: str) -> ResearchResult:
        """Do a thing."""
        return ResearchResult(query=query, source="probe", result_type="papers")


class TestBaseResearchToolkitMROAndInit:
    def test_mro_and_init(self):
        """`OpenDataToolkit()` (here: `_Probe()`) constructs; base attrs initialised."""
        tk = _Probe()
        for attr in ("_opened", "_open_lock", "logger", "_tool_cache"):
            assert hasattr(tk, attr), f"{attr} missing — super().__init__ not called"

    def test_auto_open_is_true(self):
        assert _Probe.auto_open is True


class TestNoPrivateHelpersExposed:
    def test_only_public_method_becomes_a_tool(self):
        """`get_tools()` exposes no name starting with `_` and no base-mixin helper."""
        names = [t.name for t in _Probe().get_tools()]
        assert names == ["do_thing"]
        for leaked in (
            "_open", "_close", "_make_api_request", "_run_sync_in_executor",
            "_build_citation", "_failure",
        ):
            assert leaked not in names


class TestSessionLifecycle:
    async def test_lifecycle(self):
        """`auto_open` triggers `_open()` on first execute; `_close()` resets `_opened`."""
        tk = _Probe()
        await tk._ensure_open()
        assert tk._opened is True and tk._session is not None
        await tk._close()
        assert tk._opened is False and tk._session is None


class TestFailureFactory:
    def test_failure_factory(self):
        r = _Probe()._failure("q", "probe", "papers", "no_data", "nothing found")
        assert r.status == "no_data" and r.citation is None
        assert "nothing found" in r.error_message

    def test_failure_factory_error_status(self):
        r = _Probe()._failure("q", "probe", "papers", "error", "boom")
        assert r.status == "error"
        assert r.citation is None
        assert r.error_message == "boom"


class TestBuildCitation:
    def test_build_citation_populates_required_fields(self):
        citation = _Probe()._build_citation(
            source_name="World Bank Open Data",
            source_url="https://api.worldbank.org/v2/...",
        )
        assert citation.source_name == "World Bank Open Data"
        assert citation.source_url == "https://api.worldbank.org/v2/..."
        assert citation.access_date
        assert citation.formatted_citation
        assert citation.data_vintage is None


class TestMakeApiRequest:
    async def test_make_api_request_success(self, mock_aiohttp_session):
        """Returns `(payload, None)` on 200."""
        mock_aiohttp_session(responses={"http://x/ok": (200, {"a": 1})})
        payload, err = await _Probe()._make_api_request("http://x/ok")
        assert payload == {"a": 1}
        assert err is None

    async def test_make_api_request_never_raises(self, mock_aiohttp_session):
        payload, err = await _Probe()._make_api_request("http://x/500")
        assert payload is None and err

    async def test_make_api_request_error_returns_tuple(self, mock_aiohttp_session):
        """500/timeout returns `(None, "…")` — does NOT raise."""
        payload, err = await _Probe()._make_api_request("http://x/500")
        assert payload is None
        assert "500" in err

    async def test_make_api_request_rate_limit_retry(self, monkeypatch):
        """429 triggers backoff retry."""

        class _RetryResponse:
            def __init__(self, status, json_body=None, text_body=""):
                self.status = status
                self.request_info = None
                self.history = ()
                self._json_body = json_body
                self._text_body = text_body

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def json(self, content_type=None):
                return self._json_body

            async def text(self):
                return self._text_body

        class _RetrySession:
            def __init__(self):
                self.calls = 0

            def get(self, url, params=None, headers=None):
                self.calls += 1
                if self.calls < 3:
                    return _RetryResponse(429, text_body="rate limited")
                return _RetryResponse(200, json_body={"ok": True})

        tk = _Probe()
        monkeypatch.setattr(tk, "_ensure_open", AsyncMock())
        tk._session = _RetrySession()

        payload, err = await tk._make_api_request("http://x/rate-limited")
        assert payload == {"ok": True}
        assert err is None
        assert tk._session.calls == 3


class TestRunSyncInExecutor:
    async def test_run_sync_in_executor(self):
        def _sync_add(a, b):
            return a + b

        result = await _Probe()._run_sync_in_executor(_sync_add, 2, 3)
        assert result == 5


class TestToolCacheIntegration:
    """`ToolCache` `.get()`/`.set()` round-trip via the mixin's `_cache`."""

    async def test_cache_hit_skips_api(self, monkeypatch):
        tk = _Probe()
        get_mock = AsyncMock(return_value={"cached": True})
        monkeypatch.setattr(tk._cache, "get", get_mock)
        request_mock = AsyncMock()
        monkeypatch.setattr(tk, "_make_api_request", request_mock)

        cached = await tk._cache.get("probe", "do_thing", query="q")

        assert cached == {"cached": True}
        get_mock.assert_awaited_once()
        request_mock.assert_not_called()

    async def test_cache_miss_stores_result(self, monkeypatch):
        tk = _Probe()
        monkeypatch.setattr(tk._cache, "get", AsyncMock(return_value=None))
        set_mock = AsyncMock()
        monkeypatch.setattr(tk._cache, "set", set_mock)

        cached = await tk._cache.get("probe", "do_thing", query="q")
        assert cached is None

        await tk._cache.set("probe", "do_thing", {"value": 1}, query="q")
        set_mock.assert_awaited_once_with(
            "probe", "do_thing", {"value": 1}, query="q"
        )
