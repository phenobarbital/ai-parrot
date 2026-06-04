"""Dataset common-field filter HTTP handler and AgenTalk envelope (FEAT-225 Module 7).

Three endpoints:

1. **GET .../filters/{agent_id}/schema** → ``DatasetManager.get_filter_schema()``
   Returns the filter catalog for the frontend to build combo selectors.

2. **GET .../filters/{agent_id}/values/{name}** → ``DatasetManager.get_filter_values(name)``
   Returns distinct values for a named filter (combo data).

3. **POST .../filters/{agent_id}** → ``DatasetManager.apply_filters(request, persist)``
   Applies a filter request recursively across all matching datasets.

AgenTalk typed pass-through envelope (``DatasetFilterEnvelope``) mirrors
``SpatialFilterEnvelope`` — forwards directly to the manager WITHOUT invoking
the agent loop or conversation memory.

Usage (aiohttp / navigator)::

    from parrot.handlers.dataset_filter_handler import DatasetFilterHandler
    app.router.add_route("*", "/api/v1/filters/{agent_id}", DatasetFilterHandler)
    app.router.add_route("*", "/api/v1/filters/{agent_id}/schema", DatasetFilterHandler)
    app.router.add_route("*", "/api/v1/filters/{agent_id}/values/{name}", DatasetFilterHandler)

AgenTalk envelope usage::

    from parrot.handlers.dataset_filter_handler import DatasetFilterEnvelope
    envelope = DatasetFilterEnvelope(request={"region": "North"}, agent_id="my-agent")
    result = await envelope.forward(dataset_manager)

Note: This handler uses aiohttp and is intended for the ``ai-parrot-server`` package.
``DatasetManager`` is imported lazily at runtime to avoid circular dependencies.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, TYPE_CHECKING

from aiohttp import web
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..tools.dataset_manager.tool import DatasetManager
    from ..tools.dataset_manager.filtering.contracts import FilterResult


# ---------------------------------------------------------------------------
# AgenTalk typed pass-through envelope
# ---------------------------------------------------------------------------


class DatasetFilterEnvelope(BaseModel):
    """Typed AgenTalk pass-through envelope for common-field filter requests.

    Forwards to ``DatasetManager.apply_filters`` WITHOUT invoking the agent
    loop (``AbstractBot.run()``), conversation memory, or session history.

    Attributes:
        request: Filter request mapping — ``{filter_name: value | FilterCondition}``.
        agent_id: Identifier for the agent whose DatasetManager to use.
        persist: When True, register filtered datasets back into the manager.
        channel: Originating channel (defaults to ``"agentalk"``).
    """

    request: Dict[str, Any] = Field(
        ...,
        description="Filter request mapping: {filter_name: value | FilterCondition}.",
    )
    agent_id: str = Field(..., description="Agent whose DatasetManager to use.")
    persist: bool = Field(
        default=False,
        description="When True, register filtered datasets back into the manager.",
    )
    channel: str = Field(
        default="agentalk",
        description="Originating channel identifier.",
    )

    async def forward(
        self,
        dataset_manager: "DatasetManager",
    ) -> "FilterResult":
        """Forward the request to DatasetManager.apply_filters.

        Does NOT call AbstractBot.run() or touch conversation memory.
        This is a direct, stateless call to the filter method.

        Args:
            dataset_manager: A ready DatasetManager instance.

        Returns:
            FilterResult with applied/skipped dataset lists.
        """
        logger.info(
            "DatasetFilterEnvelope: forwarding request to apply_filters "
            "(agent_id=%r, filter_keys=%r, persist=%r, channel=%r)",
            self.agent_id,
            list(self.request.keys()),
            self.persist,
            self.channel,
        )
        return await dataset_manager.apply_filters(
            self.request,
            persist=self.persist,
        )


# ---------------------------------------------------------------------------
# DatasetFilterHandler (aiohttp handler)
# ---------------------------------------------------------------------------


class DatasetFilterHandler:
    """aiohttp handler for common-field filter endpoints.

    Endpoints:
        GET  /api/v1/filters/{agent_id}/schema          — filter catalog
        GET  /api/v1/filters/{agent_id}/values/{name}   — distinct values
        POST /api/v1/filters/{agent_id}                  — apply filters

    Note: This handler is designed to be imported and mounted by the
    ``ai-parrot-server`` package.  It does not inherit from ``BaseView``
    directly to keep the core ``ai-parrot`` package server-independent.
    """

    def __init__(self, request: web.Request) -> None:
        self.request = request
        self.logger = logging.getLogger(__name__)

    async def _get_dataset_manager(self) -> "DatasetManager":
        """Retrieve the DatasetManager for the request's agent.

        Subclasses or the mounting server must override this to resolve the
        manager from the session/BotManager (mirroring SpatialFilterHandler).

        Raises:
            NotImplementedError: Always — must be overridden by the server.
        """
        raise NotImplementedError(
            "DatasetFilterHandler._get_dataset_manager must be overridden "
            "by the server package to resolve the manager from session/BotManager."
        )

    async def _json_response(
        self,
        data: Any,
        status: int = 200,
    ) -> web.Response:
        """Serialize *data* to a JSON aiohttp response.

        Args:
            data: Pydantic model or dict to serialize.
            status: HTTP status code.

        Returns:
            ``web.Response`` with ``application/json`` content type.
        """
        if hasattr(data, "model_dump"):
            body = json.dumps(data.model_dump(), default=str)
        else:
            body = json.dumps(data, default=str)
        return web.Response(
            text=body,
            status=status,
            content_type="application/json",
        )

    async def get(self) -> web.Response:
        """Handle GET requests.

        Routes:
        - ``/schema`` suffix → ``get_filter_schema()``
        - ``/values/{name}`` suffix → ``get_filter_values(name)``

        Returns:
            JSON response with schema list or values list.
        """
        agent_id = self.request.match_info.get("agent_id", "")
        if not agent_id:
            return await self._json_response({"error": "agent_id is required"}, status=400)

        try:
            dm = await self._get_dataset_manager()
        except (KeyError, NotImplementedError) as exc:
            return await self._json_response({"error": str(exc)}, status=404)

        # Check if this is a schema or values request
        path = self.request.path
        if path.endswith("/schema"):
            return await self._handle_schema(dm)

        # Check for /values/{name}
        filter_name = self.request.match_info.get("name")
        if filter_name:
            return await self._handle_values(dm, filter_name)

        return await self._json_response(
            {"error": "Unknown GET endpoint. Use /schema or /values/{name}"},
            status=400,
        )

    async def _handle_schema(self, dm: "DatasetManager") -> web.Response:
        """GET .../schema → filter catalog.

        Args:
            dm: DatasetManager instance.

        Returns:
            JSON array of filter schema entries.
        """
        schema = dm.get_filter_schema()
        self.logger.debug(
            "DatasetFilterHandler: GET schema returned %d filters.", len(schema)
        )
        return await self._json_response(schema)

    async def _handle_values(
        self, dm: "DatasetManager", filter_name: str
    ) -> web.Response:
        """GET .../values/{name} → distinct values for a filter.

        Args:
            dm: DatasetManager instance.
            filter_name: The filter definition name.

        Returns:
            JSON list of distinct values.
        """
        try:
            values = await dm.get_filter_values(filter_name)
        except KeyError as exc:
            return await self._json_response({"error": str(exc)}, status=404)
        except Exception as exc:
            self.logger.error(
                "DatasetFilterHandler: get_filter_values('%s') failed: %s",
                filter_name,
                exc,
            )
            return await self._json_response({"error": "Internal server error"}, status=500)

        self.logger.debug(
            "DatasetFilterHandler: GET values('%s') returned %d values.",
            filter_name,
            len(values),
        )
        return await self._json_response({"name": filter_name, "values": values})

    async def post(self) -> web.Response:
        """POST .../filters/{agent_id} — apply a filter request.

        Request body (JSON):
            - ``request`` (dict): Filter name → value mapping.
            - ``persist`` (bool, optional): Register filtered datasets.

        Returns:
            JSON ``FilterResult`` with ``applied`` and ``skipped`` lists.
        """
        agent_id = self.request.match_info.get("agent_id", "")
        if not agent_id:
            return await self._json_response({"error": "agent_id is required"}, status=400)

        try:
            body = await self.request.json()
        except (json.JSONDecodeError, ValueError):
            return await self._json_response({"error": "Invalid JSON body"}, status=400)

        filter_request = body.get("request", {})
        if not isinstance(filter_request, dict):
            return await self._json_response(
                {"error": "'request' must be a dict mapping filter names to values"},
                status=422,
            )

        persist = bool(body.get("persist", False))

        try:
            dm = await self._get_dataset_manager()
        except (KeyError, NotImplementedError) as exc:
            return await self._json_response({"error": str(exc)}, status=404)

        try:
            result = await dm.apply_filters(filter_request, persist=persist)
        except KeyError as exc:
            return await self._json_response({"error": str(exc)}, status=422)
        except ValueError as exc:
            return await self._json_response({"error": str(exc)}, status=422)
        except Exception as exc:
            self.logger.error(
                "DatasetFilterHandler: apply_filters failed: %s", exc
            )
            return await self._json_response({"error": "Internal server error"}, status=500)

        self.logger.info(
            "DatasetFilterHandler[%s]: apply_filters applied=%r skipped=%r persist=%s",
            agent_id,
            result.applied,
            result.skipped,
            persist,
        )
        return await self._json_response(result)
