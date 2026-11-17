# FC-009 — Construction contract the new examples must honour: `SemanticLayerToolkit(**kwargs)` is kwargs-only and fails closed in five ways

**Query**: Q006 follow-up · **Type**: read · **Depth**: 1

## Summary
`SemanticLayerToolkit.__init__` takes `**kwargs` and `pop()`s its settings, so every argument is
keyword-only and a typo silently flows to `AbstractToolkit`. Five fail-closed constructor rules bound
what an example may do: (1) passing `static_subject` raises `SemanticPolicyError("static_subject_forbidden")`
— static identity belongs to `LocalSemanticLayerToolkit`, not the agent-surface toolkit;
(2) any governed model without a `dataplane_guard` raises `SemanticPolicyError("guard_required")`;
(3) `allow_raw_sql` must be a literal `bool`; (4) `dataset_manager_factory` must be callable;
(5) the sink it returns must pass `_validate_sink` — `GovernedSinkRegistry.register()` rejects an
`AbstractToolkit` itself, which is why the example needs the `_FacadeSink` composition wrapper rather
than handing back the facade. Defaults worth naming in an example: `result_ttl_s=900`,
`result_store_max=256`, `audit_required=None`, `allow_raw_sql=False`. The toolkit's `tool_prefix` is
`"sl"`. `LocalSemanticLayerToolkit` (bootstrap.py:60) is the separate class for the MCP-local surface.

## Citations
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:38-41` — `class SemanticLayerToolkit(AbstractToolkit)`, `tool_prefix = "sl"`
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:44-73` — `def __init__(self, **kwargs: Any) -> None` — pops `models_dir`, `dialect`, `dataplane_guard`, `rls_registry`, `database_toolkit`, `signer`, `audit_storage`, `static_subject`, `result_ttl_s=900`, `result_store_max=256`, `allowed_functions=()`, `audit_required=None`, `allow_raw_sql=False`, `dataset_manager_factory`; raises `static_subject_forbidden`, `invalid_allow_raw_sql`, `invalid_sink_factory`
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:78-79` — `guard_required` when any governed model has `dataplane_guard is None`
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:123-205, 451, 546` — the public tool methods: `list_models`, `list_metrics`, `get_dimensions`, `get_dimension_values`, `search_data_model`, `list_saved_queries`, `compile_query`, `query_metrics`, `run_sql`, `save_result_as_dataset`; plus `reload()` at :206
- `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py:34-44` — `class GovernedDatasetSink(Protocol)` with `async def publish(self, name, handle, authorize_read) -> dict[str, Any]`
- `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py:56-72, 74-118` — `_validate_sink` and `GovernedSinkRegistry.register` — what rejects a bare `AbstractToolkit`/`DatasetManager`
- `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py:46-49` — `handle_owner(handle) -> tuple[str, str, str, str]`; `:159-200` — `build_read_authorizer(...)` producing the `ReadAuthorizer`
- `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py:23-30, 60-117, 130-162` — `StaticSubject(BaseModel)`, `class LocalSemanticLayerToolkit(SemanticLayerToolkit)` with its own `__init__` and `_build_guard` — the MCP-local entry point a second example could target
- `packages/ai-parrot-semantic/src/parrot/semantic/ossie.py:18-31` — `is_ossie_document(doc)` / `validate_ossie_document(doc)` — the OSSIE import path, exercised only by `tests/test_ossie.py` and never by an example
- `packages/ai-parrot-server/src/parrot/handlers/semantic.py` — the HTTP surface (in `ai-parrot-server`, not `ai-parrot-semantic`); `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/semantic.py` — a third consumer

## Notes
- `run_sql` exists at `toolkit.py:451` but is only exposed when `allow_raw_sql=True`; a "raw SQL under
  governance" example is a distinct, documented story (`docs/tools/semantic-layer.md:83, 86-92`).
- `[cross-lane: type=external, intent=ai-parrot-semantic has no external docs/examples upstream; the clean-room format means no third-party example can be borrowed]`
