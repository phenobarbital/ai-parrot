---
id: ADR-0010
title: Graph backends — retire ArangoDB for PostgreSQL + SurrealDB
status: accepted
---

## Context

Source: `sdd/proposals/SPEC_ontology_backend_postgres_surrealdb.md`; `sdd/specs/ontology-backend.spec.md` (FEAT-824).

The decision to retire ArangoDB and adopt PostgreSQL + SurrealDB addresses licensing issues with ArangoDB Community Edition, which ships under a Community License without commercial-use rights and with a 100 GiB cap. This limitation is incompatible with the distribution MIT license of ai-parrot for commercial use.

Four selection criteria guided the evaluation of graph database engines:
1. Open-source non-enterprise licensing
2. No paid SaaS requirements
3. Deployable on the AWS services currently in use
4. Simpler platform architecture

## Decision

PostgreSQL (vocabulary, GraphIndex, vectors) + SurrealDB 3.3.x server mode (instance graph, wiki knowledge store) will be adopted as the primary graph backends, subject to the G1 verdict.

PostgreSQL with AGE was passed over because the Postgres of production runs on Amazon RDS and AWS does not allow the AGE extension to be installed.

FalkorDB was rejected due to its SSPL license, per-graph write serialization, and lack of BM25 support. It was ranked second by the evaluation criteria.

HelixDB was rejected due to its single writer process limitation and GPL-3.0 Python client license.

The positions established by FEAT-540 and FEAT-670 that ArangoDB stays are hereby reversed.

BSL 1.1 licensing for SurrealDB is acceptable because its binaries carry no commercial-use restriction and ai-parrot does not redistribute them.

## Consequences

Removal of ArangoDB is planned as the last phase (D-P7). The research note's advice to keep ArangoDB as an optional adapter is not followed because maintaining multiple backends increases complexity and the licensing restrictions make it unsuitable for commercial deployments.

FEAT-670 (HelixDB provider) is superseded by this decision.

## Decision Metadata

```yaml
schema_version: 1
document_id: seed-graph-backends-postgres-surrealdb
entries:
  - id: d1
    statement: Ontology in PostgreSQL relational with materialized closure
    relation: requires
    about: [knowledge-graphindex]
    targets: [dir:packages]
    rationale: RDS already exists; AGE not installable; RDF stores lack vector and GraphRAG backends; router needs JOINs, trgm and pgvector, not traversals

  - id: d2
    statement: The ontology is append-only + versioned; never delete an IRI, deprecate it (deprecated, replaced_by)
    relation: requires
    about: [knowledge-graphindex]
    targets: [dir:packages]
    rationale: Integrity referential between stores by convention; allows deterministic propagation

  - id: d3
    statement: Local reads the ontology from a read-only SQLite snapshot by (ontology_id, version)
    relation: requires
    about: [knowledge-graphindex]
    targets: [dir:packages]
    rationale: Read-mostly; eliminates a local daemon; works offline

  - id: d4
    statement: Wiki/Bookstore/L1 in SurrealDB server mode in both modes
    relation: requires
    about: [knowledge-wiki]
    targets: [dir:packages]
    rationale: Only evaluated engine with real BM25 + HNSW + fusion + edges with properties + unlimited namespaces; same SurrealQL local and central

  - id: d5
    statement: OKF bundles live in git; Surreal is derived index + graph. Only entities, syntheses and annotations not derivable from git use delta log
    relation: requires
    about: [knowledge-wiki]
    targets: [dir:packages]
    rationale: Page conflicts resolved in git; re-ingestion is idempotent by (path, commit)

  - id: d6
    statement: Seam between stores by IRI as string in Surreal; retrieval in two steps (expand in ontology → filter in Surreal)
    relation: requires
    about: [knowledge-graphindex, knowledge-wiki]
    targets: [dir:packages]
    rationale: No JOIN between engines; expansion returns dozens of IRIs, filter is cheap
```