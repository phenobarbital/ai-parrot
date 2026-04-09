"""Unit tests for ScrapingInfoHandler reference metadata endpoints."""
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.handlers.scraping.info import (
    ScrapingInfoHandler,
    _build_action_catalog,
)
from parrot.tools.scraping.models import ACTION_MAP
from parrot.tools.scraping.toolkit_models import DriverConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def info_handler():
    """Create a ScrapingInfoHandler instance."""
    return ScrapingInfoHandler()


@pytest.fixture
def mock_request():
    """Create a mock aiohttp request."""
    return make_mocked_request("GET", "/api/v1/scraping/info/actions")


# ---------------------------------------------------------------------------
# Helper to parse JSON response
# ---------------------------------------------------------------------------

async def _parse_response(handler_method, request) -> dict:
    """Call a handler method and parse the JSON response body."""
    resp = await handler_method(request)
    return json.loads(resp.body)


# ---------------------------------------------------------------------------
# Unit tests: _build_action_catalog helper
# ---------------------------------------------------------------------------

class TestBuildActionCatalog:
    """Tests for the _build_action_catalog helper function."""

    def test_returns_all_actions(self):
        """Catalog contains one entry per ACTION_MAP key."""
        catalog = _build_action_catalog()
        assert len(catalog) == len(ACTION_MAP)

    def test_action_entry_keys(self):
        """Each entry has name, description, fields, required."""
        catalog = _build_action_catalog()
        for entry in catalog:
            assert "name" in entry
            assert "description" in entry
            assert "fields" in entry
            assert "required" in entry

    def test_action_names_match(self):
        """Catalog names match ACTION_MAP keys."""
        catalog = _build_action_catalog()
        catalog_names = {entry["name"] for entry in catalog}
        assert catalog_names == set(ACTION_MAP.keys())

    def test_fields_are_dicts(self):
        """Fields are JSON Schema property dicts."""
        catalog = _build_action_catalog()
        for entry in catalog:
            assert isinstance(entry["fields"], dict)

    def test_required_are_lists(self):
        """Required is a list of field names."""
        catalog = _build_action_catalog()
        for entry in catalog:
            assert isinstance(entry["required"], list)


# ---------------------------------------------------------------------------
# Handler method tests (direct invocation)
# ---------------------------------------------------------------------------

class TestGetActions:
    """Tests for get_actions() handler method."""

    @pytest.mark.asyncio
    async def test_returns_200(self, info_handler, mock_request):
        """Handler returns 200 OK."""
        resp = await info_handler.get_actions(mock_request)
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_returns_all_actions(self, info_handler, mock_request):
        """Response contains all ACTION_MAP entries."""
        data = await _parse_response(info_handler.get_actions, mock_request)
        assert "actions" in data
        assert len(data["actions"]) == len(ACTION_MAP)

    @pytest.mark.asyncio
    async def test_action_has_schema_fields(self, info_handler, mock_request):
        """Each action entry includes name, description, fields, required."""
        data = await _parse_response(info_handler.get_actions, mock_request)
        for action in data["actions"]:
            assert "name" in action
            assert "description" in action
            assert "fields" in action
            assert "required" in action

    @pytest.mark.asyncio
    async def test_navigate_action_present(self, info_handler, mock_request):
        """The 'navigate' action is present."""
        data = await _parse_response(info_handler.get_actions, mock_request)
        names = [a["name"] for a in data["actions"]]
        assert "navigate" in names

    @pytest.mark.asyncio
    async def test_click_action_present(self, info_handler, mock_request):
        """The 'click' action is present."""
        data = await _parse_response(info_handler.get_actions, mock_request)
        names = [a["name"] for a in data["actions"]]
        assert "click" in names

    @pytest.mark.asyncio
    async def test_all_action_map_entries_present(self, info_handler, mock_request):
        """Every key in ACTION_MAP is represented."""
        data = await _parse_response(info_handler.get_actions, mock_request)
        names = {a["name"] for a in data["actions"]}
        for key in ACTION_MAP:
            assert key in names


class TestGetDrivers:
    """Tests for get_drivers() handler method."""

    @pytest.mark.asyncio
    async def test_returns_200(self, info_handler, mock_request):
        """Handler returns 200 OK."""
        resp = await info_handler.get_drivers(mock_request)
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_returns_selenium(self, info_handler, mock_request):
        """Selenium driver type is listed with browsers."""
        data = await _parse_response(info_handler.get_drivers, mock_request)
        assert "drivers" in data
        driver_names = [d["name"] for d in data["drivers"]]
        assert "selenium" in driver_names
        selenium = next(d for d in data["drivers"] if d["name"] == "selenium")
        assert "chrome" in selenium["browsers"]
        assert "firefox" in selenium["browsers"]

    @pytest.mark.asyncio
    async def test_returns_playwright(self, info_handler, mock_request):
        """Playwright driver type is listed with browsers."""
        data = await _parse_response(info_handler.get_drivers, mock_request)
        driver_names = [d["name"] for d in data["drivers"]]
        assert "playwright" in driver_names
        playwright = next(d for d in data["drivers"] if d["name"] == "playwright")
        assert "chromium" in playwright["browsers"]
        assert "webkit" in playwright["browsers"]

    @pytest.mark.asyncio
    async def test_driver_entry_structure(self, info_handler, mock_request):
        """Each driver entry has name and browsers list."""
        data = await _parse_response(info_handler.get_drivers, mock_request)
        for driver in data["drivers"]:
            assert "name" in driver
            assert "browsers" in driver
            assert isinstance(driver["browsers"], list)
            assert len(driver["browsers"]) > 0


class TestGetConfigSchema:
    """Tests for get_config_schema() handler method."""

    @pytest.mark.asyncio
    async def test_returns_200(self, info_handler, mock_request):
        """Handler returns 200 OK."""
        resp = await info_handler.get_config_schema(mock_request)
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_returns_valid_json_schema(self, info_handler, mock_request):
        """Response contains a valid JSON schema with properties."""
        data = await _parse_response(info_handler.get_config_schema, mock_request)
        assert "schema" in data
        schema = data["schema"]
        assert "properties" in schema
        assert "driver_type" in schema["properties"]
        assert "browser" in schema["properties"]
        assert "headless" in schema["properties"]

    @pytest.mark.asyncio
    async def test_schema_matches_driver_config(self, info_handler, mock_request):
        """Schema properties match DriverConfig.model_json_schema()."""
        data = await _parse_response(info_handler.get_config_schema, mock_request)
        expected = DriverConfig.model_json_schema()
        assert set(data["schema"]["properties"].keys()) == set(expected["properties"].keys())

    @pytest.mark.asyncio
    async def test_schema_has_title(self, info_handler, mock_request):
        """Schema has a title field (from Pydantic)."""
        data = await _parse_response(info_handler.get_config_schema, mock_request)
        assert "title" in data["schema"]

    @pytest.mark.asyncio
    async def test_schema_includes_defaults(self, info_handler, mock_request):
        """Schema includes default values for fields."""
        data = await _parse_response(info_handler.get_config_schema, mock_request)
        props = data["schema"]["properties"]
        assert props["headless"]["default"] is True
        assert props["default_timeout"]["default"] == 10


class TestGetStrategies:
    """Tests for get_strategies() handler method."""

    @pytest.mark.asyncio
    async def test_returns_200(self, info_handler, mock_request):
        """Handler returns 200 OK."""
        resp = await info_handler.get_strategies(mock_request)
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_returns_bfs_and_dfs(self, info_handler, mock_request):
        """Both bfs and dfs strategies are listed."""
        data = await _parse_response(info_handler.get_strategies, mock_request)
        assert "strategies" in data
        names = [s["name"] for s in data["strategies"]]
        assert "bfs" in names
        assert "dfs" in names

    @pytest.mark.asyncio
    async def test_strategy_has_description(self, info_handler, mock_request):
        """Each strategy has a non-empty description."""
        data = await _parse_response(info_handler.get_strategies, mock_request)
        for strategy in data["strategies"]:
            assert "name" in strategy
            assert "description" in strategy
            assert len(strategy["description"]) > 0

    @pytest.mark.asyncio
    async def test_bfs_description_content(self, info_handler, mock_request):
        """BFS description mentions breadth-first."""
        data = await _parse_response(info_handler.get_strategies, mock_request)
        bfs = next(s for s in data["strategies"] if s["name"] == "bfs")
        assert "breadth" in bfs["description"].lower()

    @pytest.mark.asyncio
    async def test_exactly_two_strategies(self, info_handler, mock_request):
        """Exactly two strategies (bfs, dfs) are returned."""
        data = await _parse_response(info_handler.get_strategies, mock_request)
        assert len(data["strategies"]) == 2


class TestSetup:
    """Tests for ScrapingInfoHandler.setup() route registration."""

    def test_registers_four_routes(self, info_handler):
        """setup() registers all 4 info routes."""
        app = web.Application()
        info_handler.setup(app)
        # Collect all registered route paths
        routes = set()
        for resource in app.router.resources():
            info = resource.get_info()
            path = info.get("formatter") or info.get("path", "")
            if path:
                routes.add(path)
        assert "/api/v1/scraping/info/actions" in routes
        assert "/api/v1/scraping/info/drivers" in routes
        assert "/api/v1/scraping/info/config" in routes
        assert "/api/v1/scraping/info/strategies" in routes

    def test_routes_are_get_only(self, info_handler):
        """All registered routes are GET method only."""
        app = web.Application()
        info_handler.setup(app)
        for route in app.router.routes():
            assert route.method == "GET"

    def test_four_resources_registered(self, info_handler):
        """Exactly 4 resources are registered."""
        app = web.Application()
        info_handler.setup(app)
        resources = list(app.router.resources())
        assert len(resources) == 4


class TestImports:
    """Tests for module imports."""

    def test_import_handler(self):
        """ScrapingInfoHandler can be imported from the module."""
        from parrot.handlers.scraping.info import ScrapingInfoHandler
        assert ScrapingInfoHandler is not None

    def test_import_from_module(self):
        """Module attributes are accessible."""
        import parrot.handlers.scraping.info
        assert hasattr(parrot.handlers.scraping.info, "ScrapingInfoHandler")
        assert hasattr(parrot.handlers.scraping.info, "_build_action_catalog")
        assert hasattr(parrot.handlers.scraping.info, "_DRIVER_TYPES")
        assert hasattr(parrot.handlers.scraping.info, "_STRATEGIES")
