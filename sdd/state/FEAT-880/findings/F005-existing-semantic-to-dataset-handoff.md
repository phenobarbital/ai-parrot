---
id: F005
query_id: Q018, Q019, Q032
type: read
intent: "Existing semantic -> DatasetManager hand-off contract (handoff.py, toolkit._dataset_manager_for, dataset_manager_factory) and what its tests guarantee."
executed_at: 2026-11-11T22:12:00Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-005, FW-003]
---

# F005 — The existing hand-off is push-only, per-owner, and explicitly rejects a raw DatasetManager + The semantic→DatasetManager hand-off (M9H) deliberately rejects a bare DatasetManager: governed rows may only land in a host `GovernedDatasetSink` that re-authorizes every read

## Summary

[FC-005] Today the only bridge runs semantic → dataset: `save_result_as_dataset(result_id, name)` publishes an
already-governed, already-executed result (`ResultHandle`) into a host-supplied `GovernedDatasetSink`.
The sink is produced per request by `dataset_manager_factory(identity)`, must declare
`guarded_reads = True`, a `scope_id`, and an `owner` 4-tuple `(agent, user, tenant, session)` equal to
the caller's; `_validate_sink` rejects any object whose class lineage contains `DatasetManager`,
`AbstractToolkit` or `DataFrame`. Every later exposure must call a `ReadAuthorizer` that re-checks
identity, subject digest, expiry, model/policy digests, member visibility, column usage grants and
PBAC. Nothing in the hand-off lets a `DatasetManager` *pull* from the semantic layer.

[FW-003] The existing direction (semantic result → dataset) is `save_result_as_dataset`, exposed only when the
host passes `dataset_manager_factory`, an async callable `(SemanticRequestIdentity) -> GovernedDatasetSink`.
The sink is a `runtime_checkable` Protocol (`scope_id`, immutable 4-tuple `owner`, `guarded_reads=True`,
async `publish(name, handle, authorize_read)`). `_validate_sink` rejects anything whose MRO contains
`DatasetManager`, `AbstractToolkit` or `DataFrame`; there is no default session-manager adapter. The
documented rationale (TASK-4709, M9H): a retained snapshot of governed rows must stay governed — every
list/metadata/sample/cache/query/export/derived read re-invokes `authorize_read` with the *current*
caller identity, and "automatic semantic authorization in `DatasetManager.add_dataframe()`" is listed
under Does-NOT-Exist. The sanctioned ungoverned surfaces are a policy with `governed: false` and
`sl_compile_query`, which returns compiled SQL without executing it.

## Citations

- path: `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py`
  lines: 33-43
  symbol: `GovernedDatasetSink`
  excerpt: |
    @runtime_checkable
    class GovernedDatasetSink(Protocol):
        scope_id: str
        owner: tuple[str, str, str, str]
        guarded_reads: Literal[True]
        async def publish(self, name: str, handle: ResultHandle, authorize_read: ReadAuthorizer) -> dict[str, Any]:
            """Publish privately without exposing an unguarded manager or source."""

- path: `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py`
  lines: 25-71
  symbol: `_validate_sink`
  excerpt: |
    _RAW_TYPE_NAMES = frozenset({"DatasetManager", "AbstractToolkit", "DataFrame"})
    def _validate_sink(sink: object) -> None:
        if _is_raw_target(sink):
            raise SemanticResultError("sink_rejected", "Raw or shared dataset managers are not guarded sinks")
        if getattr(sink, "guarded_reads", None) is not True:
            raise SemanticResultError("sink_rejected", "Sink does not declare guarded reads")

- path: `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py`
  lines: 120-156
  symbol: `GovernedSinkRegistry.publish`
  excerpt: |
    if not self.is_registered(sink): raise SemanticResultError("sink_rejected", "Sink is not registered")
    if sink.owner != handle_owner(handle): raise ...
    if (identity.agent_id, identity.ctx.user_id, identity.ctx.tenant_id, identity.session_id) != sink.owner:
        raise _deny()
    await authorize_read(identity)
    result = await sink.publish(name, handle, authorize_read)
    if not isinstance(result, dict) or any(_is_raw_target(value) for value in result.values()):
        raise SemanticResultError("sink_rejected", "Sink returned an unguarded object")

- path: `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py`
  lines: 159-247
  symbol: `build_read_authorizer`
  excerpt: |
    if (snapshot.agent_id != identity.agent_id or snapshot.user_id != ctx.user_id
        or snapshot.tenant_id != ctx.tenant_id or snapshot.session_id != identity.session_id
        or snapshot.subject_digest != subject_digest(ctx)):
        raise _deny()
    if snapshot.expires_at <= datetime.now(timezone.utc): raise _deny()
    loaded = _current(models())   # model_digest and policy_digest must still match
    if loaded.policy.governed: ... await pbac.authorize(ctx, PhysicalResources(driver=driver, tables=tables), governed=True)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 546-592
  symbol: `SemanticLayerToolkit.save_result_as_dataset`
  excerpt: |
    if self._sink_factory is None:
        raise SemanticResultError("handoff_unavailable", "Dataset hand-off is not configured")
    identity = require_identity()
    handle, loaded = self._claim(result_id, identity, context)
    await self._recheck_handle(handle, loaded, context, roles)
    sink = await self._dataset_manager_for(identity)
    authorize_read = build_read_authorizer(handle, models=lambda: self._models, catalog=lambda: self._catalog, pbac=self._pbac)
    published = await self._sinks.publish(sink, name, handle, authorize_read, identity=identity)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 772-781
  symbol: `SemanticLayerToolkit._dataset_manager_for`
  excerpt: |
    produced = self._sink_factory(identity)
    sink = await produced if inspect.isawaitable(produced) else produced
    if getattr(sink, "owner", None) != handle_owner_of(identity):
        raise SemanticResultError("sink_rejected", "Sink owner does not match the trusted identity")
    self._sinks.register(sink)

- path: `packages/ai-parrot-semantic/tests/test_e2e_handoff.py`
  lines: 161-429
  symbol: `test_handoff_publishes_through_guarded_sink`
  excerpt: |
    async def test_handoff_publishes_through_guarded_sink(
    async def test_unrelated_visible_member_does_not_authorize_handle(
    async def test_shared_scope_and_raw_manager_rejected(
    async def test_guarded_sink_read_after_revocation(
    async def test_fresh_sink_per_call_same_owner(

- path: `packages/ai-parrot-semantic/tests/test_handoff_contract.py`
  lines: 99-213
  symbol: `test_exact_provenance_and_scope_rejection`
  excerpt: |
    async def test_exact_provenance_and_scope_rejection(tmp_path: Path) -> None:
    async def test_every_exposure_revocation_and_expiry(tmp_path: Path) -> None:
    async def test_cached_derived_inheritance_and_reload_race(tmp_path: Path) -> None:
    async def test_read_rechecks_column_usage_grants() -> None:

- wiki: `file:sdd/state/FEAT-769/findings/F008-construction-and-surface-contracts.md` (Q007 score=0.42), `file:sdd/tasks/completed/TASK-4709-semantic-guarded-dataset-sink.md` (score=0.10), `file:wiki/tools/semantic-layer.md` (score=0.11), `sym:packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py#SemanticLayerToolkit._dataset_manager_for` (score=1.00), `sym:packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py#SemanticLayerToolkit.save_result_as_dataset` (score=0.33)

- path: `wiki/tools/semantic-layer.md`
  lines: 100-112
  symbol: `Guarded dataset hand-off`
  excerpt: |
    ## Guarded dataset hand-off
    A bare `DatasetManager`, dataframe, or plain manager factory is rejected. The
    host adapter must declare guarded reads, immutable owner scope, async publish,
    and pass the sink conformance tests; without it the hand-off tool is not

- path: `wiki/tools/semantic-layer.md`
  lines: 46
  symbol: `Authorization and identity`
  excerpt: |
    request. Only a policy with `governed: false` opts out explicitly.

- path: `wiki/tools/semantic-layer.md`
  lines: 81-88
  symbol: `Tools and audit`
  excerpt: |
    | `sl_compile_query` | `compile_query(query: SemanticQuery)` |
    `allow_raw_sql: true` enables it; it still uses model-manifest authorization,

- path: `wiki/tools/semantic-layer.md`
  lines: 184
  symbol: `Example agents`
  excerpt: |
    `models_ungoverned/`, which serves as the compiler surface for ad-hoc analysis.

- path: `sdd/tasks/completed/TASK-4709-semantic-guarded-dataset-sink.md`
  lines: 18-21
  symbol: `Scope`
  excerpt: |
    - Implement GovernedDatasetSink protocol: scope_id, immutable owner tuple, guarded_reads=True and async publish(name, handle, authorize_read). Reject raw/shared DatasetManager targets; no default session-manager adapter.
    - Capability flags alone are not proof. [...] No unguarded manager, source, dataframe reference or alternate endpoint may escape. Callback uses current caller identity, never captured original context.

- path: `sdd/tasks/completed/TASK-4709-semantic-guarded-dataset-sink.md`
  lines: 87
  symbol: `Does NOT Exist`
  excerpt: |
    - Automatic semantic authorization in `DatasetManager.add_dataframe()` — retained snapshots require the guarded host-sink contract.

## Notes

[FC-005]
- The hand-off's stated invariants — results are owned by one `(agent, user, tenant, session)`, are
  never exposed through a raw or shared `DatasetManager`, expire, and are re-authorized on every read —
  are the security posture a pull-direction `add_semantic` must not undercut. A semantic dataset
  registered on a shared `DatasetManager`, materialized once into `entry._df` and served from there (or
  from the Redis Parquet cache, FC-002) would bypass every one of them for governed models.
- The sink factory name is historical: `dataset_manager_factory` yields a `GovernedDatasetSink`, not a
  `DatasetManager`.
- No production implementation of `GovernedDatasetSink` was found in the codebase lane's reads (only the
  Protocol and test doubles). [cross-lane: type=wiki_query, intent=is there a shipped GovernedDatasetSink adapter over DatasetManager, or only test/example doubles?]

[FW-003]
- The two `handoff.py` entries are quoted from FEAT-769 F008 (2026-10-29), **not re-read in this lane**.
  [cross-lane: type=read, intent=re-verify handoff.py line ranges for GovernedDatasetSink, _RAW_TYPE_NAMES, _validate_sink and build_read_authorizer on current dev]
- Design tension for FEAT-880: an `add_semantic` on a plain DatasetManager that materializes governed
  rows into `_df` and the shared Redis cache is precisely the "retained snapshot in a raw manager" that
  M9H forbids. A compliant design must (a) restrict the semantic source to `governed: false` models,
  or (b) compile + govern per fetch under the caller's identity and never cache across subjects, or
  (c) reuse the sink / `authorize_read` contract on the DatasetManager side.
- No wiki `decision` page records the M9H rationale; it lives in the FEAT-704 spec and TASK-4709 only.
- An example already wraps a private DatasetManager behind a guarded facade
  (`sym:examples/agents/semantic/agent_semantic_example.py#GuardedDatasetFacade`, score=0.08).
