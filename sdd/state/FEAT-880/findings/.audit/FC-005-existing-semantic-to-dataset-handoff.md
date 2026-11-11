---
id: FC-005
query_id: Q018, Q019, Q032
type: read
intent: "Existing semantic -> DatasetManager hand-off contract (handoff.py, toolkit._dataset_manager_for, dataset_manager_factory) and what its tests guarantee."
executed_at: 2026-11-11T22:12:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-005 — The existing hand-off is push-only, per-owner, and explicitly rejects a raw DatasetManager

## Summary

Today the only bridge runs semantic → dataset: `save_result_as_dataset(result_id, name)` publishes an
already-governed, already-executed result (`ResultHandle`) into a host-supplied `GovernedDatasetSink`.
The sink is produced per request by `dataset_manager_factory(identity)`, must declare
`guarded_reads = True`, a `scope_id`, and an `owner` 4-tuple `(agent, user, tenant, session)` equal to
the caller's; `_validate_sink` rejects any object whose class lineage contains `DatasetManager`,
`AbstractToolkit` or `DataFrame`. Every later exposure must call a `ReadAuthorizer` that re-checks
identity, subject digest, expiry, model/policy digests, member visibility, column usage grants and
PBAC. Nothing in the hand-off lets a `DatasetManager` *pull* from the semantic layer.

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

## Notes

- The hand-off's stated invariants — results are owned by one `(agent, user, tenant, session)`, are
  never exposed through a raw or shared `DatasetManager`, expire, and are re-authorized on every read —
  are the security posture a pull-direction `add_semantic` must not undercut. A semantic dataset
  registered on a shared `DatasetManager`, materialized once into `entry._df` and served from there (or
  from the Redis Parquet cache, FC-002) would bypass every one of them for governed models.
- The sink factory name is historical: `dataset_manager_factory` yields a `GovernedDatasetSink`, not a
  `DatasetManager`.
- No production implementation of `GovernedDatasetSink` was found in the codebase lane's reads (only the
  Protocol and test doubles). [cross-lane: type=wiki_query, intent=is there a shipped GovernedDatasetSink adapter over DatasetManager, or only test/example doubles?]
