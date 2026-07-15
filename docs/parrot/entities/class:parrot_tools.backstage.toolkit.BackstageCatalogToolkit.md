---
type: Wiki Entity
title: BackstageCatalogToolkit
id: class:parrot_tools.backstage.toolkit.BackstageCatalogToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for reading entries from a Backstage.io software catalog.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# BackstageCatalogToolkit

Defined in [`parrot_tools.backstage.toolkit`](../summaries/mod:parrot_tools.backstage.toolkit.md).

```python
class BackstageCatalogToolkit(AbstractToolkit)
```

Toolkit for reading entries from a Backstage.io software catalog.

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

## Methods

- `async def list_entities(self, filter: Optional[str]=None, fields: Optional[str]=None, order: Optional[str]=None, limit: Optional[int]=None, offset: Optional[int]=None, after: Optional[str]=None) -> dict[str, Any]` — List all entities in the Backstage catalog with optional filtering.
- `async def get_entity_by_uid(self, uid: str) -> dict[str, Any]` — Fetch a single entity by its unique identifier (UID).
- `async def get_entity_by_name(self, kind: str, namespace: str, name: str) -> dict[str, Any]` — Fetch a single entity by kind, namespace, and name.
- `async def get_entity_ancestry(self, kind: str, namespace: str, name: str) -> dict[str, Any]` — Get the ancestry (lineage) of an entity.
- `async def get_entities_by_refs(self, entity_refs: list[str], fields: Optional[list[str]]=None) -> dict[str, Any]` — Batch-retrieve multiple entities by their entity references.
- `async def query_entities(self, filter: Optional[str]=None, fields: Optional[str]=None, order_field: Optional[str]=None, limit: Optional[int]=None, offset: Optional[int]=None, cursor: Optional[str]=None, full_text_filter_term: Optional[str]=None, full_text_filter_fields: Optional[str]=None) -> dict[str, Any]` — Search entities with filtering, full-text search, and pagination.
- `async def get_entity_facets(self, facets: list[str], filter: Optional[str]=None) -> dict[str, Any]` — Get faceted (aggregated) counts for entity properties.
- `async def list_locations(self) -> dict[str, Any]` — List all registered catalog locations.
- `async def get_location_by_id(self, location_id: str) -> dict[str, Any]` — Fetch a specific catalog location by its ID.
- `async def get_location_by_entity(self, kind: str, namespace: str, name: str) -> dict[str, Any]` — Get the catalog location that provides a specific entity.
- `async def refresh_entity(self, entity_ref: str) -> dict[str, Any]` — Trigger a refresh of a specific entity in the catalog.
- `async def validate_entity(self, entity: dict[str, Any], location: str) -> dict[str, Any]` — Validate an entity definition against the catalog schema.
