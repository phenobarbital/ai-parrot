---
id: FC-004
query_id: Q017, Q019, Q027
type: read
intent: "GovernancePipeline.govern and the toolkit's governed path: what compiled SQL must pass before execution; what governed:false relaxes."
executed_at: 2026-11-11T22:12:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-004 — The governed path is manifest-PBAC → rights → compile → govern → execute → audit; `governed: false` only skips PBAC

## Summary

`SemanticLayerToolkit._run_governed` is the single path that turns a `SemanticQuery` into rows:
manifest PBAC, saved-query expansion, member-rights check, compile, `GovernancePipeline.govern`
(read-only validation → qualification → PBAC → column-usage lineage → RLS push-down → masking →
positive guard / limit cap), execution through `Executor`, and an audit entry on every outcome. It
needs a trusted `PermissionContext` (`current_pctx()`, fails closed with `context_required`), the
subject's roles, a `PbacGate` wrapping a host `DataPlanePolicyGuard`, an `RlsRegistry` and an audit
ledger. `governed: false` on a policy makes `PbacGate.authorize` return early and lifts the
"connection required" rule; usage rights, RLS, masking and the positive guard still run inside
`_finish`. `compile_query` is the toolkit's compile-only tool and it still runs the whole governed
path minus execution.

## Citations

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 289-328
  symbol: `SemanticLayerToolkit._run_governed`
  excerpt: |
    context = self._context()
    roles = frozenset(context.roles)
    await self._pbac.authorize_manifest(context, loaded)
    expanded = self._catalog.expand_saved_query(query)
    self._catalog.check_query_rights(expanded, roles)
    compiled = await compile_query_sql(expanded, loaded, self._dialect, cache=self._cache)
    governed = await self._pipeline.govern(compiled.sql, model=loaded, ctx=context, roles=roles)
    if not execute:
        return {"sql": compiled_sql, "audit_id": audit_id, "members": list(governed.members)}
    rows, row_count, truncated, duration_ms, columns = await self._executor.run_with_columns(
        governed, connection=loaded.policy.connection)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 273-278
  symbol: `SemanticLayerToolkit._context`
  excerpt: |
    context = current_pctx()
    if context is None:
        raise SemanticAccessError("context_required", "A trusted semantic context is required")

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 195-198
  symbol: `SemanticLayerToolkit.compile_query`
  excerpt: |
    async def compile_query(self, query: SemanticQuery) -> dict:
        """Return audited pre-RLS compiled SQL without database execution; governed SQL stays in the audit."""
        result = await self._run_governed(query, execute=False)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py`
  lines: 152-188
  symbol: `GovernancePipeline.govern`
  excerpt: |
    async def govern(self, sql: str, *, model: LoadedModel, ctx: PermissionContext | None,
                     roles: frozenset[str]) -> GovernedQuery:
        """... Order: negative validation → qualification → resource subset/PBAC →
        usage lineage → RLS → masking → positive guard → render."""
        digest = subject_digest(ctx)
        dialect = _dialect_for(model.schema.driver)
        prepared = await asyncio.to_thread(self._prepare, sql, model, dialect)
        await self.pbac.authorize(ctx, prepared.resources, governed=model.policy.governed, manifest=manifest)
        return await asyncio.to_thread(self._finish, prepared, model, ctx, roles, dialect, digest)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py`
  lines: 215-286
  symbol: `GovernancePipeline._finish`
  excerpt: |
    enforce_usage_rights(prepared.uses, policy, roles, trusted_nodes=trusted)
    if ctx is None:
        if self.rls.registry.lookup(model.schema.driver, set(tables)):
            raise SemanticAccessError("no_subject", "Row-level rules require a permission context")
    else:
        tree, rls_applied, rls_nodes = bound.apply(tree, ctx, model.schema.driver)
    tree, masked, mask_nodes = apply_masks(tree, prepared.uses, policy, roles, dialect)
    tree = guard.check_and_limit(tree, trusted_nodes=trusted)
    tree.limit(limit + 1, copy=False)   # one probe row past the cap for truncation reporting

- path: `packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py`
  lines: 63-100
  symbol: `PbacGate.authorize`
  excerpt: |
    if not governed:
        return
    if ctx is None:
        raise SemanticAccessError("no_subject", "A governed query requires a permission context")
    if not self.available or self.guard is None:
        raise SemanticAccessError("pbac_unavailable", "The PBAC evaluator is unavailable")
    ...
    await self.guard.authorize_source(ctx, resources)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/policy.py`
  lines: 143-148
  symbol: `load_policy`
  excerpt: |
    policy = ModelPolicy.model_validate(raw)
    ...
    if policy.governed and not policy.connection:
        raise SemanticPolicyError("invalid_policy", "Governed policies require a connection")

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 44-100
  symbol: `SemanticLayerToolkit.__init__`
  excerpt: |
    models_dir = Path(kwargs.pop("models_dir")); dialect = str(kwargs.pop("dialect"))
    dataplane_guard = kwargs.pop("dataplane_guard", None)
    ...
    if any(model.policy.governed for model in self._models.values()) and dataplane_guard is None:
        raise SemanticPolicyError("guard_required", "Governed semantic models require a data-plane guard")
    self._executor = Executor(database_toolkit or DatabaseQueryToolkit(), ConnectionResolver())

## Notes

- `GovernedQuery.sql` is what gets executed; it carries the RLS literals and the `limit + 1` probe row.
  The toolkit never hands governed SQL to callers — `compile_query` returns the *pre-RLS* SQL and keeps
  the governed SQL in the audit entry only (toolkit.py:311-313). Handing compiled-but-ungoverned SQL to
  another executor is therefore exactly the thing the current design avoids.
- The executor trims to `governed.limit` rows and reports `truncated` (execution.py:84-86, read earlier
  in this session). Any other executor of governed SQL must drop the probe row itself.
- The same `DataPlanePolicyGuard` type backs both the semantic `PbacGate` and DatasetManager's
  `AuthorizingDataSource` (see FC-006).
- Even for `governed: false`, a `ctx is None` call fails if any RLS rule is registered for the tables.
