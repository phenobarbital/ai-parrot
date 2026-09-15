---
id: F002
query_id: Q002
type: read
intent: Read the current QSourceTool — schema, description, payload building, return shape.
executed_at: 2026-09-15T02:41:00Z
duration_ms: 1500
parent_id: null
depth: 0
---
# F002 — QSourceTool is a single AbstractTool with an under-specified schema
## Summary
`QSourceTool(AbstractTool)` (437 lines) exposes ONE tool whose `QuerySourceInput` has `query_slug`, `query` (raw SQL), `conditions` ("fields, filters, and group_by clauses" — no grammar), `additional_filters`, `driver`, `return_format`, `structured_output_class`, `lazy`, `limit`. `_execute()` merges `additional_filters` into `conditions['filter']`, maps `limit`→`conditions['querylimit']`, builds `QS(slug=..., conditions=..., driver=..., lazy=...)`, calls `build_provider()` then `query()`. Latent bug: `DataNotFound` is imported only under `TYPE_CHECKING` but used in a runtime `except` (line 237) → `NameError` when that branch is hit. Uses f-string logging and bare `except:`; no tenant/program notion; no way to inspect or list slugs.
## Citations
- path: `packages/ai-parrot-tools/src/parrot_tools/qsource.py`
  lines: 21-59
  symbol: `QuerySourceInput`
  excerpt: |
    conditions: Optional[Dict[str, Any]] = Field(default_factory=dict,
        description="Query conditions including fields, filters, and group_by clauses")
    additional_filters: ... description="Additional filters to apply to the query conditions"
- path: `packages/ai-parrot-tools/src/parrot_tools/qsource.py`
  lines: 62-79
  symbol: `QSourceTool`
  excerpt: |
    name: str = "QSourceTool"
    description: str = ("Execute QuerySource queries to retrieve and analyze data. "
        "Supports query slugs, raw SQL, filtering, grouping, and multiple output formats. ...")
- path: `packages/ai-parrot-tools/src/parrot_tools/qsource.py`
  lines: 14-17
  excerpt: |
    if TYPE_CHECKING:
        from querysource.queries.qs import QS
        from querysource.exceptions import DataNotFound  # only for type checking
    from .abstract import AbstractTool, ToolResult
- path: `packages/ai-parrot-tools/src/parrot_tools/qsource.py`
  lines: 174-236
  symbol: `QSourceTool._execute`
  excerpt: |
    _qs_mod = lazy_import("querysource.queries.qs", package_name="querysource", extra="db")
    ... conditions['filter'] = filters
    if limit: conditions['querylimit'] = limit
    qry = QS(slug=query_slug, lazy=lazy, conditions=conditions, driver=driver)
    await qry.build_provider()
    result, error = await qry.query(output_format='pandas')  # or qry.query()
- path: `packages/ai-parrot-tools/src/parrot_tools/qsource.py`
  lines: 237-249
  excerpt: |
    except DataNotFound as e:   # <-- NameError at runtime: name only bound under TYPE_CHECKING
- path: `packages/ai-parrot-tools/src/parrot_tools/qsource.py`
  lines: 327-396
  symbol: `QSourceTool._process_results`
  excerpt: return formats dict | json | pandas | structured (via available_structured_outputs)
