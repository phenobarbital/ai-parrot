"""Unit tests for `OpenDataToolkit` OECD SDMX methods (FEAT-426 TASK-2237).

`sdmx1` is not installed in the base test environment (spec goal G6 —
fixtures only, no live network in CI), so these tests exercise
`OpenDataToolkit` against a fake `sdmx` module patched onto
`parrot_tools.research.open_data.sdmx`. The fake `Client` records
construction args, call order, and the data-query key/params so the
tests can assert on the real contract (SDMX 3.0 source, DSD-before-data,
bounded queries) without a real SDMX server.
"""
import types

import pytest
from parrot_tools.research import open_data as open_data_module
from parrot_tools.research.open_data import OpenDataToolkit


def _make_fake_sdmx_module(catalog_flows: dict | None = None, observations: list | None = None):
    """Build a fake `sdmx` module plus the list of constructed clients."""
    created: list = []
    catalog_flows = catalog_flows or {}
    observations = observations if observations is not None else []

    class _FakeDataMessage:
        def __init__(self, obs):
            self.observations = obs

    class _FakeFlowMessage:
        def __init__(self, dataflow_dict):
            self.dataflow = dataflow_dict

    class _RecordingClient:
        def __init__(self, source_id):
            self.source_id = source_id
            self.call_order = []
            self.key = None
            self.params = None
            created.append(self)

        def dataflow(self, dataset_id=None):
            self.call_order.append("dataflow")
            if dataset_id is None:
                return _FakeFlowMessage(catalog_flows)
            flow = catalog_flows.get(dataset_id, types.SimpleNamespace(name=dataset_id))
            return _FakeFlowMessage({dataset_id: flow})

        def data(self, dataset_id, key=None, params=None):
            self.call_order.append("data")
            self.key = key
            self.params = params
            return _FakeDataMessage(observations)

    fake_module = types.SimpleNamespace(Client=_RecordingClient)
    return fake_module, created


@pytest.fixture
def mock_sdmx_catalog(monkeypatch):
    flows = {
        "DSD_FUA_CLIM@DF_TEMPERATURES": types.SimpleNamespace(
            name="Urban Areas Climate Temperatures"
        ),
        "DSD_X@DF_Y": types.SimpleNamespace(name="Some Other Dataflow"),
    }
    fake_module, created = _make_fake_sdmx_module(catalog_flows=flows)
    monkeypatch.setattr(open_data_module, "sdmx", fake_module)
    return created


@pytest.fixture
def capture_sdmx_client(monkeypatch):
    flows = {"X": types.SimpleNamespace(name="X")}
    fake_module, created = _make_fake_sdmx_module(catalog_flows=flows)
    monkeypatch.setattr(open_data_module, "sdmx", fake_module)

    class _Proxy:
        @property
        def source_id(self):
            return created[-1].source_id if created else None

    return _Proxy()


@pytest.fixture
def mock_sdmx_series(monkeypatch):
    fake_module, created = _make_fake_sdmx_module(
        observations=[
            {
                "country": "FRA", "country_name": "France", "period": "2020",
                "value": 14.2, "series_name": "Average Temperature",
            },
            {
                "country": "FRA", "country_name": "France", "period": "2021",
                "value": 14.6, "series_name": "Average Temperature",
            },
        ],
    )
    monkeypatch.setattr(open_data_module, "sdmx", fake_module)
    return created


@pytest.fixture
def call_order(mock_sdmx_series):
    class _Proxy:
        def index(self, value):
            return mock_sdmx_series[-1].call_order.index(value)

    return _Proxy()


@pytest.fixture
def capture_sdmx_query(monkeypatch):
    fake_module, created = _make_fake_sdmx_module(
        observations=[{"country": "FRA", "period": "2020", "value": 1.0}]
    )
    monkeypatch.setattr(open_data_module, "sdmx", fake_module)

    class _Proxy:
        @property
        def key(self):
            return created[-1].key if created else None

        @property
        def params(self):
            return created[-1].params if created else None

    return _Proxy()


@pytest.fixture
def mock_sdmx_empty(monkeypatch):
    fake_module, created = _make_fake_sdmx_module(catalog_flows={}, observations=[])
    monkeypatch.setattr(open_data_module, "sdmx", fake_module)
    return created


class TestOECD:
    async def test_search_lists_dataflows(self, mock_sdmx_catalog):
        r = await OpenDataToolkit().search_oecd_data("temperature")
        assert r.status == "success" and r.result_type == "datasets"
        assert r.datasets and r.datasets[0].source == "oecd"

    async def test_uses_sdmx3_source(self, capture_sdmx_client):
        await OpenDataToolkit().search_oecd_data("x")
        assert capture_sdmx_client.source_id == "OECD3"

    async def test_get_indicator_fetches_dsd_first(self, mock_sdmx_series, call_order):
        await OpenDataToolkit().get_oecd_indicator("DSD_X@DF_Y", "FRA")
        assert call_order.index("dataflow") < call_order.index("data")

    async def test_data_query_is_bounded(self, capture_sdmx_query):
        await OpenDataToolkit().get_oecd_indicator("DSD_X@DF_Y", "FRA")
        assert capture_sdmx_query.key or capture_sdmx_query.params

    async def test_unknown_flow_is_no_data(self, mock_sdmx_empty):
        r = await OpenDataToolkit().get_oecd_indicator("NOPE", "FRA")
        assert r.status == "no_data"

    async def test_missing_library_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(open_data_module, "sdmx", None)
        r = await OpenDataToolkit().search_oecd_data("x")
        assert r.status == "error" and "ai-parrot-tools[research]" in r.error_message

    async def test_get_indicator_returns_indicators(self, mock_sdmx_series):
        r = await OpenDataToolkit().get_oecd_indicator("DSD_X@DF_Y", "FRA")
        assert r.status == "success" and r.result_type == "indicators"
        assert r.indicators and r.indicators[0].country == "FRA"
        assert r.citation.source_name == "OECD SDMX"
