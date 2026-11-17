---
title: Ontology backend programme
summary: Retiring ArangoDB from ai-parrot — plane-to-destination map, binding decisions D-P1…D-P7, phases and gates, the G1 verdict, and what is still in the tree (FEAT-824).
---

# Ontology backend programme

## Purpose

FEAT-824 removes ArangoDB from ai-parrot. ArangoDB's Community License gives no commercial-use
rights and caps the data at 100 GiB, which conflicts with an MIT-licensed framework that is
distributed commercially. The decision and the rejected alternatives are recorded in
[ADR-0010](../../docs/decisions/graph-backends-postgres-surrealdb.md).

This page is the map of the programme. Use it to decide where a piece of ontology or
knowledge-store work belongs, which decisions bind it, and which gate it must pass first. The
Phase 2 API (the PostgreSQL vocabulary store) is documented on
[Ontology vocabulary store](ontology-vocabulary-store.md).

**Status as of 2026-11-07**

- Phase 1 (spike G1 and the licence ADR) is complete. The G1 verdict is **GO**.
- Phase 2 (the PostgreSQL OntologyStore, snapshots, conformance suite and catalog publication)
  is delivered in code. Its PostgreSQL read path is not yet verified against a live server;
  see the Gotchas on the vocabulary page.
- Phases 3 to 7 are not started. Each one needs a follow-on spec.

## Public API

The programme has no Python API of its own. The Phase 2 surface that exists today is:

- [`OntologyStore`](ref:parrot.knowledge.ontology.vocabulary.contracts) — read contract of the vocabulary plane
- [`OntologyPublisher`](ref:parrot.knowledge.ontology.vocabulary.contracts) — write contract, implemented only by PostgreSQL
- [`create_ontology_store`](ref:parrot.knowledge.ontology.vocabulary.backends) — builds a store from `ONTOLOGY_BACKEND`
- [`register_vocabulary_backend`](ref:parrot.knowledge.ontology.vocabulary.backends) — registers a new vocabulary backend under a name

## Configuration & Parameters

The programme adds no settings of its own. Phase 2 reads the `ONTOLOGY_*` settings documented on
the vocabulary store page. No ArangoDB setting has been removed yet.

## Plane-to-destination map

Each ArangoDB plane gets exactly one destination and enters through a seam that already exists.

| Plane | Today | Destination | Seam | Phase |
|---|---|---|---|---|
| Ontology vocabulary (concepts, labels, hierarchies, versions) | PostgreSQL `ontology_concept*` (reviewed, per tenant) plus an ArangoDB copy; no RDF | PostgreSQL OntologyStore + SQLite snapshot | new `vocabulary` registry | 2 |
| Ontology instance graph (entities, relations, traversal patterns, dynamic queries) | `ArangoOntologyGraphStore`, dialect `aql` | SurrealDB store, dialect `surrealql` | `register_ontology_backend`, `TraversalPattern.query_templates`, `register_query_validator` | 4 |
| Wiki, source manifest, Bookstore, L1 synthesis cache | `ArangoDBWikiStore` (server), SQLite (local) | SurrealDB KnowledgeStore (server mode, central and local) | `register_wiki_backend`, `SourceManifestBackend` | 3 |
| GraphIndex structural plane | `sqlite`, `postgres`, `arangodb` | `sqlite`, `postgres` (shipped) | `register_graph_backend` (`arangodb` entry removed) | 7 |
| Vectors | pgvector (primary), Arango vector store | pgvector | the Arango store is removed | 7 |

## Binding decisions

These bind every phase.

- **D-P1 — Engines.** PostgreSQL 17 on RDS (`vector`, `pg_trgm`) and SurrealDB 3.3.x in server
  mode. SurrealDB is BSL 1.1 (source-available, not OSI). It is accepted because its binaries
  carry no commercial-use restriction and ai-parrot does not redistribute them. It is the only
  evaluated engine that offers BM25, HNSW, graph edges and multi-process writers in one binary.
- **D-P2 — Seams, not parallel abstractions.** Every new backend is a registered implementation
  of an existing FEAT-540 contract.
- **D-P3 — Instance graph goes to SurrealDB** (user decision, 2026-11-06). The SurrealDB store
  implements `GraphDocumentStore` and `OntologyTraversalStore` with `dialect = "surrealql"`.
- **D-P4 — The seam between the two stores is the IRI.** SurrealDB records keep `concept_iri` as
  a string plus the `ontology_version` they were tagged with. Retrieval is two steps: `resolve` and
  `expand` in the vocabulary store, then a filter in SurrealDB. Hierarchies are never copied.
- **D-P5 — git is the source of truth** for OKF pages and for domain ontologies, which are
  Turtle files.
- **D-P6 — Transactional synchronisation.** Local mutations, stream counters and outbox records
  commit together. Operation identity is `(origin, ns, db, seq)` plus a `request_id`. JSONL is an
  export format, never a second source of truth.
- **D-P7 — Removal is last.** Legacy implementations and dependencies stay operational through
  migration, cutover and the rollback window.

## Phases and gates

| Phase | Content | Gate to start | Status |
|---|---|---|---|
| 1 | Spike G1, licence ADR, FEAT-670 supersession | none | complete, G1 = GO |
| 2 | PostgreSQL OntologyStore, snapshot, conformance suite, concept-catalog publication | none (independent of G1) | delivered in code; PostgreSQL reads unverified |
| 3 | SurrealDB KnowledgeStore behind the wiki seams; Bookstore; L1 cache; local daemon; transactional sync; deprecation propagation | G1 = GO | not started (follow-on spec) |
| 4 | SurrealDB instance-graph store, `surrealql` patterns, validator and prompt; port of consumers | G1 = GO | not started (follow-on spec) |
| 5 | Resumable migration rehearsal per tenant and plane, parity, authorization checks, benchmarks, ArangoDB still running | Phases 2–4 merged | not started |
| 6 | Freeze, final delta, cutover with checkpoints, rehearsed rollback | Phase 5 parity accepted | not started |
| 7 | Workspace-wide removal of ArangoDB | retirement gate | not started |

**Retirement gate (Phase 7 precondition).** Per-tenant and per-plane migration checkpoints, data
and query parity, permission parity, benchmark results and a demonstrated rollback. New writes
after cutover are never silently discarded by a rollback.

**If G1 had been NO-GO**, the engine choice for Phases 3 and 4 would reopen and the proposal
would be revised before any follow-on spec. Phase 2 would be unaffected, because nothing in the
OntologyStore depends on SurrealDB.

## Phase 1 — G1 verdict

The G1 spike runs against a pinned SurrealDB server image and a pinned `surrealdb` Python SDK.
The full report is in
`sdd/state/FEAT-824/g1/report.md`.

- **Server image**: `surrealdb/surrealdb@sha256:681c6c22c287421b5c7d99e0fde79b6e0d32c36c1ddeaab2762a1661cb04cd20`
- **SDK**: `surrealdb` 3.0.0
- **Blocking checks**: G1-01 to G1-05, G1-07 to G1-12 (11 checks). All pass.
- **Informational checks**: G1-06 (`search::rrf` availability) and G1-13 (SDK licence, image digest,
  several processes sharing one server). Both pass and neither blocks.
- **Verdict**: **GO**.
- **Measured** (G1-05, 200 IRIs under `CONTAINSANY`): BM25 about 1.5 ms, KNN about 2.0 ms.

The verdict rule is strict: GO only when every blocking check passes. Client-side RRF remains
mandatory whatever G1-06 says.

## What is removed and what is not

**Removed: nothing.** Every ArangoDB file, dependency, extra and Docker asset is still in the
tree. The programme removes them only in Phase 7.

Still in place:

- `ArangoOntologyGraphStore` and the `aql` dialect (instance graph, Phase 4 moves them).
- The Arango branch of `create_ontology_graph_store`.
- `ArangoDBWikiStore` and the wiki `arangodb` backend (Phase 3).
- The GraphIndex `arangodb` backend and `persist_arango.py` (Phase 7).
- The concept-catalog worker's ArangoDB materialisation. `ConceptCatalogSyncWorker` still writes
  to the Arango graph store; the vocabulary publisher is an additional hook.

Added in Phase 2:

- The `parrot.knowledge.ontology.vocabulary` subpackage.
- The `ontology-store` extra and the `parrot ontology` CLI group.
- Three read-only HTTP routes under `/api/ontology/vocabularies/`.
- The optional `vocabulary_publisher` argument of `ConceptCatalogSyncWorker`.

The FEAT-670 HelixDB provider is superseded by FEAT-824 and must not be started.

## Usage Examples

Choose the vocabulary backend from the environment, then use the same read contract either way:

```python
from parrot.knowledge.ontology.vocabulary import create_ontology_store

store = create_ontology_store()  # ONTOLOGY_BACKEND: "postgres" (default) or "snapshot"
try:
    current = await store.version("legal_es")
finally:
    await store.close()
```

The `snapshot` backend needs no database. Its files are built with the `parrot ontology snapshot`
command, described on the vocabulary store page.

## Gotchas

- **Setting `ONTOLOGY_BACKEND` does not remove ArangoDB.** The vocabulary store is a new plane
  beside the Arango instance graph until Phase 4 ports the consumers.
- **G1 GO covers the engine only.** Phases 3 and 4 still need their own specs and design
  decisions. The verdict does not approve any SurrealDB schema.
- **The research note's advice to keep ArangoDB as an optional adapter was not followed.**
  Maintaining several backends adds complexity, and the licence rules out a commercial default.
- **Phase 2 status is partial.** The PostgreSQL publisher, schema, snapshot store and catalog
  bridge are in code. The PostgreSQL read methods other than `version`, `status` and export have
  not been exercised against a live server. Read the vocabulary store page before relying on them.
- **Open questions before the first publication** (spec §8): confirm the parrot namespaces
  `urn:parrot:core:`, `urn:parrot:tenant:<tenant_id>:` and `urn:parrot:framework:`; confirm that
  no planned ontology needs blank nodes; choose the embedding dimension (1024 in the draft, 1536
  as GraphIndex's default). IRIs cannot be renamed later, only deprecated.
- **Phase 7 is larger than it looks.** Forty-three files outside the knowledge planes still refer
  to ArangoDB. The roles of five of them were inferred rather than read, so the Phase 7 spec must
  read them first.

## Related

- [Ontology vocabulary store](ontology-vocabulary-store.md) — the Phase 2 API, settings, CLI and HTTP routes.
- [ADR-0010: graph backends, PostgreSQL and SurrealDB](../../docs/decisions/graph-backends-postgres-surrealdb.md) — the accepted decision and its rejected alternatives.
- G1 SurrealDB spike report (`sdd/state/FEAT-824/g1/report.md`) — per-check evidence and the GO verdict.
- Ontology backend spec (`sdd/specs/ontology-backend.spec.md`) — the full programme and Phase 2 specification.
