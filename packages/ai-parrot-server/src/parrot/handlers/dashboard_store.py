"""Dashboard persistence (FEAT-878): DocumentDB and Redis dashboard stores."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from parrot.interfaces.documentdb import DocumentDb
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import DASHBOARDS, DASHBOARD_TABS

logger = logging.getLogger("Parrot.DashboardStore")
DASHBOARDS_COLLECTION = "dashboards"
TABS_COLLECTION = "dashboard_tabs"


class DashboardStore(Protocol):
    """Persistence operations used by dashboard handlers without MongoDB ``_id`` values."""

    async def ensure_indexes(self) -> None: ...

    async def get_dashboard(self, dashboard_id: str) -> dict[str, Any] | None: ...

    async def list_dashboards(
        self, *, module_id: str | None = None, user_id: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def create_dashboard(self, doc: dict[str, Any]) -> bool: ...

    async def dashboard_exists(self, dashboard_id: str) -> bool: ...

    async def update_dashboard(self, dashboard_id: str, fields: dict[str, Any]) -> bool: ...

    async def delete_dashboard(self, dashboard_id: str) -> bool: ...

    async def get_tab(self, dashboard_id: str, tab_id: str) -> dict[str, Any] | None: ...

    async def list_tabs(self, dashboard_id: str) -> list[dict[str, Any]]: ...

    async def create_tab(self, doc: dict[str, Any]) -> bool: ...

    async def tab_exists(self, dashboard_id: str, tab_id: str) -> bool: ...

    async def update_tab(self, dashboard_id: str, tab_id: str, fields: dict[str, Any]) -> bool: ...

    async def delete_tab(self, dashboard_id: str, tab_id: str) -> bool: ...


def get_dashboard_store() -> DashboardStore:
    """Return the call-time configured dashboard persistence backend."""
    from parrot.userstore import resolve_store_backend

    return RedisDashboardStore() if resolve_store_backend("DASHBOARDS_STORE") == "redis" else DocumentDbDashboardStore()


class DocumentDbDashboardStore:
    """Today's dashboard handler DocumentDB queries, moved without changing their behavior."""

    async def ensure_indexes(self) -> None:
        """Create the dashboard indexes used by the legacy handler."""
        try:
            async with DocumentDb() as db:
                await db.create_indexes(
                    DASHBOARDS_COLLECTION,
                    [
                        {"keys": [("dashboard_id", 1)], "unique": True},
                        "module_id",
                        "user_id",
                        {"keys": [("module_id", 1), ("user_id", 1)]},
                    ],
                )
                await db.create_indexes(
                    TABS_COLLECTION,
                    [
                        {"keys": [("tab_id", 1)], "unique": True},
                        "dashboard_id",
                        "module_id",
                        "user_id",
                        {"keys": [("dashboard_id", 1), ("tab_id", 1)], "unique": True},
                    ],
                )
                logger.info("Dashboard indexes created on '%s' and '%s'", DASHBOARDS_COLLECTION, TABS_COLLECTION)
        except Exception as exc:
            logger.warning("Failed to create dashboard indexes: %s", exc)

    async def get_dashboard(self, dashboard_id: str) -> dict[str, Any] | None:
        """Return one dashboard without its DocumentDB internal identifier."""
        async with DocumentDb() as db:
            doc = await db.read_one(DASHBOARDS_COLLECTION, {"dashboard_id": dashboard_id})
        if doc:
            doc.pop("_id", None)
        return doc or None

    async def list_dashboards(
        self, *, module_id: str | None = None, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List dashboards in reverse creation order, optionally filtered by module and user."""
        query = {key: value for key, value in (("module_id", module_id), ("user_id", user_id)) if value}
        async with DocumentDb() as db:
            docs = await db.read(DASHBOARDS_COLLECTION, query or None, sort=[("created_at", -1)])
        for doc in docs:
            doc.pop("_id", None)
        return list(docs)

    async def create_dashboard(self, doc: dict[str, Any]) -> bool:
        """Create a dashboard only when its identifier is absent."""
        async with DocumentDb() as db:
            if await db.exists(DASHBOARDS_COLLECTION, {"dashboard_id": doc["dashboard_id"]}):
                return False
            await db.write(DASHBOARDS_COLLECTION, doc)
        return True

    async def dashboard_exists(self, dashboard_id: str) -> bool:
        """Return whether a dashboard exists."""
        async with DocumentDb() as db:
            return await db.exists(DASHBOARDS_COLLECTION, {"dashboard_id": dashboard_id})

    async def update_dashboard(self, dashboard_id: str, fields: dict[str, Any]) -> bool:
        """Update an existing dashboard without creating a missing one."""
        async with DocumentDb() as db:
            if not await db.exists(DASHBOARDS_COLLECTION, {"dashboard_id": dashboard_id}):
                return False
            await db.update(DASHBOARDS_COLLECTION, {"dashboard_id": dashboard_id}, {"$set": fields})
        return True

    async def delete_dashboard(self, dashboard_id: str) -> bool:
        """Delete an existing dashboard after deleting all of its tabs."""
        async with DocumentDb() as db:
            if not await db.exists(DASHBOARDS_COLLECTION, {"dashboard_id": dashboard_id}):
                return False
            await db.delete(TABS_COLLECTION, {"dashboard_id": dashboard_id})
            await db.delete(DASHBOARDS_COLLECTION, {"dashboard_id": dashboard_id})
        return True

    async def get_tab(self, dashboard_id: str, tab_id: str) -> dict[str, Any] | None:
        """Return one tab without its DocumentDB internal identifier."""
        async with DocumentDb() as db:
            doc = await db.read_one(TABS_COLLECTION, {"dashboard_id": dashboard_id, "tab_id": tab_id})
        if doc:
            doc.pop("_id", None)
        return doc or None

    async def list_tabs(self, dashboard_id: str) -> list[dict[str, Any]]:
        """List a dashboard's tabs in ascending index order."""
        async with DocumentDb() as db:
            docs = await db.read(TABS_COLLECTION, {"dashboard_id": dashboard_id}, sort=[("index", 1)])
        for doc in docs:
            doc.pop("_id", None)
        return list(docs)

    async def create_tab(self, doc: dict[str, Any]) -> bool:
        """Create a tab only when its dashboard/tab key is absent."""
        key = {"dashboard_id": doc["dashboard_id"], "tab_id": doc["tab_id"]}
        async with DocumentDb() as db:
            if await db.exists(TABS_COLLECTION, key):
                return False
            await db.write(TABS_COLLECTION, doc)
        return True

    async def tab_exists(self, dashboard_id: str, tab_id: str) -> bool:
        """Return whether a tab exists for the requested dashboard."""
        async with DocumentDb() as db:
            return await db.exists(TABS_COLLECTION, {"dashboard_id": dashboard_id, "tab_id": tab_id})

    async def update_tab(self, dashboard_id: str, tab_id: str, fields: dict[str, Any]) -> bool:
        """Update an existing tab without creating a missing one."""
        key = {"dashboard_id": dashboard_id, "tab_id": tab_id}
        async with DocumentDb() as db:
            if not await db.exists(TABS_COLLECTION, key):
                return False
            await db.update(TABS_COLLECTION, key, {"$set": fields})
        return True

    async def delete_tab(self, dashboard_id: str, tab_id: str) -> bool:
        """Delete one tab when it exists."""
        key = {"dashboard_id": dashboard_id, "tab_id": tab_id}
        async with DocumentDb() as db:
            if not await db.exists(TABS_COLLECTION, key):
                return False
            await db.delete(TABS_COLLECTION, key)
        return True


class RedisDashboardStore:
    """Dashboards and tabs stored in Redis key/index structures."""

    def __init__(self) -> None:
        """Initialize the two Redis document collections."""
        self._dash = RedisDocumentStore(DASHBOARDS)
        self._tabs = RedisDocumentStore(DASHBOARD_TABS)

    async def ensure_indexes(self) -> None:
        """Do nothing because Redis indexes are maintained by the key layout."""
        return None

    async def get_dashboard(self, dashboard_id: str) -> dict[str, Any] | None:
        """Return one dashboard by identifier."""
        return await self._dash.get({"dashboard_id": dashboard_id})

    async def list_dashboards(
        self, *, module_id: str | None = None, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List dashboards in reverse creation order, optionally filtered by module and user."""
        where = {key: value for key, value in (("module_id", module_id), ("user_id", user_id)) if value}
        docs = await self._dash.find(where or None)
        return sorted(docs, key=lambda doc: doc.get("created_at") or "", reverse=True)

    async def create_dashboard(self, doc: dict[str, Any]) -> bool:
        """Create a dashboard only when its identifier is absent."""
        return await self._dash.create(doc)

    async def dashboard_exists(self, dashboard_id: str) -> bool:
        """Return whether a dashboard exists."""
        return await self._dash.exists({"dashboard_id": dashboard_id})

    async def update_dashboard(self, dashboard_id: str, fields: dict[str, Any]) -> bool:
        """Update an existing dashboard without creating a missing one."""
        return await self._dash.update({"dashboard_id": dashboard_id}, fields)

    async def delete_dashboard(self, dashboard_id: str) -> bool:
        """Delete a dashboard and its tabs, deleting tabs first."""
        await self._tabs.delete_where({"dashboard_id": dashboard_id})
        return await self._dash.delete({"dashboard_id": dashboard_id})

    async def get_tab(self, dashboard_id: str, tab_id: str) -> dict[str, Any] | None:
        """Return one tab by its compound dashboard/tab key."""
        return await self._tabs.get({"dashboard_id": dashboard_id, "tab_id": tab_id})

    async def list_tabs(self, dashboard_id: str) -> list[dict[str, Any]]:
        """List dashboard tabs with indexed tabs first and null indexes last."""
        docs = await self._tabs.find({"dashboard_id": dashboard_id})
        return sorted(docs, key=lambda doc: (doc.get("index") is None, doc.get("index") or 0))

    async def create_tab(self, doc: dict[str, Any]) -> bool:
        """Create a tab only when its dashboard/tab key is absent."""
        return await self._tabs.create(doc)

    async def tab_exists(self, dashboard_id: str, tab_id: str) -> bool:
        """Return whether a tab exists for the requested dashboard."""
        return await self._tabs.exists({"dashboard_id": dashboard_id, "tab_id": tab_id})

    async def update_tab(self, dashboard_id: str, tab_id: str, fields: dict[str, Any]) -> bool:
        """Update an existing tab without creating a missing one."""
        return await self._tabs.update({"dashboard_id": dashboard_id, "tab_id": tab_id}, fields)

    async def delete_tab(self, dashboard_id: str, tab_id: str) -> bool:
        """Delete one tab when it exists."""
        return await self._tabs.delete({"dashboard_id": dashboard_id, "tab_id": tab_id})
