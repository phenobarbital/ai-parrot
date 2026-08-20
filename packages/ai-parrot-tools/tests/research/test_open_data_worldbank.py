"""Unit tests for `OpenDataToolkit` World Bank methods (FEAT-426 TASK-2235)."""
import types

import pytest
from parrot_tools.research import open_data as open_data_module
from parrot_tools.research.open_data import OpenDataToolkit


class _FakeSeriesInfo:
    """Stand-in for a `wbgapi.series.info()` metadata row."""

    def __init__(self, id_: str, value: str):
        self.id = id_
        self.value = value


def _make_fake_wb(rows: list, matches: list | None = None):
    matches = matches if matches is not None else [
        _FakeSeriesInfo("NY.GDP.MKTP.KD.ZG", "GDP growth (annual %)")
    ]
    return types.SimpleNamespace(
        data=types.SimpleNamespace(
            fetch=lambda series, economy=None, **kw: iter(rows)
        ),
        series=types.SimpleNamespace(info=lambda q=None: matches),
    )


@pytest.fixture
def mock_wbgapi(monkeypatch, load_fixture):
    rows = load_fixture("world_bank_indicator.json")
    fake_wb = _make_fake_wb(rows)
    monkeypatch.setattr(open_data_module, "wb", fake_wb)
    return fake_wb


@pytest.fixture
def mock_wbgapi_empty(monkeypatch):
    fake_wb = _make_fake_wb(rows=[], matches=[])
    monkeypatch.setattr(open_data_module, "wb", fake_wb)
    return fake_wb


@pytest.fixture
def mock_wbgapi_gaps(monkeypatch, load_fixture):
    rows = load_fixture("world_bank_indicator.json")
    fake_wb = _make_fake_wb(rows)
    monkeypatch.setattr(open_data_module, "wb", fake_wb)
    return fake_wb


class TestWorldBank:
    async def test_get_indicator_from_fixture(self, mock_wbgapi):
        r = await OpenDataToolkit().get_world_bank_indicator(
            "NY.GDP.MKTP.KD.ZG", "BRA"
        )
        assert r.status == "success" and r.result_type == "indicators"
        assert r.indicators and r.indicators[0].country == "BRA"
        assert r.citation.source_name == "World Bank Open Data"
        assert r.citation.source_url and r.citation.access_date

    async def test_search_returns_indicators(self, mock_wbgapi):
        r = await OpenDataToolkit().search_world_bank("GDP growth", country="BRA")
        assert r.status in {"success", "no_data"}

    async def test_no_results_is_no_data(self, mock_wbgapi_empty):
        r = await OpenDataToolkit().get_world_bank_indicator("BOGUS.CODE", "BRA")
        assert r.status == "no_data" and r.citation is None

    async def test_missing_library_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(open_data_module, "wb", None)
        r = await OpenDataToolkit().get_world_bank_indicator("X", "BRA")
        assert r.status == "error" and "ai-parrot-tools[research]" in r.error_message

    async def test_missing_observations_kept_as_none(self, mock_wbgapi_gaps):
        r = await OpenDataToolkit().get_world_bank_indicator(
            "NY.GDP.MKTP.KD.ZG", "BRA"
        )
        assert any(i.value is None for i in r.indicators)

    async def test_search_with_no_metadata_matches_is_no_data(self, mock_wbgapi_empty):
        r = await OpenDataToolkit().search_world_bank("nonsense query xyz")
        assert r.status == "no_data" and r.citation is None

    async def test_wbgapi_only_called_via_executor(self, mock_wbgapi, monkeypatch):
        """Sanity check: the sync library call happens off the event loop."""
        tk = OpenDataToolkit()
        called = {}

        original = tk._run_sync_in_executor

        async def _spy(func, *args, **kwargs):
            called["invoked"] = True
            return await original(func, *args, **kwargs)

        monkeypatch.setattr(tk, "_run_sync_in_executor", _spy)
        await tk.get_world_bank_indicator("NY.GDP.MKTP.KD.ZG", "BRA")
        assert called.get("invoked") is True
