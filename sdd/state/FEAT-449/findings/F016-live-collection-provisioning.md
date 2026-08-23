---
id: F016
query_id: Q022,Q024
type: grep
intent: Audit how a tenant is provisioned and whether collections can be added to a live tenant
executed_at: 2026-08-23T00:41:06Z
depth: 2
parent_id: F002
---

# F016 — Collections can be added to a live tenant idempotently; tenant DB naming is a configurable template

## Summary

`OntologyGraphStore.ensure_collection` creates a vertex or edge collection on demand
(`create_collection(name, edge=True)`) and swallows the already-exists case, so adding legal
collections to an existing tenant does not require a rebuild. `initialize_tenant` provisions
the full set from the ontology's entity/relation defs. `TenantOntologyManager` builds the
database name from a template (`self._db_template.format(tenant=tenant_id)`), not a hard-coded
`db_` prefix, and exposes `list_tenants`, `invalidate`, and `resolve_with_overlay` plus YAML-
chain and concept/schema overlay builders. Tenant-per-materia is therefore cheap and the
schema is layerable — this materially lowers the migration risk behind claim C15.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 462-488
  symbol: `ensure_collection`
  excerpt: |
    async def ensure_collection(
                    await db.create_collection(name, edge=True)
                    await db.create_collection(name)
            logger.debug("ensure_collection('%s') skipped: %s", name, e)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 71, 101, 122
  symbol: `initialize_tenant`
  excerpt: |
    async def initialize_tenant(self, ctx: TenantContext) -> None:
                    await db.create_collection(entity.collection)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py`
  lines: 29, 92, 167, 198, 208, 280-338
  symbol: `TenantOntologyManager`
  excerpt: |
    class TenantOntologyManager:
        arango_db=self._db_template.format(tenant=tenant_id),
    def list_tenants(self) -> list[str]:
    async def resolve_with_overlay(
    def _build_yaml_chain(
    def _build_concept_overlay(
    def _build_schema_overlay(

## Notes

Downgrades the severity of the "wrong multiplicity choice = migrate everything" risk: the
per-collection provisioning is incremental and idempotent.
