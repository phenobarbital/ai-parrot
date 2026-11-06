---
id: F027
query_id: Q207
type: wiki_page
intent: "What the ontological graph RAG spec fixed as the ontology model and store contract"
executed_at: 2026-11-06T13:29:04Z
duration_ms: 2500
parent_id: null
depth: 0
merged_from: [FW-007]
---

# F027 — FEAT-053 fixed the ontology as composable **YAML** (base → domain → client) over per-tenant ArangoDB databases, queried by AQL traversal patterns — not RDF/Turtle/IRI

## Summary

`ontological-graph-rag.spec.md` (FEAT-053, approved 2026-03-19) defines "Graph-First RAG": the ontology is three merged YAML layers validated by Pydantic; each tenant gets its **own ArangoDB database and PgVector schema**; `OntologyIntentResolver` maps a query to a declared traversal pattern or to **LLM-generated dynamic AQL**; `OntologyGraphStore.execute_traversal(aql, bind_vars)` runs it after a read-only/depth-limit safety validation; post-actions route to PgVector search or tool calls; a CRON `OntologyRefreshPipeline` delta-syncs **instance data** (employees, projects, portals) from data sources and discovers edges. The graph therefore stores *entity instances and their relations* (an LPG of business records), which is a different thing from the draft's OntologyStore of *classes / properties / SKOS concepts with transitive closure*. The draft's data model (Turtle source, IRIs, `resolve`/`expand`) has no counterpart in this spec.

## Citations

- path: `sdd/specs/ontological-graph-rag.spec.md`
  symbol: `§1 Goals`
  wiki_page_id: file:sdd/specs/ontological-graph-rag.spec.md
  score: n/a (direct wiki_page)
  excerpt: |
    - **Composable Ontology YAMLs**: Three-layer system (base → domain → client) with strict Pydantic validation
      and deterministic merge rules.
    - **Multi-Tenant Isolation**: Each tenant gets its own ArangoDB database and PgVector schema.
    - **Dual-Path Intent Resolution**: Fast-path keyword matching (~0ms) + LLM-based classification.
    - **Relation Discovery Engine**: Automatic edge creation from data sources (exact, fuzzy, AI-assisted, composite).
    - **Agent Mixin Integration**: `OntologyRAGMixin` — agents opt-in via inheritance, hooks into `ask()` flow.
    - **CRON Refresh Pipeline**: Delta sync from data sources with cache invalidation.

- path: `sdd/specs/ontological-graph-rag.spec.md`
  symbol: `§2 Component Diagram`
  wiki_page_id: file:sdd/specs/ontological-graph-rag.spec.md
  excerpt: |
    ├── 1. TenantOntologyManager.resolve(tenant_id) └── OntologyMerger.merge([base, domain, client])
    ├── 2. OntologyIntentResolver.resolve(query, user_context)
    │     ├── Fast path: keyword scan against trigger_intents
    │     └── LLM path: structured output → pattern or dynamic AQL
    ├── 3. OntologyGraphStore.execute_traversal(aql, bind_vars)
    │     └── AQL validated for safety (read-only, depth-limited)
    ├── 4. Post-action routing: vector_search → PgVector query with graph context | tool_call | none
    └── 5. Cache result (Redis, TTL = ONTOLOGY_CACHE_TTL)
    CRON: OntologyRefreshPipeline — DataSourceFactory → Diff → Upsert nodes → RelationDiscovery → Sync PgVector → Invalidate cache

- path: `sdd/specs/ontological-graph-rag.spec.md`
  symbol: `§2 Integration Points`
  wiki_page_id: file:sdd/specs/ontological-graph-rag.spec.md
  excerpt: |
    | `parrot/conf.py` | Modified | Add 12 ONTOLOGY_* config variables |
    | `parrot/stores/arango.py` (`ArangoDBStore`) | Consumed | Existing ArangoDB client, extend with ontology-specific methods |
    | `parrot/stores/pgvector.py` (`PgVectorStore`) | Consumed | Vector search with graph context |
    | Redis (existing) | Consumed | Cache full pipeline results |

- path: `sdd/specs/ontological-graph-rag.spec.md`
  symbol: `§1 Non-Goals`
  wiki_page_id: file:sdd/specs/ontological-graph-rag.spec.md
  excerpt: |
    - Real-time streaming graph updates — CRON-based delta sync only.
    - Graph visualization or exploration UI.
    - Building a UI for the review queue — JSON log files only.

## Notes

- Mismatch to resolve in the proposal: the existing ontology subsystem is **schema-in-YAML + instance graph in Arango + AQL patterns**; the draft is **schema-as-RDF in Postgres with no instance graph at all** (instances/entities move to SurrealDB as `entity`/`related`). "Replace the Arango ontology backend" therefore needs an explicit mapping for: tenant instance vertices/edges, `TraversalPattern.query_template` (AQL), LLM-generated dynamic AQL, relation discovery upserts, and the refresh pipeline.
- Tenancy today = one Arango **database per tenant** + one PgVector **schema per tenant**; FEAT-540 kept `TenantContext.arango_db` / `pgvector_schema` unrenamed (F030 non-goals). The draft maps tenancy to a Surreal `NAMESPACE` and puts the ontology in a single shared `ontology` Postgres schema keyed by `ontology_id` — per-tenant ontology overlays (the "client" YAML layer) have no slot in that model.
- Later work (FEAT-540 M8, F030) replaced the public `execute_traversal(aql)` surface with typed traversals and a dialect-explicit dynamic query path; FEAT-670 (F031) adds a backend-neutral `TraversalPattern.traversal_spec`. A Postgres ontology backend needs a traversal compiler (recursive CTE / closure table) for those specs, or it cannot serve the existing patterns.
- [cross-lane: type=read, intent=read ontology/schema.py TraversalPattern (query_template, traversal_spec?) and ontology/defaults/*.yaml to count AQL query_template patterns that a Postgres backend must compile or drop]
- [cross-lane: type=grep, intent=ONTOLOGY_ config variables in parrot/conf.py (12 expected) and which name the Arango database / backend]
