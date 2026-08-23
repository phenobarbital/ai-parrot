"""Unit tests for `AcademicResearchToolkit.search_semantic_scholar` (FEAT-426 TASK-2240)."""
import pytest
from parrot_tools.research import academic as academic_module
from parrot_tools.research.academic import _S2_SEARCH_URL, AcademicResearchToolkit


@pytest.fixture
def capture_params(monkeypatch):
    """Capture the `params` dict passed to `_make_api_request`."""
    captured: dict = {}

    async def _fake_request(self, url, params=None, headers=None):
        captured.update(params or {})
        return {"data": []}, None

    monkeypatch.setattr(
        academic_module.AcademicResearchToolkit, "_make_api_request", _fake_request
    )
    return captured


@pytest.fixture
def capture_headers(monkeypatch):
    """Capture the `headers` dict passed to `_make_api_request`."""
    captured: dict = {}

    async def _fake_request(self, url, params=None, headers=None):
        captured.update(headers or {})
        return {"data": []}, None

    monkeypatch.setattr(
        academic_module.AcademicResearchToolkit, "_make_api_request", _fake_request
    )
    return captured


class TestSemanticScholar:
    async def test_requests_fields(self, capture_params):
        await AcademicResearchToolkit().search_semantic_scholar("graph nn")
        assert capture_params.get("fields")

    async def test_hyphens_replaced(self, capture_params):
        await AcademicResearchToolkit().search_semantic_scholar(
            "graph-neural-network"
        )
        assert "-" not in capture_params["query"]

    async def test_api_key_header_name(self, monkeypatch, capture_headers):
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "k")
        await AcademicResearchToolkit().search_semantic_scholar("x")
        assert capture_headers.get("x-api-key") == "k"
        assert "Authorization" not in capture_headers

    async def test_maps_papers(self, mock_aiohttp_session, load_fixture):
        body = load_fixture("semantic_scholar_search.json")
        mock_aiohttp_session(responses={_S2_SEARCH_URL: (200, body)})

        r = await AcademicResearchToolkit().search_semantic_scholar("x")
        assert r.papers[0].source == "semantic_scholar" and r.citation
        assert r.papers[0].doi == "10.1000/gnn-molecular"
        assert r.papers[0].open_access is True

    async def test_limit_clamped_to_100(self, capture_params):
        await AcademicResearchToolkit().search_semantic_scholar(
            "x", max_results=500
        )
        assert capture_params["limit"] <= 100
