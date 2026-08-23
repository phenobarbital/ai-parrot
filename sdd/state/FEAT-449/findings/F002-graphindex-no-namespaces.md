---
id: F002
query_id: Q002
type: grep
intent: Establish whether GraphIndex supports multiple namespaces over shared collections (closes OQ1)
executed_at: 2026-08-23T00:20:22Z
depth: 0
parent_id: null
---

# F002 — GraphIndex has NO namespace concept; isolation is one ArangoDB database per tenant

## Summary

A case-insensitive grep for "namespace" across the whole `knowledge/graphindex/` package
returns exactly **one** hit, and it is an unrelated comment about a Python PEP-420 namespace
package. There is no namespace attribute, no namespace filter, and no multi-graph
discriminator anywhere in GraphIndex. The isolation unit that *does* exist is
`TenantContext`, which carries a distinct **ArangoDB database name** (`arango_db`) and a
distinct pgvector schema per tenant — `factory.py` builds it as `arango_db=f"db_{tenant_id}"`.
This directly contradicts the source's OQ1 "Closed" decision (single Arango DB, namespaces
over shared collections, tenancy as a second discriminator).

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/export_html.py`
  lines: 435
  excerpt: |
    the parrot.outputs.formats.assets namespace package.
  # ^ the ONLY "namespace" hit in the entire graphindex package

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 406-421
  symbol: `TenantContext`
  excerpt: |
    class TenantContext(BaseModel):
        tenant_id: str
        arango_db: str
        pgvector_schema: str
        ontology: MergedOntology

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py`
  lines: 49-68
  excerpt: |
        full hydration is only needed for ArangoDB/ontology deployments.
        arango_db=f"db_{tenant_id}",

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py`
  lines: 1-26
  excerpt: |
    Writes assembled graph nodes and edges to ArangoDB via
    OntologyGraphStore and embeddings to pgvector.
    Commits live in two per-tenant collections:

## Notes

Spawned follow-up F003 (is the collection vocabulary extensible?) and F004 (tenant ontology
merging). Also relevant: commit `de08ac3e2` reserved FEAT-450 for "wiki-namespaces" minutes
after this run started — possible overlapping work on exactly this gap.
