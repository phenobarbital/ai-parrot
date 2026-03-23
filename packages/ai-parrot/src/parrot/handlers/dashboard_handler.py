"""REST API Handler for Dashboard Persistence.

Provides CRUD endpoints for managing dashboards and dashboard tabs
using DocumentDB (MongoDB) as the persistence layer.

Endpoints:
    GET    /api/v1/dashboards                         — list all dashboards
    GET    /api/v1/dashboards/{dashboard_id}          — get single dashboard
    POST   /api/v1/dashboards                         — create new dashboard
    PUT    /api/v1/dashboards/{dashboard_id}          — update existing dashboard
    PATCH  /api/v1/dashboards/{dashboard_id}          — partial update
    DELETE /api/v1/dashboards/{dashboard_id}          — delete dashboard

    GET    /api/v1/dashboards/{dashboard_id}/tabs              — list tabs
    POST   /api/v1/dashboards/{dashboard_id}/tabs              — create tab
    PUT    /api/v1/dashboards/{dashboard_id}/tabs/{tab_id}     — update tab
    DELETE /api/v1/dashboards/{dashboard_id}/tabs/{tab_id}     — delete tab
    PATCH  /api/v1/dashboards/{dashboard_id}/tabs/{tab_id}     — partial tab update
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView

from ..interfaces.documentdb import DocumentDb

# Collection names
DASHBOARDS_COLLECTION = "dashboards"
TABS_COLLECTION = "dashboard_tabs"


async def _ensure_dashboard_indexes(app: web.Application) -> None:
    """Create indexes on dashboards and dashboard_tabs collections.

    Called during application startup to ensure fast lookups by
    module_id, dashboard_id, tab_id, and user_id.
    """
    logger = logging.getLogger("Parrot.DashboardHandler")
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
            logger.info(
                "Dashboard indexes created on '%s' and '%s'",
                DASHBOARDS_COLLECTION,
                TABS_COLLECTION,
            )
    except Exception as exc:
        logger.warning("Failed to create dashboard indexes: %s", exc)


class DashboardHandler(BaseView):
    """REST API Handler for Dashboard CRUD operations."""

    _logger_name: str = "Parrot.DashboardHandler"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    # -- helpers ---------------------------------------------------------------

    def _dashboard_id(self) -> Optional[str]:
        """Extract dashboard_id from URL path."""
        return self.request.match_info.get("dashboard_id") or None

    def _user_id(self) -> Optional[str]:
        """Extract user_id from request context."""
        return self.request.get("user_id") or None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- GET -------------------------------------------------------------------

    async def get(self) -> web.Response:
        """GET handler.

        - ``/dashboards/{dashboard_id}`` → single dashboard with its tabs
        - ``/dashboards?module_id=X`` → list dashboards filtered by module
        - ``/dashboards`` → list all dashboards for current user
        """
        dashboard_id = self._dashboard_id()
        if dashboard_id:
            return await self._get_one(dashboard_id)
        return await self._get_list()

    async def _get_one(self, dashboard_id: str) -> web.Response:
        """Return a single dashboard with its tabs."""
        async with DocumentDb() as db:
            dashboard = await db.read_one(
                DASHBOARDS_COLLECTION,
                {"dashboard_id": dashboard_id},
            )
            if not dashboard:
                return self.error(
                    response={"message": f"Dashboard '{dashboard_id}' not found"},
                    status=404,
                )
            # Strip MongoDB internal _id
            dashboard.pop("_id", None)

            # Fetch associated tabs
            tabs = await db.read(
                TABS_COLLECTION,
                {"dashboard_id": dashboard_id},
                sort=[("index", 1)],
            )
            for tab in tabs:
                tab.pop("_id", None)

            dashboard["tabs"] = tabs
            return self.json_response(dashboard)

    async def _get_list(self) -> web.Response:
        """Return list of dashboards, optionally filtered by module_id or user_id."""
        qs = self.query_parameters(self.request)
        query: Dict[str, Any] = {}

        if module_id := qs.get("module_id"):
            query["module_id"] = module_id
        if user_id := qs.get("user_id"):
            query["user_id"] = user_id

        async with DocumentDb() as db:
            dashboards = await db.read(
                DASHBOARDS_COLLECTION,
                query or None,
                sort=[("created_at", -1)],
            )
            for d in dashboards:
                d.pop("_id", None)

        return self.json_response({
            "dashboards": dashboards,
            "total": len(dashboards),
        })

    # -- POST (create) ---------------------------------------------------------

    async def post(self) -> web.Response:
        """Create a new dashboard.

        Body: ``{"title": "...", "module_id": "...", "attributes": {...}}``
        """
        try:
            data = await self.request.json()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        title = data.get("title")
        if not title:
            return self.error(
                response={"message": "'title' is required"},
                status=400,
            )

        dashboard_id = data.get("dashboard_id") or uuid.uuid4().hex
        now = self._now()
        user_id = data.get("user_id") or self._user_id()

        doc: Dict[str, Any] = {
            "dashboard_id": dashboard_id,
            "title": title,
            "module_id": data.get("module_id", ""),
            "user_id": user_id,
            "attributes": data.get("attributes", {}),
            "created_at": now,
            "updated_at": now,
        }

        async with DocumentDb() as db:
            await db.write(DASHBOARDS_COLLECTION, doc)

        return self.json_response(
            {"message": "Dashboard created", "dashboard_id": dashboard_id},
            status=201,
        )

    # -- PUT (full update) -----------------------------------------------------

    async def put(self) -> web.Response:
        """Full update of an existing dashboard.

        Body: full dashboard JSON (excluding dashboard_id which comes from URL).
        """
        dashboard_id = self._dashboard_id()
        if not dashboard_id:
            return self.error(
                response={"message": "dashboard_id is required in URL"},
                status=400,
            )

        try:
            data = await self.request.json()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        now = self._now()
        update_fields: Dict[str, Any] = {
            "title": data.get("title", ""),
            "module_id": data.get("module_id", ""),
            "user_id": data.get("user_id") or self._user_id(),
            "attributes": data.get("attributes", {}),
            "updated_at": now,
        }

        async with DocumentDb() as db:
            exists = await db.exists(
                DASHBOARDS_COLLECTION,
                {"dashboard_id": dashboard_id},
            )
            if not exists:
                return self.error(
                    response={"message": f"Dashboard '{dashboard_id}' not found"},
                    status=404,
                )
            await db.update(
                DASHBOARDS_COLLECTION,
                {"dashboard_id": dashboard_id},
                {"$set": update_fields},
            )

        return self.json_response(
            {"message": f"Dashboard '{dashboard_id}' updated"}
        )

    # -- PATCH (partial update) ------------------------------------------------

    async def patch(self) -> web.Response:
        """Partially update fields on a dashboard.

        Body: JSON with fields to merge (e.g. ``{"title": "New Title"}``).
        """
        dashboard_id = self._dashboard_id()
        if not dashboard_id:
            return self.error(
                response={"message": "dashboard_id is required in URL"},
                status=400,
            )

        try:
            patch_data = await self.request.json()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        if not isinstance(patch_data, dict) or not patch_data:
            return self.error(
                response={"message": "Body must be a non-empty JSON object"},
                status=400,
            )

        # Prevent overwriting the primary key
        patch_data.pop("dashboard_id", None)
        patch_data["updated_at"] = self._now()

        async with DocumentDb() as db:
            exists = await db.exists(
                DASHBOARDS_COLLECTION,
                {"dashboard_id": dashboard_id},
            )
            if not exists:
                return self.error(
                    response={"message": f"Dashboard '{dashboard_id}' not found"},
                    status=404,
                )
            await db.update(
                DASHBOARDS_COLLECTION,
                {"dashboard_id": dashboard_id},
                {"$set": patch_data},
            )

        return self.json_response({
            "message": f"Dashboard '{dashboard_id}' patched",
            "updated_fields": list(patch_data.keys()),
        })

    # -- DELETE ----------------------------------------------------------------

    async def delete(self) -> web.Response:
        """Delete a dashboard and all its tabs."""
        dashboard_id = self._dashboard_id()
        if not dashboard_id:
            return self.error(
                response={"message": "dashboard_id is required"},
                status=400,
            )

        async with DocumentDb() as db:
            exists = await db.exists(
                DASHBOARDS_COLLECTION,
                {"dashboard_id": dashboard_id},
            )
            if not exists:
                return self.error(
                    response={"message": f"Dashboard '{dashboard_id}' not found"},
                    status=404,
                )
            # Remove all tabs first
            await db.delete(TABS_COLLECTION, {"dashboard_id": dashboard_id})
            # Remove the dashboard
            await db.delete(DASHBOARDS_COLLECTION, {"dashboard_id": dashboard_id})

        return self.json_response(
            {"message": f"Dashboard '{dashboard_id}' and its tabs deleted"}
        )


class DashboardTabHandler(BaseView):
    """REST API Handler for Dashboard Tab CRUD operations."""

    _logger_name: str = "Parrot.DashboardTabHandler"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    # -- helpers ---------------------------------------------------------------

    def _dashboard_id(self) -> Optional[str]:
        return self.request.match_info.get("dashboard_id") or None

    def _tab_id(self) -> Optional[str]:
        return self.request.match_info.get("tab_id") or None

    def _user_id(self) -> Optional[str]:
        return self.request.get("user_id") or None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- GET -------------------------------------------------------------------

    async def get(self) -> web.Response:
        """GET handler.

        - ``/dashboards/{dashboard_id}/tabs/{tab_id}`` → single tab
        - ``/dashboards/{dashboard_id}/tabs`` → list all tabs for dashboard
        """
        dashboard_id = self._dashboard_id()
        if not dashboard_id:
            return self.error(
                response={"message": "dashboard_id is required"},
                status=400,
            )

        tab_id = self._tab_id()
        if tab_id:
            return await self._get_one_tab(dashboard_id, tab_id)
        return await self._get_tabs(dashboard_id)

    async def _get_one_tab(self, dashboard_id: str, tab_id: str) -> web.Response:
        """Return a single tab."""
        async with DocumentDb() as db:
            tab = await db.read_one(
                TABS_COLLECTION,
                {"dashboard_id": dashboard_id, "tab_id": tab_id},
            )
            if not tab:
                return self.error(
                    response={"message": f"Tab '{tab_id}' not found"},
                    status=404,
                )
            tab.pop("_id", None)
            return self.json_response(tab)

    async def _get_tabs(self, dashboard_id: str) -> web.Response:
        """Return all tabs for a dashboard, ordered by index."""
        async with DocumentDb() as db:
            tabs = await db.read(
                TABS_COLLECTION,
                {"dashboard_id": dashboard_id},
                sort=[("index", 1)],
            )
            for tab in tabs:
                tab.pop("_id", None)

        return self.json_response({
            "tabs": tabs,
            "total": len(tabs),
        })

    # -- POST (create tab) -----------------------------------------------------

    async def post(self) -> web.Response:
        """Create a new tab for a dashboard.

        Body: ``{"title": "...", "layout_mode": "grid", "widgets": [...]}``
        """
        dashboard_id = self._dashboard_id()
        if not dashboard_id:
            return self.error(
                response={"message": "dashboard_id is required"},
                status=400,
            )

        try:
            data = await self.request.json()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        title = data.get("title")
        if not title:
            return self.error(
                response={"message": "'title' is required"},
                status=400,
            )

        tab_id = data.get("tab_id") or uuid.uuid4().hex
        now = self._now()

        # Determine next index
        async with DocumentDb() as db:
            # Verify parent dashboard exists
            parent_exists = await db.exists(
                DASHBOARDS_COLLECTION,
                {"dashboard_id": dashboard_id},
            )
            if not parent_exists:
                return self.error(
                    response={"message": f"Dashboard '{dashboard_id}' not found"},
                    status=404,
                )

            existing_tabs = await db.read(
                TABS_COLLECTION,
                {"dashboard_id": dashboard_id},
            )
            next_index = data.get("index", len(existing_tabs))

            doc: Dict[str, Any] = {
                "tab_id": tab_id,
                "dashboard_id": dashboard_id,
                "title": title,
                "icon": data.get("icon", "📊"),
                "index": next_index,
                "layout_mode": data.get("layout_mode", "grid"),
                "grid_mode": data.get("grid_mode", "flexible"),
                "template": data.get("template", "default"),
                "pane_size": data.get("pane_size", 300),
                "closable": data.get("closable", True),
                "component": data.get("component"),
                "widgets": data.get("widgets", []),
                "module_id": data.get("module_id", ""),
                "user_id": data.get("user_id") or self._user_id(),
                "created_at": now,
                "updated_at": now,
            }

            await db.write(TABS_COLLECTION, doc)

        return self.json_response(
            {"message": "Tab created", "tab_id": tab_id},
            status=201,
        )

    # -- PUT (full update tab) -------------------------------------------------

    async def put(self) -> web.Response:
        """Full update of an existing tab."""
        dashboard_id = self._dashboard_id()
        tab_id = self._tab_id()
        if not dashboard_id or not tab_id:
            return self.error(
                response={"message": "dashboard_id and tab_id are required in URL"},
                status=400,
            )

        try:
            data = await self.request.json()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        now = self._now()
        update_fields: Dict[str, Any] = {
            "title": data.get("title", ""),
            "icon": data.get("icon", "📊"),
            "index": data.get("index", 0),
            "layout_mode": data.get("layout_mode", "grid"),
            "grid_mode": data.get("grid_mode", "flexible"),
            "template": data.get("template", "default"),
            "pane_size": data.get("pane_size", 300),
            "closable": data.get("closable", True),
            "component": data.get("component"),
            "widgets": data.get("widgets", []),
            "module_id": data.get("module_id", ""),
            "user_id": data.get("user_id") or self._user_id(),
            "updated_at": now,
        }

        async with DocumentDb() as db:
            exists = await db.exists(
                TABS_COLLECTION,
                {"dashboard_id": dashboard_id, "tab_id": tab_id},
            )
            if not exists:
                return self.error(
                    response={"message": f"Tab '{tab_id}' not found"},
                    status=404,
                )
            await db.update(
                TABS_COLLECTION,
                {"dashboard_id": dashboard_id, "tab_id": tab_id},
                {"$set": update_fields},
            )

        return self.json_response(
            {"message": f"Tab '{tab_id}' updated"}
        )

    # -- PATCH (partial update tab) --------------------------------------------

    async def patch(self) -> web.Response:
        """Partially update fields on a tab.

        Body: JSON with fields to merge (e.g. ``{"title": "New Tab"}``).
        """
        dashboard_id = self._dashboard_id()
        tab_id = self._tab_id()
        if not dashboard_id or not tab_id:
            return self.error(
                response={"message": "dashboard_id and tab_id are required in URL"},
                status=400,
            )

        try:
            patch_data = await self.request.json()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        if not isinstance(patch_data, dict) or not patch_data:
            return self.error(
                response={"message": "Body must be a non-empty JSON object"},
                status=400,
            )

        # Prevent overwriting primary keys
        patch_data.pop("tab_id", None)
        patch_data.pop("dashboard_id", None)
        patch_data["updated_at"] = self._now()

        async with DocumentDb() as db:
            exists = await db.exists(
                TABS_COLLECTION,
                {"dashboard_id": dashboard_id, "tab_id": tab_id},
            )
            if not exists:
                return self.error(
                    response={"message": f"Tab '{tab_id}' not found"},
                    status=404,
                )
            await db.update(
                TABS_COLLECTION,
                {"dashboard_id": dashboard_id, "tab_id": tab_id},
                {"$set": patch_data},
            )

        return self.json_response({
            "message": f"Tab '{tab_id}' patched",
            "updated_fields": list(patch_data.keys()),
        })

    # -- DELETE ----------------------------------------------------------------

    async def delete(self) -> web.Response:
        """Delete a tab from a dashboard."""
        dashboard_id = self._dashboard_id()
        tab_id = self._tab_id()
        if not dashboard_id or not tab_id:
            return self.error(
                response={"message": "dashboard_id and tab_id are required"},
                status=400,
            )

        async with DocumentDb() as db:
            exists = await db.exists(
                TABS_COLLECTION,
                {"dashboard_id": dashboard_id, "tab_id": tab_id},
            )
            if not exists:
                return self.error(
                    response={"message": f"Tab '{tab_id}' not found"},
                    status=404,
                )
            await db.delete(
                TABS_COLLECTION,
                {"dashboard_id": dashboard_id, "tab_id": tab_id},
            )

        return self.json_response(
            {"message": f"Tab '{tab_id}' deleted from dashboard '{dashboard_id}'"}
        )
