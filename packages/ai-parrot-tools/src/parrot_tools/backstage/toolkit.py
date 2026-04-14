"""
BackstageCatalogToolkit — Read entries from a Backstage.io software catalog.

Extends OpenAPIToolkit to auto-generate tools from the official Backstage
Catalog Backend OpenAPI spec, and adds curated convenience methods for the
most frequent catalog operations.

Usage:
    toolkit = BackstageCatalogToolkit(
        base_url="https://backstage.example.com/api/catalog",
        api_key="<backstage-token>",
    )
    tools = toolkit.get_tools()

Environment variables:
    BACKSTAGE_BASE_URL  — Base URL of the Backstage catalog API
    BACKSTAGE_API_KEY   — Bearer token for authentication
"""

import os
from typing import Any, Optional
from urllib.parse import quote

from navconfig.logging import logging

from parrot.interfaces.http import HTTPService
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.abstract import ToolResult

from .models import (
    Entity,
    EntitiesQueryResponse,
    EntityFacetsResponse,
    Location,
)

# Inline OpenAPI spec for the Backstage Catalog Backend.
# Derived from https://github.com/backstage/backstage/blob/master/
# plugins/catalog-backend/src/schema/openapi.yaml
# Only read-oriented endpoints are included to keep the tool surface lean.
_BACKSTAGE_CATALOG_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {
        "title": "Backstage Catalog API",
        "version": "1.0.0",
        "description": "Backstage Software Catalog read operations.",
    },
    "servers": [{"url": "{base_url}", "variables": {"base_url": {"default": ""}}}],
    "paths": {},  # We use explicit async methods instead of dynamic generation
}


class BackstageCatalogToolkit(AbstractToolkit):
    """Toolkit for reading entries from a Backstage.io software catalog.

    Provides tools for querying the Backstage Catalog Backend API:
    - List and search entities with filtering and pagination
    - Look up entities by UID, name, or entity refs
    - Query entity facets for aggregated counts
    - List and look up catalog locations
    - Retrieve entity ancestry/lineage
    - Validate entity definitions

    Authentication is via Bearer token (Backstage service-to-service
    or user tokens).

    Example:
        toolkit = BackstageCatalogToolkit(
            base_url="https://backstage.example.com/api/catalog",
            api_key="<token>",
        )
        tools = toolkit.get_tools()
    """

    # Methods that are internal and should not be exposed as tools.
    exclude_tools: tuple[str, ...] = ()

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 30,
        use_proxy: bool = False,
        debug: bool = False,
        **kwargs,
    ):
        """Initialize the Backstage Catalog toolkit.

        Args:
            base_url: Base URL of the Backstage catalog API
                      (e.g. ``https://backstage.example.com/api/catalog``).
                      Falls back to ``BACKSTAGE_BASE_URL`` env var.
            api_key: Bearer token for Backstage API authentication.
                     Falls back to ``BACKSTAGE_API_KEY`` env var.
            timeout: HTTP request timeout in seconds.
            use_proxy: Whether to route requests through a proxy.
            debug: Enable debug logging.
            **kwargs: Additional arguments passed to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self.logger = logging.getLogger("Parrot.Tools.BackstageCatalog")

        self.base_url = (
            base_url
            or os.environ.get("BACKSTAGE_BASE_URL", "")
        ).rstrip("/")
        if not self.base_url:
            raise ValueError(
                "Backstage base URL is required. "
                "Pass base_url= or set the BACKSTAGE_BASE_URL environment variable."
            )

        self.api_key = api_key or os.environ.get("BACKSTAGE_API_KEY", "")
        self.debug = debug

        # Build credentials/headers for HTTPService
        headers: dict[str, str] = {"Accept": "application/json"}
        credentials: dict[str, str] = {}
        if self.api_key:
            credentials["token"] = self.api_key

        self._http = HTTPService(
            accept="application/json",
            headers=headers,
            credentials=credentials,
            use_proxy=use_proxy,
            timeout=timeout,
            debug=debug,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    async def _get(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute a GET request against the catalog API.

        Args:
            path: API path relative to base_url (e.g. ``/entities``).
            params: Optional query parameters.

        Returns:
            Parsed JSON response or error dict.
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        if self.debug:
            self.logger.debug("GET %s params=%s", url, params)

        result, error = await self._http._request(
            url=url,
            method="GET",
            params=params or {},
            full_response=False,
            use_proxy=False,
            raise_for_status=False,
        )
        if error:
            return ToolResult(
                status="error",
                result=None,
                error=str(error),
                metadata={"url": url},
            ).model_dump()

        return ToolResult(
            status="success",
            result=result,
            metadata={"url": url},
        ).model_dump()

    async def _post(
        self,
        path: str,
        data: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute a POST request against the catalog API.

        Args:
            path: API path relative to base_url.
            data: JSON body payload.
            params: Optional query parameters.

        Returns:
            Parsed JSON response or error dict.
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        if self.debug:
            self.logger.debug("POST %s data=%s params=%s", url, data, params)

        result, error = await self._http._request(
            url=url,
            method="POST",
            data=data or {},
            params=params or {},
            use_json=True,
            full_response=False,
            use_proxy=False,
            raise_for_status=False,
        )
        if error:
            return ToolResult(
                status="error",
                result=None,
                error=str(error),
                metadata={"url": url},
            ).model_dump()

        return ToolResult(
            status="success",
            result=result,
            metadata={"url": url},
        ).model_dump()

    # ------------------------------------------------------------------
    # Entity Tools
    # ------------------------------------------------------------------

    async def list_entities(
        self,
        filter: Optional[str] = None,
        fields: Optional[str] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        after: Optional[str] = None,
    ) -> dict[str, Any]:
        """List all entities in the Backstage catalog with optional filtering.

        Use the ``filter`` parameter to narrow results. Multiple filters can be
        combined with comma separation.

        Args:
            filter: Filter expression (e.g. ``kind=component,metadata.namespace=default``
                    or ``kind=api,spec.type=openapi``).
            fields: Comma-separated list of fields to include in the response
                    (e.g. ``metadata.name,metadata.namespace,kind``).
            order: Ordering specification (e.g. ``asc:metadata.name``).
            limit: Maximum number of entities to return.
            offset: Number of entities to skip (for pagination).
            after: Cursor for keyset pagination.

        Returns:
            List of catalog entities matching the filter criteria.
        """
        params: dict[str, Any] = {}
        if filter:
            params["filter"] = filter
        if fields:
            params["fields"] = fields
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if after:
            params["after"] = after
        return await self._get("entities", params=params)

    async def get_entity_by_uid(self, uid: str) -> dict[str, Any]:
        """Fetch a single entity by its unique identifier (UID).

        Args:
            uid: The unique identifier of the entity.

        Returns:
            The entity object matching the UID.
        """
        return await self._get(f"entities/by-uid/{quote(uid, safe='')}")

    async def get_entity_by_name(
        self,
        kind: str,
        namespace: str,
        name: str,
    ) -> dict[str, Any]:
        """Fetch a single entity by kind, namespace, and name.

        Args:
            kind: Entity kind (e.g. ``Component``, ``API``, ``System``, ``Group``).
            namespace: Entity namespace (usually ``default``).
            name: Entity name.

        Returns:
            The matching entity object.
        """
        path = (
            f"entities/by-name/"
            f"{quote(kind, safe='')}/{quote(namespace, safe='')}/{quote(name, safe='')}"
        )
        return await self._get(path)

    async def get_entity_ancestry(
        self,
        kind: str,
        namespace: str,
        name: str,
    ) -> dict[str, Any]:
        """Get the ancestry (lineage) of an entity.

        Returns the chain of parent entity references that led to this entity
        being ingested into the catalog.

        Args:
            kind: Entity kind.
            namespace: Entity namespace.
            name: Entity name.

        Returns:
            Ancestry response with ``rootEntityRef`` and ``items`` array
            containing ``parentEntityRefs`` at each level.
        """
        path = (
            f"entities/by-name/"
            f"{quote(kind, safe='')}/{quote(namespace, safe='')}/{quote(name, safe='')}"
            "/ancestry"
        )
        return await self._get(path)

    async def get_entities_by_refs(
        self,
        entity_refs: list[str],
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Batch-retrieve multiple entities by their entity references.

        Args:
            entity_refs: List of entity references
                         (e.g. ``["component:default/my-service", "api:default/my-api"]``).
            fields: Optional list of fields to include in the response.

        Returns:
            Batch response with an ``items`` array (nullable entries for
            refs that were not found).
        """
        body: dict[str, Any] = {"entityRefs": entity_refs}
        if fields:
            body["fields"] = fields
        return await self._post("entities/by-refs", data=body)

    async def query_entities(
        self,
        filter: Optional[str] = None,
        fields: Optional[str] = None,
        order_field: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        cursor: Optional[str] = None,
        full_text_filter_term: Optional[str] = None,
        full_text_filter_fields: Optional[str] = None,
    ) -> dict[str, Any]:
        """Search entities with filtering, full-text search, and pagination.

        This endpoint supports cursor-based pagination for efficient traversal
        of large result sets.

        Args:
            filter: Filter expression (same syntax as ``list_entities``).
            fields: Comma-separated fields to include.
            order_field: Field to order results by (e.g. ``metadata.name``).
            limit: Maximum number of results per page.
            offset: Number of results to skip.
            cursor: Pagination cursor from a previous response.
            full_text_filter_term: Full-text search term to match against
                                   entity fields.
            full_text_filter_fields: Comma-separated list of fields to search
                                     (e.g. ``metadata.name,metadata.description``).

        Returns:
            Paginated response with ``items``, ``totalItems``, and ``pageInfo``
            (containing ``nextCursor`` / ``prevCursor``).
        """
        params: dict[str, Any] = {}
        if filter:
            params["filter"] = filter
        if fields:
            params["fields"] = fields
        if order_field:
            params["orderField"] = order_field
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if cursor:
            params["cursor"] = cursor
        if full_text_filter_term:
            params["fullTextFilterTerm"] = full_text_filter_term
        if full_text_filter_fields:
            params["fullTextFilterFields"] = full_text_filter_fields
        return await self._get("entities/by-query", params=params)

    async def get_entity_facets(
        self,
        facets: list[str],
        filter: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get faceted (aggregated) counts for entity properties.

        Useful for building filter UIs or understanding the distribution
        of entities across categories.

        Args:
            facets: List of fields to facet on
                    (e.g. ``["kind", "spec.type", "spec.lifecycle"]``).
            filter: Optional filter to restrict which entities are included.

        Returns:
            Facets response with counts for each unique value of each
            requested facet field.
        """
        params: dict[str, Any] = {"facet": facets}
        if filter:
            params["filter"] = filter
        return await self._get("entity-facets", params=params)

    # ------------------------------------------------------------------
    # Location Tools
    # ------------------------------------------------------------------

    async def list_locations(self) -> dict[str, Any]:
        """List all registered catalog locations.

        Locations are pointers to catalog descriptor files (e.g. catalog-info.yaml)
        that Backstage discovers and ingests entities from.

        Returns:
            Array of location objects (each wrapped in a ``data`` property
            with ``id``, ``type``, and ``target`` fields).
        """
        return await self._get("locations")

    async def get_location_by_id(self, location_id: str) -> dict[str, Any]:
        """Fetch a specific catalog location by its ID.

        Args:
            location_id: The unique identifier of the location.

        Returns:
            Location object with ``id``, ``type``, and ``target``.
        """
        return await self._get(f"locations/{quote(location_id, safe='')}")

    async def get_location_by_entity(
        self,
        kind: str,
        namespace: str,
        name: str,
    ) -> dict[str, Any]:
        """Get the catalog location that provides a specific entity.

        Args:
            kind: Entity kind.
            namespace: Entity namespace.
            name: Entity name.

        Returns:
            The location object that registered the entity.
        """
        path = (
            f"locations/by-entity/"
            f"{quote(kind, safe='')}/{quote(namespace, safe='')}/{quote(name, safe='')}"
        )
        return await self._get(path)

    # ------------------------------------------------------------------
    # Refresh & Validate Tools
    # ------------------------------------------------------------------

    async def refresh_entity(self, entity_ref: str) -> dict[str, Any]:
        """Trigger a refresh of a specific entity in the catalog.

        Forces Backstage to re-read the entity's source location and update
        the catalog entry.

        Args:
            entity_ref: Full entity reference string
                        (e.g. ``component:default/my-service``).

        Returns:
            Success confirmation or error details.
        """
        return await self._post("refresh", data={"entityRef": entity_ref})

    async def validate_entity(
        self,
        entity: dict[str, Any],
        location: str,
    ) -> dict[str, Any]:
        """Validate an entity definition against the catalog schema.

        Checks whether the provided entity YAML/JSON would be accepted
        by the catalog without actually registering it.

        Args:
            entity: The entity object to validate (as a dict with
                    ``apiVersion``, ``kind``, ``metadata``, ``spec``).
            location: Reference location string for the entity.

        Returns:
            Validation result — either success or list of validation errors.
        """
        return await self._post(
            "validate-entity",
            data={"entity": entity, "location": location},
        )
