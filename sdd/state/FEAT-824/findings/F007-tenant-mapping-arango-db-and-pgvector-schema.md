---
id: F007
query_id: Q007
type: read
intent: "How does ontology multi-tenancy map tenants to databases/graphs (candidate mapping to Postgres schema / Surreal namespace)?"
executed_at: 2026-11-06T13:38:00Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-007]
---

# F007 — Tenancy: one ArangoDB database + one pgvector schema per tenant, both name-templated; `arango_db` is a field of the neutral TenantContext

## Summary

`TenantOntologyManager` resolves a tenant into a `TenantContext(tenant_id, arango_db, pgvector_schema, ontology)`. The names come from two templates: `ONTOLOGY_DB_TEMPLATE` (default `"{tenant}_ontology"`) and `ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE` (default `"{tenant}"`), read from `parrot/conf.py`. The ontology itself is assembled per tenant from a YAML chain (base file → `domains/` → `clients/`) plus optional concept and schema overlays. **`TenantContext.arango_db` is a required field** of the model every store method receives (`ctx`), so the Arango name is baked into the "backend-neutral" contract's parameter type. A replacement would map naturally to "one Postgres schema per tenant" / "one Surreal database per tenant", but needs the field renamed or generalised (e.g. `graph_db`).

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 531-546
  symbol: `TenantContext`
  excerpt: |
    class TenantContext(BaseModel):
        """Runtime context for a specific tenant.
            tenant_id: Unique tenant identifier.
            arango_db: ArangoDB database name for this tenant.
            pgvector_schema: PgVector schema name for this tenant.
        tenant_id: str
        arango_db: str
        pgvector_schema: str
        ontology: MergedOntology

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py`
  lines: 60-83
  symbol: `TenantOntologyManager.__init__`
  excerpt: |
    67:                ONTOLOGY_DB_TEMPLATE,
    68:                ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE,
    75:            ONTOLOGY_DB_TEMPLATE = "{tenant}_ontology"
    76:            ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE = "{tenant}"
    82:        self._db_template = db_template or ONTOLOGY_DB_TEMPLATE or "{tenant}_ontology"
    83:        self._pgvector_template = pgvector_schema_template or ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE or "{tenant}"

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py`
  lines: 92-264
  symbol: `TenantOntologyManager.resolve` / `resolve_with_overlay`
  excerpt: |
    167:            arango_db=self._db_template.format(tenant=tenant_id),
    168:            pgvector_schema=self._pgvector_template.format(tenant=tenant_id),
    208:    async def resolve_with_overlay(
    263:            arango_db=self._db_template.format(tenant=tenant_id),
    264:            pgvector_schema=self._pgvector_template.format(tenant=tenant_id),

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 151-154
  symbol: `ONTOLOGY_DB_TEMPLATE`
  excerpt: |
    151:ONTOLOGY_DB_TEMPLATE = config.get("ONTOLOGY_DB_TEMPLATE", fallback="{tenant}_ontology")
    154:ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE = config.get("ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE", fallback="{tenant}")

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 84-100
  symbol: `ArangoOntologyGraphStore._get_db`
  excerpt: |
    # Use the tenant's database
    await self._client.use(ctx.arango_db)
    return self._client

## Notes

- `tenant.py` was scanned by `grep -nE` (375 lines; not read in full). Other methods seen: `invalidate` L183, `list_tenants` L198, `_build_yaml_chain` L280, `_build_concept_overlay` L312, `_build_schema_overlay` L338.
- The draft's topology (`NAMESPACE` = tenant/team, `DATABASE` = knowledge domain; `ontology_id` as named graph) is a *different axis* from today's tenant axis: today there is no per-domain database, the domain is a YAML layer merged into the tenant's single ontology.
- pgvector is already the tenant's vector plane for ontology entities (`vectorize` fields → `pgvector_schema`), i.e. the ontology subsystem is *already* an Arango + Postgres hybrid.
