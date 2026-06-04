"""Integration tests for FEAT-225 Module 7 — DatasetFilterHandler HTTP endpoints.

Tests cover:
- GET /schema → filter schema list.
- GET /values/{name} → distinct values list.
- POST /filters → apply_filters result (applied/skipped).
- Error cases: unknown filter name.
- DatasetFilterEnvelope.forward() sends request to apply_filters.
"""
import pytest
import pandas as pd
from aiohttp import web

from parrot.tools.dataset_manager.filtering import FilterDefinition
from parrot.tools.dataset_manager.tool import DatasetEntry, DatasetManager
from parrot.handlers.dataset_filter_handler import DatasetFilterEnvelope, DatasetFilterHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(df: pd.DataFrame) -> DatasetEntry:
    return DatasetEntry(name="test", df=df)


def _make_manager() -> DatasetManager:
    """Create a DatasetManager with stores/sites/weather fixtures."""
    dm = DatasetManager()
    dm._datasets["stores"] = _entry(pd.DataFrame({
        "region": ["North", "South", "North"],
        "revenue": [100, 200, 150],
    }))
    dm._datasets["sites"] = _entry(pd.DataFrame({
        "region": ["North", "East"],
    }))
    dm._datasets["weather"] = _entry(pd.DataFrame({
        "temp": [20.0, 22.0],
    }))
    dm.define_filters([
        FilterDefinition(
            name="region",
            columns=["region"],
            kind="categorical",
            ops=["eq", "in"],
            required=False,
            label="Region",
        ),
    ])
    return dm


# ---------------------------------------------------------------------------
# App fixture using functional routes
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_with_filter_handler() -> web.Application:
    """Create an aiohttp app with filter handler functions mounted."""
    _dm = _make_manager()
    handler = _TestHandler(_dm)

    app = web.Application()
    app.router.add_get("/api/v1/filters/{agent_id}/schema", handler.handle_schema)
    app.router.add_get("/api/v1/filters/{agent_id}/values/{name}", handler.handle_values)
    app.router.add_post("/api/v1/filters/{agent_id}", handler.handle_apply)
    return app


class _TestHandler:
    """Test handler wrapping a DatasetManager instance."""

    def __init__(self, dm: DatasetManager) -> None:
        self._dm = dm
        # Instantiate base handler with a dummy request for helper access
        self._base_cls = DatasetFilterHandler

    async def handle_schema(self, request: web.Request) -> web.Response:
        """GET schema endpoint."""
        handler = self._base_cls.__new__(self._base_cls)
        handler.request = request
        handler.logger = __import__("logging").getLogger(__name__)
        return await handler._handle_schema(self._dm)

    async def handle_values(self, request: web.Request) -> web.Response:
        """GET values endpoint."""
        handler = self._base_cls.__new__(self._base_cls)
        handler.request = request
        handler.logger = __import__("logging").getLogger(__name__)
        name = request.match_info.get("name", "")
        return await handler._handle_values(self._dm, name)

    async def handle_apply(self, request: web.Request) -> web.Response:
        """POST apply endpoint."""
        import json as _json

        handler = self._base_cls.__new__(self._base_cls)
        handler.request = request
        handler.logger = __import__("logging").getLogger(__name__)

        try:
            body = await request.json()
        except Exception:
            return web.Response(
                text=_json.dumps({"error": "Invalid JSON"}),
                status=400,
                content_type="application/json",
            )

        filter_request = body.get("request", {})
        persist = bool(body.get("persist", False))

        try:
            result = await self._dm.apply_filters(filter_request, persist=persist)
        except KeyError as exc:
            return web.Response(
                text=_json.dumps({"error": str(exc)}),
                status=422,
                content_type="application/json",
            )
        except ValueError as exc:
            return web.Response(
                text=_json.dumps({"error": str(exc)}),
                status=422,
                content_type="application/json",
            )
        return await handler._json_response(result)


# ---------------------------------------------------------------------------
# GET /schema tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_schema(aiohttp_client, app_with_filter_handler) -> None:
    """GET /schema returns the filter catalog."""
    client = await aiohttp_client(app_with_filter_handler)
    resp = await client.get("/api/v1/filters/my-agent/schema")
    assert resp.status == 200
    body = await resp.json()
    assert isinstance(body, list)
    assert any(e["name"] == "region" for e in body)


@pytest.mark.asyncio
async def test_get_schema_entry_has_required_fields(aiohttp_client, app_with_filter_handler) -> None:
    """Schema entries contain name, kind, ops, datasets, required."""
    client = await aiohttp_client(app_with_filter_handler)
    resp = await client.get("/api/v1/filters/my-agent/schema")
    body = await resp.json()
    region = next(e for e in body if e["name"] == "region")
    assert "kind" in region
    assert "ops" in region
    assert "datasets" in region
    assert "required" in region


@pytest.mark.asyncio
async def test_get_schema_applicable_datasets(aiohttp_client, app_with_filter_handler) -> None:
    """Schema correctly identifies which datasets have the column."""
    client = await aiohttp_client(app_with_filter_handler)
    resp = await client.get("/api/v1/filters/my-agent/schema")
    body = await resp.json()
    region = next(e for e in body if e["name"] == "region")
    assert "stores" in region["datasets"]
    assert "sites" in region["datasets"]
    assert "weather" not in region["datasets"]


# ---------------------------------------------------------------------------
# GET /values/{name} tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_values(aiohttp_client, app_with_filter_handler) -> None:
    """GET /values/region returns distinct region values."""
    client = await aiohttp_client(app_with_filter_handler)
    resp = await client.get("/api/v1/filters/my-agent/values/region")
    assert resp.status == 200
    body = await resp.json()
    assert "values" in body
    assert "North" in body["values"]


@pytest.mark.asyncio
async def test_get_values_unknown_filter(aiohttp_client, app_with_filter_handler) -> None:
    """GET /values for unknown filter name returns 404."""
    client = await aiohttp_client(app_with_filter_handler)
    resp = await client.get("/api/v1/filters/my-agent/values/ghost_filter")
    assert resp.status == 404


# ---------------------------------------------------------------------------
# POST /filters tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_apply(aiohttp_client, app_with_filter_handler) -> None:
    """POST apply returns FilterResult with applied/skipped."""
    client = await aiohttp_client(app_with_filter_handler)
    resp = await client.post(
        "/api/v1/filters/my-agent",
        json={"request": {"region": ["North"]}},
    )
    assert resp.status == 200
    body = await resp.json()
    assert "applied" in body
    assert "skipped" in body
    assert "stores" in body["applied"]
    assert "weather" in body["skipped"]


@pytest.mark.asyncio
async def test_post_apply_scalar(aiohttp_client, app_with_filter_handler) -> None:
    """POST with scalar value applies eq filter."""
    client = await aiohttp_client(app_with_filter_handler)
    resp = await client.post(
        "/api/v1/filters/my-agent",
        json={"request": {"region": "North"}},
    )
    assert resp.status == 200
    body = await resp.json()
    assert "stores" in body["applied"]


@pytest.mark.asyncio
async def test_post_apply_unknown_filter(aiohttp_client, app_with_filter_handler) -> None:
    """POST with unknown filter name returns 422."""
    client = await aiohttp_client(app_with_filter_handler)
    resp = await client.post(
        "/api/v1/filters/my-agent",
        json={"request": {"ghost_filter": "North"}},
    )
    assert resp.status == 422


# ---------------------------------------------------------------------------
# DatasetFilterEnvelope tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_envelope_forward() -> None:
    """DatasetFilterEnvelope.forward() calls apply_filters on the manager."""
    dm = _make_manager()
    envelope = DatasetFilterEnvelope(
        request={"region": ["North"]},
        agent_id="test-agent",
        persist=False,
    )
    result = await envelope.forward(dm)
    assert "stores" in result.applied
    assert "sites" in result.applied
    assert "weather" in result.skipped


@pytest.mark.asyncio
async def test_envelope_persist() -> None:
    """DatasetFilterEnvelope with persist=True registers filtered datasets."""
    dm = _make_manager()
    keys_before = set(dm._datasets.keys())
    envelope = DatasetFilterEnvelope(
        request={"region": "North"},
        agent_id="test-agent",
        persist=True,
    )
    await envelope.forward(dm)
    assert len(dm._datasets) > len(keys_before)
