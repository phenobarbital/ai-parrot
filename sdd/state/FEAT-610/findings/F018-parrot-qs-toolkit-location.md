---
id: F018
query_id: Q018
type: grep
intent: Locate parrot-side QuerySource integration (toolkit, qs_* tools, qs_build_linked_surface)
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F018 — `QuerysourceToolkit` (tool prefix `qs`) in ai-parrot-tools owns `qs_build_linked_surface`; it executes slugs in-process, not over HTTP
## Summary
The agent-facing integration is `parrot_tools.querysource.toolkit.QuerysourceToolkit` (registered under the `"querysource"` key in `parrot_tools/__init__.py`), generating `qs_get_dialect_reference`, `qs_list_slugs`, `qs_describe_slug`, `qs_execute_slug`, `qs_build_linked_surface`, `qs_list_components`, `qs_validate_pipeline`, `qs_run_multiquery` (+ `qs_save_multiquery` when `allow_write`). `build_linked_surface(slug, component, request, tenant, snapshot, ...)` describes the slug, validates `SourceRequest` placeholders/filter, builds a `LinkedDataSource` targeting `/{key}/rows`, runs it through `parrot.outputs.a2ui.linked.executor.execute_sources` (in-process QS call, no HTTP) and wraps the frame with `parrot.outputs.a2ui.builders.build_linked_surface` — one component per call. Config (`QuerysourceToolkitConfig`) has `programs` (tenant scope), `max_rows=200`, `forced_conditions`, `dsn`, `allow_raw_sql`. QS access goes through lazy imports in `_qs.py` (`get_qs`, `get_definition_repository` over the `QuerySource()` singleton). Legacy `QuerySourceTool` is still used by `examples/tools/qs.py`. Details are lane A's.
## Citations
- path: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`
  lines: 1-5
  symbol: `-`
  excerpt: |
    """QuerysourceToolkit — tenant-scoped QuerySource tools for agents (spec FEAT-558 §3 M5/M6).
    Generated tool names (tool_prefix 'qs'): qs_get_dialect_reference, qs_list_slugs, qs_describe_slug, qs_execute_slug,
    qs_build_linked_surface, qs_list_components, qs_validate_pipeline, qs_run_multiquery and — only when allow_write=True —
    qs_save_multiquery.
- path: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`
  lines: 339-345, 389
  symbol: `QuerysourceToolkit.build_linked_surface`
  excerpt: |
    async def build_linked_surface(
        self,
        slug: str,
        component: dict[str, Any],
        request: dict[str, Any] | None = None,
        tenant: str | None = None,
        snapshot: bool = True,
    ...
    execution = await execute_sources({key: source}, pctx=None, guard=None)
- path: `packages/ai-parrot-tools/src/parrot_tools/querysource/config.py`
  lines: 10-22
  symbol: `QuerysourceToolkitConfig`
  excerpt: |
    programs: list[str] | None = Field(default=None, description="Allowed program slugs (tenants); empty = all")
    allow_write: bool = False
    allow_raw_sql: bool = False
    ...
    max_rows: int = 200
- path: `packages/ai-parrot-tools/src/parrot_tools/__init__.py`
  lines: 138
  symbol: `-`
  excerpt: |
    "querysource": "parrot_tools.querysource.toolkit.QuerysourceToolkit",
## Implications
- `max_rows=200` default is relevant for the ~17k-row grid snapshot: the agent-built surface should snapshot a page (or none) and let the browser page via `_limit/_offset` (F012).
- Because the toolkit runs QS in-process, the server needs the QS singleton/env even if the browser never calls HTTP; the browser refresh path (HTTP, F011) and the agent build path (in-process) must hit the same slug/store (tenant vs public, F016).
