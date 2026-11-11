"""HTTP coverage for Redis-backed dashboard handlers (TASK-5507)."""

from __future__ import annotations

import pytest
from aiohttp import web

from parrot.handlers import dashboard_store
from parrot.handlers.dashboard_handler import DashboardHandler, DashboardTabHandler, _ensure_dashboard_indexes
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def client(aiohttp_client, monkeypatch: pytest.MonkeyPatch):
    """Provide dashboard routes backed by an isolated Redis namespace."""
    monkeypatch.delenv("DASHBOARDS_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    async with redis_test_settings(monkeypatch):
        app = web.Application()
        app.router.add_view("/api/v1/dashboards", DashboardHandler)
        app.router.add_view("/api/v1/dashboards/{dashboard_id}", DashboardHandler)
        app.router.add_view("/api/v1/dashboards/{dashboard_id}/tabs", DashboardTabHandler)
        app.router.add_view("/api/v1/dashboards/{dashboard_id}/tabs/{tab_id}", DashboardTabHandler)
        yield await aiohttp_client(app)


async def test_dashboard_crud_redis(client) -> None:
    """Dashboard routes preserve create, read, update, list, and delete behavior."""
    created = await client.post(
        "/api/v1/dashboards",
        json={"dashboard_id": "d1", "title": "Sales", "module_id": "reports"},
    )
    assert created.status == 201
    assert await created.json() == {"message": "Dashboard created", "dashboard_id": "d1"}

    retrieved = await client.get("/api/v1/dashboards/d1")
    assert retrieved.status == 200
    assert (await retrieved.json())["tabs"] == []

    patched = await client.patch("/api/v1/dashboards/d1", json={"title": "Revenue"})
    assert patched.status == 200
    assert (await patched.json())["message"] == "Dashboard 'd1' patched"

    listed = await client.get("/api/v1/dashboards?module_id=reports")
    assert listed.status == 200
    assert (await listed.json())["dashboards"][0]["title"] == "Revenue"

    deleted = await client.delete("/api/v1/dashboards/d1")
    assert deleted.status == 200
    assert (await client.get("/api/v1/dashboards/d1")).status == 404


async def test_dashboard_duplicate_create_409(client) -> None:
    """A duplicate dashboard identifier returns the documented conflict response."""
    payload = {"dashboard_id": "d1", "title": "Sales"}
    assert (await client.post("/api/v1/dashboards", json=payload)).status == 201
    duplicate = await client.post("/api/v1/dashboards", json=payload)
    assert duplicate.status == 409
    assert await duplicate.json() == {"message": "Dashboard 'd1' already exists"}


async def test_tab_crud_and_order(client) -> None:
    """Tabs use store ordering and return conflicts without replacing the original tab."""
    assert (
        await client.post("/api/v1/dashboards", json={"dashboard_id": "d1", "title": "Sales"})
    ).status == 201
    assert (
        await client.post(
            "/api/v1/dashboards/d1/tabs",
            json={"tab_id": "later", "title": "Later", "index": 2},
        )
    ).status == 201
    assert (
        await client.post(
            "/api/v1/dashboards/d1/tabs",
            json={"tab_id": "first", "title": "First", "index": 1},
        )
    ).status == 201

    listed = await client.get("/api/v1/dashboards/d1/tabs")
    assert [tab["tab_id"] for tab in (await listed.json())["tabs"]] == ["first", "later"]

    duplicate = await client.post(
        "/api/v1/dashboards/d1/tabs",
        json={"tab_id": "first", "title": "Replacement"},
    )
    assert duplicate.status == 409
    assert await duplicate.json() == {"message": "Tab 'first' already exists"}

    updated = await client.put(
        "/api/v1/dashboards/d1/tabs/first",
        json={"title": "Updated", "index": 0},
    )
    assert updated.status == 200
    assert (await client.delete("/api/v1/dashboards/d1/tabs/first")).status == 200
    assert (await client.get("/api/v1/dashboards/d1/tabs/first")).status == 404


async def test_ensure_indexes_no_documentdb(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis startup delegates to its no-op index hook without constructing DocumentDB."""
    monkeypatch.delenv("DASHBOARDS_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)

    class ForbiddenDocumentDb:
        """Fail if Redis startup reaches the DocumentDB implementation."""

        def __init__(self) -> None:
            raise AssertionError("DocumentDB was contacted")

    monkeypatch.setattr(dashboard_store, "DocumentDb", ForbiddenDocumentDb)
    await _ensure_dashboard_indexes(web.Application())
