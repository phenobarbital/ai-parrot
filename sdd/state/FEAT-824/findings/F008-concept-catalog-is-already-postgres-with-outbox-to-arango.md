---
id: F008
query_id: Q008
type: read
intent: "What storage do the concept catalog and concept embeddings use today (already Postgres/pgvector?)"
executed_at: 2026-11-06T13:39:00Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-008]
---

# F008 — The concept vocabulary is already authoritative in Postgres; ArangoDB only receives a materialised copy through an outbox worker

## Summary

`ConceptCatalogService` ("sole SQL writer for ontology_concept* tables", asyncpg pool) owns four Postgres tables: `ontology_concept`, `ontology_concept_isa`, `ontology_concept_audit`, `ontology_concept_outbox`. Concepts are keyed by UUID + `(tenant_id, slug)`, carry `label`, `synonyms`, `description`, `domain`, a **five-state machine** (`proposed → pending_review → approved | rejected → deprecated`, with `restore`), reviewer/rationale fields and `effective_from/effective_to`; `is_a` edges have a `parent_tier` (`framework | tenant`) + `parent_ref`. The module imports `networkx` and has a `_check_isa_cycle` method (L696, body not read); `get_isa_subgraph` filters edges in Python (no closure table, no recursive CTE). `ConceptCatalogSyncWorker` drains the outbox (`FOR UPDATE SKIP LOCKED`) and **materialises to ArangoDB** collections `concepts` / `concept_isa` via `ArangoOntologyGraphStore`, then publishes Redis invalidation. Concept embeddings go to a shared **pgvector** table `ontology.concepts` (`ConceptEmbeddingPipeline`, sha256 content-hash cache on disk). So the draft's D1/D2 (concepts in Postgres, deprecate-don't-delete) describe something that *partly exists* under a different schema — the gap is closure, labels/trgm, versions and removing the Arango materialisation, not introducing Postgres.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/service.py`
  lines: 1-60
  symbol: module docstring + `_VALID_TRANSITIONS`
  excerpt: |
    """Concept Catalog Service — sole SQL writer for ontology_concept* tables.
    Implements the five-state machine for Concept entities and is_a edges.
        1. SELECT ... FOR UPDATE row lock.
        2. Validate transition (state machine + invariants).
        3. UPDATE row.
        4. INSERT audit row.
        5. INSERT outbox row.
    _TARGET_KIND_TABLE: dict[str, str] = {"concept": "ontology_concept", "isa_edge": "ontology_concept_isa"}

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/service.py`
  lines: 100-117
  symbol: `ConceptCatalogService.__init__`
  excerpt: |
    100:class ConceptCatalogService:
    112:        pg_pool: asyncpg connection pool.
    115:    def __init__(self, pg_pool: Any) -> None:
    117:        self._pool = pg_pool

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/service.py`
  lines: 523-558
  symbol: `ConceptCatalogService.get_isa_subgraph`
  excerpt: |
    edges = await conn.fetch(
        """
        SELECT id, child_id, parent_ref, parent_tier
        FROM ontology_concept_isa
        WHERE tenant_id = $1 AND state = 'approved'
        """, tenant_id)
    ancestors = [... for e in edges if str(e["child_id"]) == str(concept_id)]
    descendants = [... for e in edges if e["parent_ref"] == str(concept_id) and e["parent_tier"] == "tenant"]

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/models.py`
  lines: 17-52
  symbol: `ConceptRow`
  excerpt: |
    id: UUID
    tenant_id: str
    slug: str
    label: str
    synonyms: list[str] = Field(default_factory=list)
    description: str | None = None
    domain: str | None = None
    state: Literal["proposed", "pending_review", "approved", "rejected", "deprecated"]
    effective_from: datetime
    effective_to: datetime | None = None

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/models.py`
  lines: 55-84
  symbol: `IsaEdgeRow`
  excerpt: |
    id: UUID
    tenant_id: str
    child_id: UUID
    parent_tier: Literal["framework", "tenant"]
    parent_ref: str
    state: Literal["proposed", "pending_review", "approved", "rejected", "deprecated"]

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/worker.py`
  lines: 1-53
  symbol: `ConceptCatalogSyncWorker`
  excerpt: |
    """Drains ``ontology_concept_outbox`` rows using ``SELECT … FOR UPDATE SKIP LOCKED``,
    materialises concept/is_a data to ArangoDB via ``ArangoOntologyGraphStore``, and
    publishes cache-invalidation messages to Redis pub/sub.
    OPERATIONS = {"publish_to_graph": "_op_publish", "deprecate_in_graph": "_op_deprecate", "invalidate_cache": "_op_invalidate"}
    GRAPH_NODE_COLLECTION = "concepts"
    GRAPH_EDGE_COLLECTION = "concept_isa"
    INVALIDATION_CHANNEL_PREFIX = "ontology:invalidate:"

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_embedding.py`
  lines: 1-101
  symbol: `ConceptEmbeddingPipeline`
  excerpt: |
    """...writes Concept embeddings into a shared PgVector ``concepts`` table scoped
    by ``tenant_id`` metadata.  Only changed or new concepts are re-embedded...
    The hash cache is persisted as JSON at::
        {ontology_dir}/.concept_hashes/{tenant_id}.json
    def __init__(self, vector_store, embedder, ontology_dir, schema: str = "ontology", table: str = "concepts") -> None:

## Notes

- `CascadeAlert` (`models.py` L87-109): deprecating a concept already emits a cascade notification listing operational `topic_authority` edge ids — an existing analogue of the draft's §7.3 "propagate deprecations".
- The `ontology` Postgres schema name is **already taken** by `ConceptEmbeddingPipeline` (`schema="ontology"`, table `concepts`); the draft's `CREATE SCHEMA ontology` + `ontology.concept` would sit next to `ontology.concepts` — naming collision risk.
- The DDL for `ontology_concept*` tables was not found as `CREATE TABLE` in `src` (grep for `CREATE TABLE.*ontology_concept` matched only files that reference the table names: `concept_catalog/{service,models,reconcile}.py`, `schema_overlay/{models,service}.py`). Where the migration lives is unverified.
- `schema_overlay/` (service 497 lines, worker 127 lines) follows the same Postgres + outbox pattern for tenant schema overlays (file list seen, contents not read).
- [cross-lane: type=wiki_query, intent=where is the DDL/migration for ontology_concept, ontology_concept_isa, ontology_concept_outbox and ontology_schema_overlay (FEAT-159 / topic-authority-ontology spec)]
