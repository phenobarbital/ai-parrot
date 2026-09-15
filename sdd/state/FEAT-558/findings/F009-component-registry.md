---
id: F009
query_id: Q008
type: read
intent: Read the MultiQuery component registry — what /api/v3/qs/components serializes; callable in-process.
executed_at: 2026-09-15T02:49:00Z
duration_ms: 2500
parent_id: null
depth: 0
---
# F009 — ComponentRegistry.get_catalog() and validate_pipeline() are importable, no HTTP needed
## Summary
`querysource.queries.multi.registry.ComponentRegistry` exposes classmethods `discover_all() -> dict[str, type]`, `get_catalog() -> list[ComponentInfo]` and `validate_pipeline(payload) -> ValidationResult`. `ComponentInfo(name, category, description, usage, attributes: list[AttributeInfo], json_schema, example, icon)` is exactly the REST payload shape in the user's example; the REST handler `list_components` just runs `get_catalog` in `asyncio.to_thread` (it is sync and does import/introspection work), applies `?category=`, and PBAC `slug:read`. `validate_pipeline` checks ≥1 source section, known step names, and Join/Merge arity. Inventory (Q017): operators Concat/GroupBy/Info/Join/Melt/Merge (+Filter), 13 transformations, 9 sources, 4 destinations, 18 `*.catalog.yaml` companions.
## Citations
- path: `.venv/lib/python3.12/site-packages/querysource/queries/multi/registry.py`
  lines: 24-70
  symbol: `AttributeInfo`, `ComponentInfo`, `ValidationError`, `ValidationResult`
  excerpt: |
    @dataclass class ComponentInfo:
        name: str; category: str  # "Operators" | "Transformations" | "Sources" | "Destinations" | "Components"
        description: str; usage: str; attributes: list[AttributeInfo]; json_schema: dict | None; example: str = ""; icon: str = ""
- path: `.venv/lib/python3.12/site-packages/querysource/queries/multi/registry.py`
  lines: 92, 187-230, 332-375
  symbol: `ComponentRegistry.discover_all`, `ComponentRegistry.get_catalog`, `ComponentRegistry.validate_pipeline`
  excerpt: |
    def validate_pipeline(cls, payload: dict) -> ValidationResult:
        # Rule 1: at least one of queries/files/sources; Rule 2: step names ∈ discover_all(); Join/Merge need 2+ inputs
        skip_keys = {"queries", "files", "sources", "Output", "Transform", "Processors"}
- path: `.venv/lib/python3.12/site-packages/querysource/handlers/components.py`
  lines: 25-65
  symbol: `list_components`
  excerpt: |
    await self._enforce_pbac(request, resource_type=ResourceType.SLUG, resource_name="components", action="slug:read")
    catalog = await asyncio.to_thread(ComponentRegistry.get_catalog)
    if category: catalog = [c for c in catalog if c.category == category]
- path: `.venv/lib/python3.12/site-packages/querysource/queries/multi/`
  excerpt: |
    operators/{Concat,GroupBy,Info,Join,Melt,Merge}.py + operators/filter/
    transformations/{correlation,crosstab,DropCols,FilterCols,Forecast,Map,NormalizeColumns,pivot,PluckCols,tExplode,tOrder,tPandas}.py
    sources/{airtable,file,query,s3,sharepoint,smartsheet,table,executors}.py ; destinations/{dwh,s3,sharepoint,table}.py
