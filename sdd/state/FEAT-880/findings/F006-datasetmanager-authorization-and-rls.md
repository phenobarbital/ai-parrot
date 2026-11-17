---
id: F006
query_id: Q020, Q021, Q023
type: read
intent: "DatasetManager-side authorization: AuthorizingDataSource wrapper, physical-resource resolver, RLS injection per source type."
executed_at: 2026-11-11T22:12:00Z
duration_ms: 0
parent_id: null
depth: 0
lane_id: FC-006
---

# F006 — DatasetManager has its own PBAC + RLS wrapper, dispatched by source class, fail-open without a context

## Summary

When a `dataplane_guard` is configured, `_make_source` wraps every non-memory source in
`AuthorizingDataSource`, whose `fetch()` resolves the source's physical resources, calls
`guard.authorize_source(ctx, resources)`, collects `guard.rls_predicates(ctx, resources)` and injects
them into a request-scoped copy. Both the resolver and the RLS injector dispatch with `isinstance` on
the concrete source class (`SQLQuerySource`, `TableSource`, `QuerySlugSource`, `MongoSource`); an
unknown class falls to the opaque resolver and gets **no RLS**. With no guard the source is unwrapped,
and with a guard but no `PermissionContext` the wrapper **fails open**. Column masking and member-level
rights do not exist on this side.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 682-714
  symbol: `DatasetManager._make_source`
  excerpt: |
    if self._dataplane_guard is None:
        return source
    if isinstance(source, InMemorySource):
        return source
    return AuthorizingDataSource(inner=source, guard=self._dataplane_guard,
                                 pctx_provider=lambda: _pctx_var.get(None))

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py`
  lines: 103-150
  symbol: `AuthorizingDataSource.fetch`
  excerpt: |
    if driver and self._guard.is_sensitive_driver(driver):
        if not isinstance(self._inner, QuerySlugSource):
            raise AuthorizationRequired(... "only registered query slugs are accepted")
    ctx = self._pctx_provider()
    if ctx is None:
        return await self._inner.fetch(**params)  # fail-open
    resources = resolve_physical_resources(self._inner)
    await self._guard.authorize_source(ctx, resources)
    predicates = await self._guard.rls_predicates(ctx, resources)
    target = self._apply_rls(predicates, resources) if predicates else self._inner

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py`
  lines: 152-262
  symbol: `AuthorizingDataSource._apply_rls`
  excerpt: |
    scoped = request_scoped_copy(self._inner)
    if isinstance(self._inner, SQLQuerySource):
        rewritten_sql, _bound_params = inject_rls_sql(scoped.sql, dialect, predicates)
        scoped.sql = rewritten_sql
    elif isinstance(self._inner, TableSource): inject_rls_table_source(scoped, predicates)
    elif isinstance(self._inner, QuerySlugSource): inject_rls_query_slug(scoped, predicates)
    else: ...  # "non-SQL/Table/Slug/Mongo sources receive no RLS filtering"

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py`
  lines: 120-188
  symbol: `resolve_physical_resources`
  excerpt: |
    if isinstance(source, SQLQuerySource):
        dialect = driver_to_dialect(driver)
        tables = physical_tables(source.sql, dialect)
        return PhysicalResources(driver=driver, tables={f"{driver}:{t}" for t in tables})
    if isinstance(source, TableSource): ...
    if isinstance(source, QuerySlugSource):
        return PhysicalResources(source_type="query_slug", source_id=f"{source.tenant or 'public'}:{source.slug}")
    # Opaque sources ... resolve_opaque_source(source)

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py`
  lines: 47-62
  symbol: `PhysicalResources`
  excerpt: |
    class PhysicalResources(BaseModel):
        driver: Optional[str] = None
        tables: set[str] = Field(default_factory=set)
        source_type: Optional[str] = None
        source_id: Optional[str] = None

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/rls.py`
  lines: 72-243
  symbol: `inject_rls_sql`
  excerpt: |
    def inject_rls_sql(
    def inject_rls_table_source(
    def inject_rls_query_slug(
    def inject_rls_mongo(
    def inject_rls_postfetch(

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/dialects.py`
  lines: 41-71
  symbol: `driver_to_dialect`
  excerpt: |
    from parrot.tools.databasequery.sources import normalize_driver
    canonical = normalize_driver(driver)
    return _DRIVER_DIALECT_MAP.get(canonical)

## Notes

- Two governance stacks exist over the **same** `DataPlanePolicyGuard` and the same
  `PhysicalResources` type (the semantic package imports `PhysicalResources` from this resolver,
  `handoff.py:11`): the DatasetManager one (PBAC + RLS, fail-open on missing context, no masking) and
  the semantic one (PBAC + usage rights + RLS + masking + positive guard + audit, fail-closed).
- If a semantic dataset were registered as a plain `SQLQuerySource` holding compiled (pre-governance)
  SQL, it would get DatasetManager's PBAC and guard-level RLS only when a guard *and* a context are
  present — and never the policy file's masks, `usage:` grants, model-level RLS rules, limits or audit.
- If instead it were a new `SemanticSource` class, `resolve_physical_resources` would send it to the
  opaque resolver and `_apply_rls` would skip it, unless both are extended — or the source does its own
  governance by calling the semantic pipeline and is deliberately *not* double-wrapped.
- The "sensitive driver" pre-check (authorizing.py:103-118) rejects every non-`QuerySlugSource` on a
  sensitive driver; a semantic source on such a driver would be refused unless that rule is widened.
- `rls.py` was inspected for its function inventory only (lines of `def`), not read in full.
