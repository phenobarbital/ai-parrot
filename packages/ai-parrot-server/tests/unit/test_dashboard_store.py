"""Contract tests for DocumentDB and Redis dashboard persistence."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, ClassVar

import pytest

from parrot.handlers import dashboard_store as ds
from parrot.userstore.testing import redis_test_settings


class _FakeDocumentDb:
    """In-memory async DocumentDB stand-in for dashboard store contract tests."""

    docs: ClassVar[dict[str, list[dict[str, Any]]]] = {}
    indexes: ClassVar[list[tuple[str, list[Any]]]] = []

    async def __aenter__(self) -> _FakeDocumentDb:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False

    @staticmethod
    def _matches(doc: dict[str, Any], query: dict[str, Any] | None) -> bool:
        return not query or all(doc.get(key) == value for key, value in query.items())

    async def read(
        self, collection: str, query: dict[str, Any] | None, *, sort: list[tuple[str, int]] | None = None
    ) -> list[dict[str, Any]]:
        docs = [deepcopy(doc) for doc in self.docs.get(collection, []) if self._matches(doc, query)]
        for field, direction in reversed(sort or []):
            docs.sort(
                key=lambda doc: (doc.get(field) is None, doc.get(field) or 0),
                reverse=direction < 0,
            )
        return docs

    async def read_one(self, collection: str, query: dict[str, Any], **_kwargs: object) -> dict[str, Any] | None:
        docs = await self.read(collection, query)
        return docs[0] if docs else None

    async def exists(self, collection: str, query: dict[str, Any]) -> bool:
        return any(self._matches(doc, query) for doc in self.docs.get(collection, []))

    async def write(self, collection: str, data: dict[str, Any], **_kwargs: object) -> None:
        self.docs.setdefault(collection, []).append(deepcopy(data))

    async def update(
        self, collection: str, query: dict[str, Any], update_data: dict[str, Any], **_kwargs: object
    ) -> None:
        for doc in self.docs.get(collection, []):
            if self._matches(doc, query):
                doc.update(update_data["$set"])

    async def delete(self, collection: str, query: dict[str, Any], **_kwargs: object) -> None:
        self.docs[collection] = [doc for doc in self.docs.get(collection, []) if not self._matches(doc, query)]

    async def create_indexes(self, collection: str, keys: list[Any]) -> None:
        self.indexes.append((collection, keys))


@pytest.fixture(params=["redis", "documentdb"])
async def store(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Yield each dashboard implementation with isolated backing storage."""
    if request.param == "documentdb":
        _FakeDocumentDb.docs = {}
        _FakeDocumentDb.indexes = []
        monkeypatch.setattr(ds, "DocumentDb", _FakeDocumentDb)
        yield ds.DocumentDbDashboardStore()
    else:
        async with redis_test_settings(monkeypatch):
            yield ds.RedisDashboardStore()


async def test_dashboard_store_contract(store: ds.DashboardStore) -> None:
    """Both stores provide dashboard CRUD, filters, ordering, and no internal identifiers."""
    assert await store.create_dashboard({"dashboard_id": "d1", "module_id": "m1", "user_id": "u1", "created_at": "2"})
    assert await store.create_dashboard(
        {"dashboard_id": "d2", "module_id": "m2", "user_id": "u1", "created_at": "1", "_id": "internal"}
    )
    assert await store.dashboard_exists("d1") is True
    assert await store.get_dashboard("d2") == {
        "dashboard_id": "d2",
        "module_id": "m2",
        "user_id": "u1",
        "created_at": "1",
    }
    assert [doc["dashboard_id"] for doc in await store.list_dashboards(user_id="u1")] == ["d1", "d2"]
    assert [doc["dashboard_id"] for doc in await store.list_dashboards(module_id="m2")] == ["d2"]
    assert await store.update_dashboard("d1", {"title": "updated"}) is True
    assert await store.get_dashboard("d1") == {
        "dashboard_id": "d1",
        "module_id": "m1",
        "user_id": "u1",
        "created_at": "2",
        "title": "updated",
    }
    assert await store.update_dashboard("missing", {"title": "none"}) is False


async def test_dashboard_duplicate_create_returns_false(store: ds.DashboardStore) -> None:
    """Both stores preserve the first dashboard and tab on duplicate creation."""
    dashboard = {"dashboard_id": "d1", "created_at": "1"}
    tab = {"dashboard_id": "d1", "tab_id": "t1", "index": 0}
    assert await store.create_dashboard(dashboard) is True
    assert await store.create_dashboard({**dashboard, "title": "later"}) is False
    assert await store.create_tab(tab) is True
    assert await store.create_tab({**tab, "title": "later"}) is False
    assert await store.get_tab("d1", "t1") == tab


async def test_dashboard_delete_cascades_tabs(store: ds.DashboardStore) -> None:
    """Deleting a dashboard removes its tabs before deleting the dashboard itself."""
    assert await store.create_dashboard({"dashboard_id": "d1", "created_at": "1"})
    assert await store.create_tab({"dashboard_id": "d1", "tab_id": "t1", "index": 0})
    assert await store.delete_dashboard("d1") is True
    assert await store.get_dashboard("d1") is None
    assert await store.list_tabs("d1") == []
    assert await store.delete_dashboard("d1") is False


async def test_tabs_sorted_by_index(store: ds.DashboardStore) -> None:
    """Both stores return numbered tabs first and missing indexes after them."""
    assert await store.create_tab({"dashboard_id": "d1", "tab_id": "none"})
    assert await store.create_tab({"dashboard_id": "d1", "tab_id": "second", "index": 2, "_id": "internal"})
    assert await store.create_tab({"dashboard_id": "d1", "tab_id": "first", "index": 1})
    tabs = await store.list_tabs("d1")
    assert [tab["tab_id"] for tab in tabs] == ["first", "second", "none"]
    assert all("_id" not in tab for tab in tabs)
    assert await store.tab_exists("d1", "first") is True
    assert await store.update_tab("d1", "first", {"title": "updated"}) is True
    assert await store.delete_tab("d1", "first") is True
    assert await store.delete_tab("d1", "first") is False


def test_selector_default_is_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-store switch resolves on each call and defaults to Redis."""
    monkeypatch.delenv("DASHBOARDS_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    assert isinstance(ds.get_dashboard_store(), ds.RedisDashboardStore)
    monkeypatch.setenv("DASHBOARDS_STORE", "documentdb")
    assert isinstance(ds.get_dashboard_store(), ds.DocumentDbDashboardStore)
