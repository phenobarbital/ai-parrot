# FW-005 — `GovernedDatasetSink` is a `runtime_checkable` Protocol with three attributes and one async `publish`

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
