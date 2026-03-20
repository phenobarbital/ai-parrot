# TASK-370: CRON Refresh Pipeline — Delta Sync

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (3-5h)
**Depends-on**: TASK-359, TASK-363, TASK-365, TASK-367
**Assigned-to**: —

---

## Context

> CRON-triggered pipeline that keeps the ontology graph in sync with source data.
> Performs delta sync: extract, diff, upsert, rediscover edges, sync vectors, invalidate cache.
> Implements spec Module 15.

---

## Scope

### Create `parrot/knowledge/ontology/refresh.py`

`OntologyRefreshPipeline`:
- `__init__(self, tenant_manager, graph_store, discovery, datasource_factory, cache, vector_store=None, source_configs=None)`.
- `async run(self, tenant_id: str) -> RefreshReport`:
  1. Resolve tenant context.
  2. For each entity with a `source`:
     a. **Extract**: Use `DataSourceFactory.get()` to get source, call `extract()`.
     b. **Diff**: `_compute_diff(new_data, existing, key_field)` — O(n+m) via dict lookup.
     c. **Apply**: Upsert changed/new nodes, soft-delete removed.
     d. **Rediscover**: Re-run `RelationDiscovery.discover()` for changed nodes only.
     e. **Sync vectors**: Embed changed vectorizable fields to PgVector (if vector_store provided).
  3. **Invalidate**: Bust Redis cache for tenant. Invalidate tenant manager cache.
  4. Return `RefreshReport`.

`_compute_diff(new_data, existing, key_field) -> DiffResult`:
- `to_add`: in new but not existing.
- `to_update`: in both but values differ.
- `to_remove`: in existing but not new.

`DiffResult(BaseModel)`: `to_add`, `to_update`, `to_remove` (all `list[dict]`).

`RefreshReport(BaseModel)`:
- `tenant: str`
- `started_at: datetime`
- `completed_at: datetime | None`
- `entity_results: dict[str, UpsertResult]`
- `discovery_results: dict[str, DiscoveryStats]`
- `errors: list[str]`

---

## Acceptance Criteria

- [ ] Delta sync: only changed nodes are upserted.
- [ ] Removed nodes are soft-deleted (not hard deleted).
- [ ] Edge rediscovery runs only for changed/new nodes.
- [ ] PgVector sync only for nodes with changed vectorizable fields.
- [ ] Cache invalidated after refresh.
- [ ] `RefreshReport` contains accurate counts and timing.
- [ ] Uses `DataSourceFactory` to resolve entity sources.
- [ ] Unit tests: diff computation, full pipeline with mocked stores.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/ontology/refresh.py` | **Create** |
| `tests/knowledge/test_ontology_refresh.py` | **Create** |
