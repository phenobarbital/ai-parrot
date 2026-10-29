# FW-001 — `SemanticLayerToolkit` takes `**kwargs` only; its 10 `sl_*` tools are plain async methods

**Query**: Q001/Q002/Q005 · **Type**: wiki_query + wiki_page + symbol + source read · **Depth**: 0

## Summary
`SemanticLayerToolkit` subclasses `AbstractToolkit` with `tool_prefix = "sl"` and
`exclude_tools = ("reload",)`, so every public async method is auto-exposed as `sl_<method>`.
Its `__init__` signature is literally `def __init__(self, **kwargs: Any) -> None` — there are
**no named constructor parameters**; every setting is `kwargs.pop(...)`ed. Two tools are
*conditionally* excluded at construction time: `run_sql` unless `allow_raw_sql=True`, and
`save_result_as_dataset` unless a callable `dataset_manager_factory` is supplied. Passing
`static_subject=` to this class raises `SemanticPolicyError("static_subject_forbidden")` — static
identity belongs to `LocalSemanticLayerToolkit` (see FW-006). A governed model without
`dataplane_guard` raises `SemanticPolicyError("guard_required")`.

## Citations
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:38-43` — class header:
  `class SemanticLayerToolkit(AbstractToolkit):` with `tool_prefix = "sl"`, `exclude_tools = ("reload",)`
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:44-108` —
  `def __init__(self, **kwargs: Any) -> None`. Popped keys, in order, with their defaults:
  `models_dir` (required, wrapped in `Path`), `dialect` (required, `str()`), `dataplane_guard=None`,
  `rls_registry=None`, `database_toolkit=None`, `signer=None`, `audit_storage=None`,
  `static_subject=None` (**forbidden — raises**), `result_ttl_s=900`, `result_store_max=256`,
  `allowed_functions=()`, `audit_required=None`, `allow_raw_sql=False`, `dataset_manager_factory=None`.
  Remaining `**kwargs` go to `super().__init__(**kwargs)` (`AbstractToolkit`).
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:123-204, 451, 546` — exact tool method signatures:
  - `async def list_models(self) -> list[dict]` (L123)
  - `async def list_metrics(self, model: str) -> list[dict]` (L138)
  - `async def get_dimensions(self, model: str, metrics: list[str] | None = None) -> list[dict]` (L147)
  - `async def get_dimension_values(self, model: str, dimension: str, metrics: list[str] | None = None, limit: int = 50) -> SemanticQueryResult` (L158-160)
  - `async def search_data_model(self, text: str, model: str | None = None) -> list[dict]` (L165)
  - `async def list_saved_queries(self, model: str) -> list[dict]` (L183)
  - `async def compile_query(self, query: SemanticQuery) -> dict` (L195)
  - `async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult` (L200)
  - `async def run_sql(self, model: str, sql: str) -> SemanticQueryResult` (L451)
  - `async def save_result_as_dataset(self, result_id: str, name: str, description: str | None = None) -> dict` (L546)
  - `def reload(self) -> None` (L206) — **not** a tool (`exclude_tools`)
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:99-108` — per-instance exclusion:
  `excluded += ("run_sql",)` when `not self._allow_raw_sql`; `excluded += ("save_result_as_dataset",)`
  when `self._sink_factory is None`.
- `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py:1-7` — package exports only
  `__version__`, `SemanticQuery`, `SemanticQueryResult`, `SemanticLayerToolkit`.
  `bind_semantic_context`, `SemanticRequestIdentity`, `ResultHandle`, `GovernedDatasetSink`
  are **not** re-exported — import them from their submodules.
- wiki page `file:docs/tools/semantic-layer.md` (score=0.63) — the `sl_*` table; matches the source.

## Notes
`run_sql` additionally raises `SemanticAccessError("raw_sql_disabled")` at call time
(toolkit.py:468-469), so the gate is doubled: tool not exposed *and* method refuses.
