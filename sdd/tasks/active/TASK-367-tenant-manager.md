# TASK-367: Tenant Ontology Manager

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2h)
**Depends-on**: TASK-362, TASK-363
**Assigned-to**: —

---

## Context

> Multi-tenant YAML resolution and caching. Resolves the merged ontology for each tenant
> using the three-layer YAML chain. Implements spec Module 14.

---

## Scope

### Create `parrot/knowledge/ontology/tenant.py`

`TenantOntologyManager`:
- `__init__(self)` — initialize in-memory cache `_cache: dict[str, TenantContext]`.
- `resolve(self, tenant_id: str, domain: str = None) -> TenantContext`:
  1. Check `_cache` for tenant.
  2. Build YAML chain: `[ONTOLOGY_DIR / ONTOLOGY_BASE_FILE]` + optional `domain.ontology.yaml` + optional `tenant.ontology.yaml`.
  3. Merge via `OntologyMerger.merge(chain)`.
  4. Build `TenantContext` with `arango_db` (from `ONTOLOGY_DB_TEMPLATE.format(tenant=tenant_id)`) and `pgvector_schema` (from `ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE.format(tenant=tenant_id)`).
  5. Cache and return.
- `invalidate(self, tenant_id: str = None)` — clear specific tenant or all.
- `list_tenants(self) -> list[str]` — return cached tenant IDs.

---

## Acceptance Criteria

- [ ] `resolve()` returns `TenantContext` with correct `arango_db` and `pgvector_schema`.
- [ ] YAML chain: base is always first, domain is optional, client is optional.
- [ ] Missing domain/client YAML files are silently skipped (not errors).
- [ ] Second `resolve()` returns cached result.
- [ ] `invalidate()` clears specific tenant or all.
- [ ] Config values from `parrot/conf.py` are used for paths and templates.
- [ ] Unit tests: resolve, cache hit, invalidation.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/ontology/tenant.py` | **Create** |
| `tests/knowledge/test_ontology_tenant.py` | **Create** |
