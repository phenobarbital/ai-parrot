# F008 — Construction, tool, hand-off and MCP-local contracts — kwargs-only, fails closed five ways

**Merged from**: FC-009, FW-001, FW-005, FW-006

<!-- merged from FC-009 -->
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

---

<!-- merged from FW-001 -->
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

---

<!-- merged from FW-005 -->
**Query**: Q005 (follow-up) · **Type**: source read · **Depth**: 1

## Summary
Result hand-off exists only when the host passes a `dataset_manager_factory` —
an *async callable* `(SemanticRequestIdentity) -> GovernedDatasetSink`. The sink must declare
`guarded_reads = True`, a non-blank `scope_id: str`, an immutable 4-tuple
`owner: (agent_id, user_id, tenant_id, session_id)`, and an **async** `publish`. `_validate_sink`
rejects anything whose MRO contains `DatasetManager`, `AbstractToolkit` or `DataFrame` — so a sink
may not itself be an `AbstractToolkit`; the existing example solves this by composition
(`_FacadeSink` wraps the facade). Every exposure must call the `authorize_read` callback produced by
`build_read_authorizer`, which re-checks agent/user/tenant/session/subject-digest, TTL,
model+policy digests, catalog visibility, per-column usage grants, table lineage and PBAC — then
re-checks staleness after the awaits. Every denial collapses to the single opaque
`SemanticResultError("result_unavailable", "Result is unavailable")`.

## Citations
- `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py:32-41` —
  `@runtime_checkable class GovernedDatasetSink(Protocol)` with
  `scope_id: str`, `owner: tuple[str, str, str, str]`, `guarded_reads: Literal[True]`, and
  `async def publish(self, name: str, handle: ResultHandle, authorize_read: ReadAuthorizer) -> dict[str, Any]`.
- `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py:20` —
  `ReadAuthorizer = Callable[[SemanticRequestIdentity], Awaitable[None]]`.
- `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py:24, 44-45` —
  `_RAW_TYPE_NAMES = frozenset({"DatasetManager", "AbstractToolkit", "DataFrame"})`;
  `def handle_owner(handle: ResultHandle) -> tuple[str, str, str, str]`.
- `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py:54-70` — `_validate_sink` error codes,
  all `SemanticResultError("sink_rejected", ...)`.
- `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py:73-82` —
  `class GovernedSinkRegistry.__init__(self, max_entries: int = 1024)`; `register(self, sink)`;
  `is_registered(self, sink) -> bool`;
  `async def publish(self, sink, name, handle, authorize_read, *, identity: SemanticRequestIdentity) -> dict[str, Any]`.
- `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py:157-163` —
  `def build_read_authorizer(handle: ResultHandle, *, models: Callable[[], dict[str, LoadedModel]], catalog: Callable[[], RoleCatalog], pbac: PbacGate) -> ReadAuthorizer`.
- `packages/ai-parrot-semantic/src/parrot/semantic/results.py:23-41` —
  `class ResultHandle(BaseModel)` fields: `result_id, agent_id, user_id, tenant_id, session_id,
  subject_digest, model, model_digest, policy_digest, expires_at: datetime,
  members: tuple[str, ...], physical_columns: tuple[str, ...], physical_tables: tuple[str, ...],
  columns: list[str], rows: list[dict[str, Any]], audit_id: str, governed_sql: str`.
  `expires_at` must be timezone-aware.
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:96-98` —
  `self._sink_factory: Callable[[SemanticRequestIdentity], Awaitable[GovernedDatasetSink]] | None = dataset_manager_factory`.
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:546-570` — `save_result_as_dataset`
  raises `SemanticResultError("handoff_unavailable")` without a factory and
  `SemanticResultError("invalid_dataset_name")` on a blank name; it calls `require_identity()`,
  so a context-only binding (no `identity=`) cannot publish.
- wiki page `file:docs/tools/semantic-layer.md` — "A bare `DatasetManager`, dataframe, or plain
  manager factory is rejected… without it the hand-off tool is not exposed."

## Notes
`ResultHandleStore(ttl_s=..., max_entries=...)` is constructed by the toolkit from
`result_ttl_s=900` / `result_store_max=256` (toolkit.py:93) — an example that wants to demo expiry
should set a small `result_ttl_s`. I read only `results.py:1-70`; the store class body was not read.

---

<!-- merged from FW-006 -->
**Query**: Q003/Q012 · **Type**: wiki_query + source read · **Depth**: 1

## Summary
`parrot.semantic.bootstrap.LocalSemanticLayerToolkit` is the stdio/MCP subclass. Unlike the parent
it has an explicit **keyword-only** signature and *requires* `static_subject`, `agent_id` and a
dotted `guard_factory` string. It builds the `PermissionContext` and `SemanticRequestIdentity` itself
(`channel="mcp-local"`, a fresh `uuid4()` session id) and overrides `_create_tool_from_method` so that
every generated tool binds that identity around the call — tool callers cannot supply or override
credentials. Startup fails closed on a malformed subject, a blank `agent_id`, a missing/invalid
`guard_factory`, or missing navigator-auth evaluator modules. It is wired via
`parrot.cli.__init__`'s `"mcp-local": "parrot.mcp.local_cli"` entry plus a
`.parrot/mcp-toolkits.yaml` block, and the HTTP handler explicitly **refuses** it (FW-007).

## Citations
- `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py:60-73` —
  `class LocalSemanticLayerToolkit(SemanticLayerToolkit)` with `local_only = True` and
  `def __init__(self, *, static_subject: StaticSubject | dict[str, Any], agent_id: str, guard_factory: str, guard_factory_kwargs: dict[str, Any] | None = None, **kwargs: Any) -> None`.
- `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py:22-29` —
  `class StaticSubject(BaseModel)`: `user_id: str = Field(min_length=1)`,
  `tenant_id: str = Field(min_length=1)`, `roles: list[str]`,
  `metadata: dict[str, Any] = Field(default_factory=dict)`.
- `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py:100-113` — builds
  `PermissionContext(session=UserSession(user_id=..., tenant_id=..., roles=frozenset(...), metadata=dict(...)), channel="mcp-local")`
  and `SemanticRequestIdentity(ctx=..., channel="mcp-local", agent_id=agent_id, session_id=str(uuid4()))`.
- `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py:128-156` —
  `_build_guard(factory_path, rls_registry, factory_kwargs)`; the host factory is called as
  `factory(rls_registry=rls_registry, **factory_kwargs)` and must return a
  `DataPlanePolicyGuard` with a non-`None` `_evaluator`.
- `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py:16-20, 117-126` —
  `_EVALUATOR_MODULES = ("navigator_auth.abac.policies.environment", "navigator_auth.abac.policies.evaluator")`;
  missing → `SemanticPolicyError("pbac_unavailable")`.
- `packages/ai-parrot/src/parrot/cli/__init__.py:116` — `"mcp-local": "parrot.mcp.local_cli"`.
  The module exists at `packages/ai-parrot/src/parrot/mcp/local_cli.py`.
- wiki page `file:docs/tools/semantic-layer.md` — the exact `.parrot/mcp-toolkits.yaml` block
  (`class: parrot.semantic.bootstrap.LocalSemanticLayerToolkit`, kwargs `models_dir`, `dialect`,
  `agent_id`, `static_subject`, `guard_factory`, `guard_factory_kwargs`) and the matching
  `.mcp.json` entry `{"command": "parrot", "args": ["mcp-local", "semantic-layer"]}`.
- wiki stub `sym:packages/ai-parrot-semantic/tests/test_mcp_local.py#test_documented_yaml_and_json_parse`
  (score=0.99) — the docs blocks are contract-tested, so an example must not diverge from them.

## Notes
`packages/ai-parrot-semantic/tests/test_mcp_local.py` asserts the *documented* fenced blocks parse
and start the real factory. If a new example ships its own YAML it should not be mistaken for the
documented one.

## Notes
[citation-check: stale] packages/ai-parrot-semantic/src/parrot/semantic/handoff.py:46 — actual signature is `def handle_owner(handle: ResultHandle) -> tuple[str, str, str, str]:` (parameter annotated); finding cited it unannotated.
