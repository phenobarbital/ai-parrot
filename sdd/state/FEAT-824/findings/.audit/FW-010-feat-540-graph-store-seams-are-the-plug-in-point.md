---
id: FW-010
query_id: Q201
type: wiki_page
intent: "Follow-up: which spec created the ontology / graph / wiki backend registries, and what it decided about ArangoDB and AQL"
executed_at: 2026-11-06T13:29:04Z
duration_ms: 4000
parent_id: FW-001
depth: 1
---

# FW-010 — FEAT-540 "GraphIndex Core Seams" (done, 34/34) already made every knowledge plane graph-database agnostic: four contracts + five registries; it kept ArangoDB and did not port AQL

## Summary

`graphindex-core-seams.spec.md` (FEAT-540, approved, v0.5, index `completed_at` 2026-10-15, 34 tasks done) is the owner of the graph-database-agnostic seams. Its v0.4 scope widening made "the graph persistence of the knowledge planes graph-database agnostic and pluggable". It defines: `GraphPersistence` + capability Protocols (temporal, embeddings, hybrid retrieval, incremental staleness) with `register_graph_backend` / `create_graph_persistence`; `GraphDocumentStore` + `OntologyTraversalStore` with typed traversals, declared patterns keyed by query dialect, and a fail-closed dialect-explicit dynamic query path; wiki backend names validated against the wiki registry instead of `Literal`s; and a `SourceManifestBackend` contract. It records where AQL leaked before the seam (7 core call sites, 12 `parrot_tools` call sites, 11 AQL operations in `wiki/sources.py`, 15 direct AQL calls in `parrot/interfaces/hierarchy.py` left out of scope). Its non-goals explicitly keep ArangoDB working unchanged, keep `asyncdb` behind Arango and `asyncpg`+`pgvector` behind Postgres, and decline to rename `TenantContext.arango_db`. Any PostgreSQL + SurrealDB replacement is, architecturally, a set of registrations into these seams plus the removal of the Arango built-ins.

## Citations

- path: `sdd/specs/graphindex-core-seams.spec.md`
  symbol: `header / v0.4–v0.5 scope notes`
  wiki_page_id: file:sdd/specs/graphindex-core-seams.spec.md
  score: n/a (direct wiki_page)
  excerpt: |
    **Feature ID**: FEAT-540 · **Status**: approved · **Target version**: 1.1.0
    **v0.4 widens the scope** (owner decision, 2026-10-14): besides the import seams, this feature makes the graph
    persistence of the knowledge planes **graph-database agnostic and pluggable** — one explicit contract plus a
    registry for GraphIndex persistence backends, and a backend-neutral ontology graph-store contract with typed
    traversals so that raw AQL stops being the public surface. The HelixDB backend (... FEAT-670 reserved
    2026-10-14) plugs into these seams; it is **not** implemented here.

- path: `sdd/specs/graphindex-core-seams.spec.md`
  symbol: `§1 Problem Statement (b) Graph-store coupling`
  wiki_page_id: file:sdd/specs/graphindex-core-seams.spec.md
  excerpt: |
    | Ontology graph store | `OntologyGraphStore` is ArangoDB-only; its public surface is `execute_traversal(ctx, aql, …)` |
      7 core call sites compose AQL inline: `authorization.py:257,339`, `entity_resolver.py:384,427`,
      `mixin.py:337,359,379` (the mixin runs AQL from `ResolvedIntent.aql`, which is either an ontology-YAML
      `TraversalPattern.query_template` or **LLM-generated** AQL validated by a regex, `intent.py:222`);
      12 `parrot_tools` call sites: `legal/wiki_store.py` ×8, `legal/boe/queries.py:72,176`,
      `procedures/retrieval.py:292`, `contracts/retrieval.py:719` |
    | Wiki retrieval plane | Already pluggable ... `sources.py:1303-1425` (11 AQL operations) |
    Out of scope but recorded: `parrot/interfaces/hierarchy.py` holds 15 direct AQL calls outside the knowledge tree.

- path: `sdd/specs/graphindex-core-seams.spec.md`
  symbol: `§1 Goals G7–G8`
  wiki_page_id: file:sdd/specs/graphindex-core-seams.spec.md
  excerpt: |
    G7 — Every GraphIndex persistence backend satisfies one explicit base contract with specified semantics; optional
         capabilities (temporal, embeddings, hybrid retrieval, incremental staleness) are explicit Protocols; backends
         are selected through one registry/factory and no consumer branches on a backend name or probes with `hasattr`.
    G8 — The ontology graph store has a backend-neutral contract: typed operations for every traversal core code
         performs, a lower-level document/edge contract for GraphIndex's Arango persistence, declared traversal patterns
         keyed by query dialect, and a dialect-explicit dynamic query path that fails closed. ArangoDB keeps working
         unchanged behind it.

- path: `sdd/specs/graphindex-core-seams.spec.md`
  symbol: `§1 Non-Goals`
  wiki_page_id: file:sdd/specs/graphindex-core-seams.spec.md
  excerpt: |
    - Implementing the HelixDB backend ... FEAT-670 (`helixdb-provider`).
    - Migrating wiki/graph/ledger/schema databases or bumping their schema versions; existing planes must reopen unchanged.
    - Replacing drivers (`asyncdb` stays behind Arango; `asyncpg`+`pgvector` behind Postgres) ...
    - Porting AQL to Cypher, or making `parrot/interfaces/hierarchy.py` backend-neutral.
    - Renaming `TenantContext.arango_db` / `pgvector_schema` (escalated, §8 Q1).

- path: `sdd/specs/graphindex-core-seams.spec.md`
  symbol: `§2 Overview, seam 4 (Graph-store contracts + registries, M7/M8)`
  wiki_page_id: file:sdd/specs/graphindex-core-seams.spec.md
  excerpt: |
    `graphindex/backends.py` is the single composition root (`register_graph_backend` / `create_graph_persistence`)
    with `sqlite`, `postgres`, `arangodb` and `null` registered lazily. On the ontology side, `ontology/contracts.py`
    declares `GraphDocumentStore` (collection/document/edge CRUD — what GraphIndex's Arango persistence needs) and
    `OntologyTraversalStore` (typed traversals, declared patterns, dialect-bound dynamic queries); today's class
    becomes `ArangoOntologyGraphStore`, implementing both, with its AQL kept private. Wiki backend names are validated
    against the wiki registry instead of `Literal`s, and the source-collection manager's AQL branch moves behind a
    `SourceManifestBackend` contract.

- path: `sdd/tasks/index/graphindex-core-seams.json`
  symbol: `FEAT-540`
  excerpt: |
    feature_id FEAT-540 · completed_at 2026-10-15T23:04:35+00:00 · tasks: {done: 34}

## Notes

- Component diagram names the Arango implementations to retire: `parrot.knowledge.ontology.graph_store.ArangoOntologyGraphStore (asyncdb, AQL)` and `parrot.knowledge.graphindex.persist_arango.ArangoPersistence`; plus `wiki/arango_store.py` (FW-006) and the Arango `SourceManifestBackend`.
- Important coupling: `GraphDocumentStore` exists *because* GraphIndex's Arango persistence is layered on the ontology store ("a lower-level document/edge contract for GraphIndex's Arango persistence"). Dropping Arango removes that consumer; a Postgres ontology backend may only need `OntologyTraversalStore`.
- Removing ArangoDB reverses three recorded FEAT-540 positions: "ArangoDB keeps working unchanged", "existing planes must reopen unchanged / no migration", and the un-renamed `TenantContext.arango_db`. It also brings `parrot/interfaces/hierarchy.py` (15 AQL calls) and the 12 `parrot_tools` call sites into scope — none of which the draft mentions.
- The draft's D7 ("contratos por operaciones semánticas, no por dialecto de consulta") is already the shipped FEAT-540 design; the draft should cite and reuse these contracts rather than define parallel `OntologyStore` / `KnowledgeStore` Protocols.
- Line numbers in the excerpts (`authorization.py:257,339`, etc.) are quoted from the spec as of its 2026-10-14 revision and predate the M8 migration; they are historical, not current.
- [cross-lane: type=grep, intent=verify the AQL call sites listed here were actually migrated behind typed traversals (authorization.py, entity_resolver.py, mixin.py, parrot_tools/legal, procedures, contracts) and that interfaces/hierarchy.py still has direct AQL]
