"""Spatial filter HTTP handler and AgenTalk pass-through envelope (FEAT-219 Module 6).

Two transport paths, both returning an identical ``SpatialFeatureCollection``:

1. **Direct (deterministic) path**: frontend POSTs ``{point, radius, unit, datasets}``
   directly → ``DatasetManager.spatial_filter(spec)`` → GeoJSON response.

2. **NL→spec synthesis path**: frontend POSTs ``{query, datasets}`` with natural
   language → ``NLSpatialSynthesizer.synthesize(query, datasets)`` builds a
   ``SpatialFilterSpec`` → same ``spatial_filter`` call → identical response.

3. **AgenTalk typed pass-through envelope**: typed ``SpatialFilterEnvelope`` wraps
   the spec for chat-originating requests.  The envelope forwards to
   ``spatial_filter`` and does NOT invoke ``AbstractBot.run()`` or the agent loop
   (spec Non-Goals: no bidirectional chat↔map coupling).

Usage (aiohttp / navigator)::

    # In your app router:
    from parrot.handlers.spatial_filter_handler import SpatialFilterHandler
    app.router.add_route("*", "/api/v1/spatial/{agent_id}", SpatialFilterHandler)
    app.router.add_route("*", "/api/v1/spatial/{agent_id}/manifest", SpatialFilterHandler)

AgenTalk envelope usage::

    from parrot.handlers.spatial_filter_handler import SpatialFilterEnvelope
    envelope = SpatialFilterEnvelope(spec=spec, agent_id="my-agent")
    result = await envelope.forward(dataset_manager)

Note: The handler uses aiohttp and is intended for the ``ai-parrot-server`` package to
mount.  It imports ``DatasetManager`` lazily at runtime to avoid circular dependencies
at module load time.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional, TYPE_CHECKING

from aiohttp import web
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..tools.dataset_manager.tool import DatasetManager
    from ..tools.dataset_manager.spatial.contracts import (
        SpatialFilterSpec,
        SpatialFeatureCollection,
    )


# ---------------------------------------------------------------------------
# AgenTalk typed pass-through envelope
# ---------------------------------------------------------------------------


class SpatialFilterEnvelope(BaseModel):
    """Typed AgenTalk pass-through envelope for spatial filter requests.

    Forwards to ``DatasetManager.spatial_filter`` WITHOUT invoking the agent
    loop (``AbstractBot.run()``), conversation memory, or session history.

    This is a typed pass-through only: the chat UI sends a map selection (or
    reads a map reference from a previous LLM turn) and forwards the spec
    directly to the filter — no agent reasoning cycle.

    Attributes:
        spec: The spatial filter spec (point, radius, datasets).
        agent_id: Identifier for the agent whose DatasetManager to use.
        cap_per_dataset: Hard cap on returned features per dataset.
        channel: Originating channel (defaults to ``"agentalk"``).
    """

    spec: "SpatialFilterSpec"
    agent_id: str = Field(..., description="Agent whose DatasetManager to use.")
    cap_per_dataset: int = Field(
        default=1000,
        ge=1,
        description="Hard cap on features returned per dataset.",
    )
    channel: str = Field(
        default="agentalk",
        description="Originating channel identifier.",
    )

    async def forward(
        self,
        dataset_manager: "DatasetManager",
    ) -> "SpatialFeatureCollection":
        """Forward the spec to DatasetManager.spatial_filter.

        Does NOT call AbstractBot.run() or touch conversation memory.
        This is a direct, stateless call to the spatial filter method.

        Args:
            dataset_manager: A ready DatasetManager instance with the relevant
                datasets registered.

        Returns:
            SpatialFeatureCollection — identical shape to the deterministic path.
        """
        logger.info(
            "SpatialFilterEnvelope: forwarding spec to spatial_filter "
            "(agent_id=%r, datasets=%r, channel=%r)",
            self.agent_id,
            self.spec.datasets,
            self.channel,
        )
        return await dataset_manager.spatial_filter(
            self.spec,
            cap_per_dataset=self.cap_per_dataset,
        )


# ---------------------------------------------------------------------------
# NL → spec synthesizer (thin wrapper)
# ---------------------------------------------------------------------------


class NLSpatialSynthesizer:
    """Thin synthesizer: natural language → SpatialFilterSpec.

    Uses the configured LLM client to extract structured spatial parameters
    from a user's natural language query.  The agent does NOT run a reasoning
    loop — this is a single structured-output LLM call.

    The synthesizer is stateless; construct one per request.

    Args:
        client: An ``AbstractClient`` instance to use for the structured
            extraction call.  If None, a fallback heuristic parser is used
            (for testing; not suitable for production NL queries).
    """

    def __init__(self, client: Optional[Any] = None) -> None:
        self.client = client
        self.logger = logging.getLogger(__name__)

    async def synthesize(
        self,
        query: str,
        available_datasets: List[str],
        default_datasets: Optional[List[str]] = None,
    ) -> "SpatialFilterSpec":
        """Synthesize a SpatialFilterSpec from a natural language query.

        Args:
            query: User's natural language spatial query, e.g.
                ``"show schools within 5 miles of the warehouse at 40.7, -74.0"``.
            available_datasets: List of spatially-queryable dataset names.
            default_datasets: Datasets to query if none are inferred from the
                query text.

        Returns:
            A validated SpatialFilterSpec.

        Raises:
            ValueError: If the query cannot be parsed into a valid spec.
        """
        from ..tools.dataset_manager.spatial.contracts import SpatialFilterSpec

        if self.client is not None:
            return await self._synthesize_via_llm(
                query, available_datasets, default_datasets, SpatialFilterSpec
            )
        # Fallback: raise to indicate NL synthesis requires a client
        raise ValueError(
            "NLSpatialSynthesizer: no LLM client configured; "
            "cannot synthesize a SpatialFilterSpec from natural language. "
            f"Query was: {query!r}"
        )

    async def _synthesize_via_llm(
        self,
        query: str,
        available_datasets: List[str],
        default_datasets: Optional[List[str]],
        spec_class: Any,
    ) -> "SpatialFilterSpec":
        """Use the LLM client to extract SpatialFilterSpec fields.

        Sends a single structured-output prompt to the LLM.  The LLM responds
        with JSON that is validated against ``SpatialFilterSpec``.

        Args:
            query: Natural language query string.
            available_datasets: Available spatial datasets.
            default_datasets: Fallback datasets if none inferred.
            spec_class: SpatialFilterSpec class to validate the parsed output.

        Returns:
            Validated SpatialFilterSpec.
        """
        system_prompt = (
            "You are a spatial query parser.  Extract the spatial filter "
            "parameters from the user's query and return ONLY valid JSON "
            "matching the schema: "
            "{\"point\": [lat, lng], \"radius\": float, \"unit\": \"mi|km|m\", "
            "\"datasets\": [list of dataset names]}. "
            f"Available datasets: {available_datasets}. "
            "If no datasets are mentioned, use all available datasets."
        )
        raw = await self.client.completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            response_format={"type": "json_object"},
        )
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            if not data.get("datasets"):
                data["datasets"] = default_datasets or available_datasets
            return spec_class(**data)
        except Exception as exc:
            raise ValueError(
                f"NLSpatialSynthesizer: failed to parse LLM output into "
                f"SpatialFilterSpec: {exc}.  Raw output: {raw!r}"
            ) from exc


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class DirectSpatialRequest(BaseModel):
    """Request body for the direct (deterministic) spatial filter path.

    Attributes:
        point: ``[lat, lng]`` in decimal degrees.
        radius: Search radius.
        unit: Distance unit.
        datasets: Dataset names to query.
        cap_per_dataset: Hard cap per dataset (optional).
    """

    point: List[float] = Field(..., min_length=2, max_length=2)
    radius: float = Field(..., gt=0)
    unit: Literal["mi", "km", "m"] = Field(default="mi")
    datasets: List[str] = Field(..., min_length=1)
    cap_per_dataset: int = Field(default=1000, ge=1)


class NLSpatialRequest(BaseModel):
    """Request body for the NL→spec synthesis spatial filter path.

    Attributes:
        query: Natural language spatial query.
        datasets: Optional hint about which datasets to query.
        cap_per_dataset: Hard cap per dataset.
    """

    query: str = Field(..., min_length=1, max_length=4096)
    datasets: Optional[List[str]] = Field(default=None)
    cap_per_dataset: int = Field(default=1000, ge=1)


# ---------------------------------------------------------------------------
# SpatialFilterHandler (aiohttp BaseView)
# ---------------------------------------------------------------------------


class SpatialFilterHandler:
    """aiohttp handler for spatial filter endpoints.

    Endpoints:
        POST /api/v1/spatial/{agent_id}/direct    — deterministic path
        POST /api/v1/spatial/{agent_id}/nl        — NL→spec synthesis path
        GET  /api/v1/spatial/{agent_id}/manifest  — dataset manifest

    Both POST endpoints return the same ``SpatialFeatureCollection`` JSON
    so the frontend is mode-agnostic (spec G1).

    Note: This handler is designed to be imported and mounted by the
    ``ai-parrot-server`` package.  It does not inherit from ``BaseView``
    directly to keep the core ``ai-parrot`` package server-independent;
    the server package wraps it as needed.
    """

    def __init__(self, request: web.Request) -> None:
        self.request = request
        self.logger = logging.getLogger(__name__)

    async def _get_dataset_manager(self) -> "DatasetManager":
        """Retrieve (or create) the DatasetManager for the request's agent.

        Subclasses or the mounting server are responsible for injecting the
        manager.  The default implementation raises NotImplementedError.

        Raises:
            NotImplementedError: Always — must be overridden by the server.
        """
        raise NotImplementedError(
            "SpatialFilterHandler._get_dataset_manager must be overridden "
            "by the server package to resolve the manager from session/BotManager."
        )

    async def _json_response(
        self,
        data: Any,
        status: int = 200,
    ) -> web.Response:
        """Serialize ``data`` to a JSON aiohttp response.

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

    async def post(self) -> web.Response:
        """Handle POST requests for both direct and NL→spec paths.

        The path discriminator is the ``?mode=direct`` (default) or ``?mode=nl``
        query parameter, or the presence/absence of a ``query`` field in the body.

        Returns:
            JSON response with ``SpatialFeatureCollection``.
        """
        agent_id = self.request.match_info.get("agent_id", "")
        if not agent_id:
            return await self._json_response({"error": "agent_id is required"}, status=400)

        try:
            body = await self.request.json()
        except (json.JSONDecodeError, ValueError):
            return await self._json_response({"error": "Invalid JSON body"}, status=400)

        # Detect which path to use
        if "query" in body:
            return await self._handle_nl(agent_id, body)
        return await self._handle_direct(agent_id, body)

    async def _handle_direct(self, agent_id: str, body: Dict) -> web.Response:
        """Handle the deterministic (direct) spatial filter path.

        Args:
            agent_id: Agent identifier.
            body: Parsed JSON request body.

        Returns:
            JSON response with ``SpatialFeatureCollection``.
        """
        from ..tools.dataset_manager.spatial.contracts import SpatialFilterSpec

        self.logger.info(
            "SpatialFilterHandler[%s]: direct path, datasets=%r",
            agent_id,
            body.get("datasets"),
        )

        try:
            req = DirectSpatialRequest(**body)
        except Exception as exc:
            return await self._json_response({"error": f"Invalid request: {exc}"}, status=422)

        try:
            spec = SpatialFilterSpec(
                point=tuple(req.point),
                radius=req.radius,
                unit=req.unit,
                datasets=req.datasets,
            )
        except Exception as exc:
            return await self._json_response(
                {"error": f"Invalid spatial spec: {exc}"}, status=422
            )

        try:
            dm = await self._get_dataset_manager()
        except (KeyError, NotImplementedError) as exc:
            return await self._json_response({"error": str(exc)}, status=404)

        try:
            result = await dm.spatial_filter(spec, cap_per_dataset=req.cap_per_dataset)
        except ValueError as exc:
            return await self._json_response({"error": str(exc)}, status=422)
        except Exception as exc:
            self.logger.error("SpatialFilterHandler: direct path failed: %s", exc)
            return await self._json_response({"error": "Internal server error"}, status=500)

        self.logger.info(
            "SpatialFilterHandler[%s]: direct path returned %d features "
            "(total=%d, capped=%s)",
            agent_id, len(result.features), result.total_count, result.capped,
        )
        return await self._json_response(result)

    async def _handle_nl(self, agent_id: str, body: Dict) -> web.Response:
        """Handle the NL→spec synthesis spatial filter path.

        Args:
            agent_id: Agent identifier.
            body: Parsed JSON request body.

        Returns:
            JSON response with ``SpatialFeatureCollection``.
        """
        self.logger.info(
            "SpatialFilterHandler[%s]: NL path, query=%r",
            agent_id,
            body.get("query"),
        )

        try:
            req = NLSpatialRequest(**body)
        except Exception as exc:
            return await self._json_response({"error": f"Invalid request: {exc}"}, status=422)

        try:
            dm = await self._get_dataset_manager()
        except (KeyError, NotImplementedError) as exc:
            return await self._json_response({"error": str(exc)}, status=404)

        # Get available spatial datasets from manifest
        manifest = dm.get_manifest()
        available = [entry["dataset"] for entry in manifest]
        datasets_hint = req.datasets or available

        # Synthesize spec via LLM (requires a client — server injects it)
        client = getattr(dm, "_llm_client", None) or getattr(self, "_client", None)
        synthesizer = NLSpatialSynthesizer(client=client)

        try:
            spec = await synthesizer.synthesize(
                query=req.query,
                available_datasets=available,
                default_datasets=datasets_hint,
            )
        except ValueError as exc:
            return await self._json_response({"error": str(exc)}, status=422)
        except Exception as exc:
            self.logger.error("SpatialFilterHandler: NL synthesis failed: %s", exc)
            return await self._json_response({"error": "Synthesis failed"}, status=500)

        try:
            result = await dm.spatial_filter(spec, cap_per_dataset=req.cap_per_dataset)
        except ValueError as exc:
            return await self._json_response({"error": str(exc)}, status=422)
        except Exception as exc:
            self.logger.error("SpatialFilterHandler: NL path execution failed: %s", exc)
            return await self._json_response({"error": "Internal server error"}, status=500)

        self.logger.info(
            "SpatialFilterHandler[%s]: NL path returned %d features "
            "(total=%d, capped=%s)",
            agent_id, len(result.features), result.total_count, result.capped,
        )
        return await self._json_response(result)

    async def get(self) -> web.Response:
        """GET /api/v1/spatial/{agent_id}/manifest — spatial dataset manifest.

        Returns:
            JSON list of spatial dataset entries (layer, geodesic, property_cols).
        """
        agent_id = self.request.match_info.get("agent_id", "")
        if not agent_id:
            return await self._json_response({"error": "agent_id is required"}, status=400)

        try:
            dm = await self._get_dataset_manager()
        except (KeyError, NotImplementedError) as exc:
            return await self._json_response({"error": str(exc)}, status=404)

        manifest = dm.get_manifest()
        return await self._json_response({"datasets": manifest})
