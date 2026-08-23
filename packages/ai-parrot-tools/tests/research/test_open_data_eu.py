"""Unit tests for `OpenDataToolkit.search_eu_open_data` (FEAT-426 TASK-2236)."""
import pytest
from parrot_tools.research import open_data as open_data_module
from parrot_tools.research.open_data import EU_SEARCH_URL, OpenDataToolkit


@pytest.fixture
def mock_aiohttp_session_de_only(mock_aiohttp_session):
    """Configure the shared aiohttp stub with a title lacking an 'en' key."""
    body = {
        "result": {
            "count": 1,
            "results": [
                {
                    "id": "energieverbrauch",
                    "title": {"de": "Energieverbrauch Datensatz"},
                    "description": {"de": "Beschreibung des Datensatzes"},
                    "publisher": {"name": {"de": "Umweltbundesamt"}},
                    "distributions": [],
                }
            ],
        }
    }
    mock_aiohttp_session(responses={EU_SEARCH_URL: (200, body)})
    return mock_aiohttp_session


@pytest.fixture
def mock_aiohttp_session_500(mock_aiohttp_session):
    mock_aiohttp_session(responses={EU_SEARCH_URL: (500, None)})
    return mock_aiohttp_session


@pytest.fixture
def mock_aiohttp_session_empty(mock_aiohttp_session):
    mock_aiohttp_session(
        responses={EU_SEARCH_URL: (200, {"result": {"count": 0, "results": []}})}
    )
    return mock_aiohttp_session


@pytest.fixture
def capture_params(monkeypatch):
    """Capture the `params` dict passed to `_make_api_request`."""
    captured: dict = {}

    async def _fake_request(self, url, params=None, headers=None):
        captured.update(params or {})
        return {"result": {"count": 0, "results": []}}, None

    monkeypatch.setattr(
        open_data_module.OpenDataToolkit, "_make_api_request", _fake_request
    )
    return captured


class TestEUOpenData:
    async def test_search_maps_datasets(self, mock_aiohttp_session, load_fixture):
        body = load_fixture("eu_open_data_search.json")
        mock_aiohttp_session(responses={EU_SEARCH_URL: (200, body)})

        r = await OpenDataToolkit().search_eu_open_data("renewable energy")
        assert r.status == "success" and r.result_type == "datasets"
        assert r.datasets and r.datasets[0].source == "eu_open_data"
        assert r.citation.source_name == "EU Open Data Portal"

    async def test_multilingual_fallback(self, mock_aiohttp_session_de_only):
        """title has only a 'de' key — must not yield an empty title."""
        r = await OpenDataToolkit().search_eu_open_data("energie")
        assert r.datasets[0].title

    async def test_limit_clamped_to_1000(self, capture_params):
        await OpenDataToolkit().search_eu_open_data("x", max_results=5000)
        assert capture_params["limit"] <= 1000

    async def test_transport_error_is_data(self, mock_aiohttp_session_500):
        r = await OpenDataToolkit().search_eu_open_data("x")
        assert r.status == "error" and r.error_message

    async def test_empty_is_no_data(self, mock_aiohttp_session_empty):
        r = await OpenDataToolkit().search_eu_open_data("zzzz")
        assert r.status == "no_data"
