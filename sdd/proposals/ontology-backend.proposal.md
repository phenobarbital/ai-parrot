---
id: FEAT-824
title: "Retire ArangoDB: PostgreSQL OntologyStore + SurrealDB KnowledgeStore as the coherent replacement for ontology-graph management"
slug: ontology-backend
type: feature
mode: enrichment
status: discussion
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-11-06
  summary_oneline: "Replace ArangoDB (licence change) with a coherent ontology-graph backend: PostgreSQL for the ontology + SurrealDB for the knowledge store"
overall_confidence: medium
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-embeddings, parrot-formdesigner]
tags: [ontology, arangodb-removal, postgres, surrealdb, knowledge-store, graph-backend]
research_state: sdd/state/FEAT-824/
created: 2026-11-06
updated: 2026-11-06
---

# FEAT-824 — Retire ArangoDB: PostgreSQL OntologyStore + SurrealDB KnowledgeStore

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: sdd/proposals/SPEC_ontology_backend_postgres_surrealdb.md` (draft v0.1) + inline request
> **Audit**: [`sdd/state/FEAT-824/`](../state/FEAT-824/)

---

## 0. Origin

The original request, preserved verbatim. The full source (inline text plus a verbatim copy of
the 474-line draft) is at `sdd/state/FEAT-824/source.md`.

> Trabajamos en un reemplazo de ArangoDB (que debe ser removido por problemas con su
> licenciamiento Open-Source), por una versión mixta que cubre la ontología usando
> SurrealDB + Postgres, por lo que es importante definir un reemplazo coherente a la
> gestión de grafos ontológicos.

The attached draft defines two stores with a seam between them: an **OntologyStore** on
PostgreSQL (RDF-faithful concepts, labels, relations, materialised closure, versioned Turtle
publication, read-only SQLite snapshot for local use) and a **KnowledgeStore** on SurrealDB in
server mode (OKF wiki, Bookstore, extracted entities, GraphIndex L1 synthesis cache), joined by
IRIs stored as strings and a two-step retrieval (expand in the ontology, filter in SurrealDB).

The licence and engine reasoning behind the draft is in the research note
`sdd/proposals/Grafos open source para ai-parrot.md`, which the user pointed to after the first
version of this proposal, together with the engine selection criteria:

> […] se descartó Apache AGE porque no se puede instalar en Amazon AWS y cualquier servicio SaaS
> de pago, solo servicios open-source no-enterprise y que a su vez descomplejize la plataforma
> (Janus por ejemplo, requiere no solo Cassandra sino a su vez Elasticsearch)

**Initial signals** (extracted, not interpreted):
- Verbs: "reemplazo", "debe ser removido", "definir" → new capability plus a removal.
- Named entities: ArangoDB, SurrealDB, PostgreSQL (RDS), wikitoolkit, Bookstore, GraphIndex L1, Turtle/SHACL/SKOS.
- Components / labels: `parrot.ontology`, `parrot.knowledge` (as named by the draft).
- Acceptance criteria provided: yes — draft §10 (contract suites, golden Turtle, 8-process local concurrency, recall@10 +15 points and p95 < 300 ms, offline suite).

---

## 1. Synthesis Summary

The request is to remove ArangoDB from ai-parrot and replace its role in ontology-graph
management with PostgreSQL plus SurrealDB, following the attached draft. The research shows the
draft was written as a greenfield design, while the repository already contains much of its
scaffolding: FEAT-540 shipped backend-neutral contracts and registries for every knowledge plane
(`create_ontology_graph_store`, `GraphBackendSpec`, `_BUILTIN_WIKI_BACKENDS`), FEAT-520 shipped
Postgres backends for GraphIndex and the wiki (`PostgresPersistence`, `PostgresWikiStore`), and
the concept vocabulary is already authoritative in Postgres (`ConceptCatalogService`). What only
ArangoDB does today is host the per-tenant ontology *instance graph* through
`ArangoOntologyGraphStore`, with AQL embedded in the ontology YAML (`traversal_patterns`), in
LLM-generated queries and in `validate_aql` — a pipeline the draft does not mention. The licence
and engine premises are documented in the research note
`sdd/proposals/Grafos open source para ai-parrot.md`. The user
confirmed the draft's direction in full: supersede FEAT-670 (HelixDB), remove ArangoDB from the
whole workspace, adopt the RDF OntologyStore, and build the complete KnowledgeStore. The
recommendation is to take that design to `/sdd-spec` as a phased programme that starts with the
SurrealDB spike, plugs the new stores into the FEAT-540 seams, and gives the instance-graph
pipeline an explicit destination (the one question still open).

---

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted
> at `sdd/state/FEAT-824/findings/`. Each cites the finding ID(s) that justify
> its inclusion. **No fabricated paths or symbols.**

### 2.1 Localization

Paths under `packages/ai-parrot/src/parrot/` are written as `parrot/…`; other distributions keep
their full path.

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `parrot/knowledge/ontology/contracts.py` | `GraphDocumentStore` | 26-103 | document/edge CRUD contract; its only consumer is GraphIndex's Arango persistence | F001 |
| 2 | `parrot/knowledge/ontology/contracts.py` | `OntologyTraversalStore` | 106-166 | traversal contract (6 methods + `dialect`) that ontology callers depend on | F001 |
| 3 | `parrot/knowledge/ontology/contracts.py` | `create_ontology_graph_store` | 169-206 | name-keyed backend registry and factory; `arangodb` is the only built-in | F001 |
| 4 | `parrot/knowledge/ontology/graph_store.py` | `ArangoOntologyGraphStore` | 62-100 | sole implementation of both contracts; one ArangoDB database per tenant, AQL built inline | F002 |
| 5 | `parrot/knowledge/ontology/graph_store.py` | `UpsertResult` | 24-59 | contract return type that lives in the Arango module | F002 |
| 6 | `parrot/knowledge/ontology/schema.py` | `TraversalPattern` | 261-297 | pattern model with `query_template` (AQL) and per-dialect `query_templates` | F005, F004 |
| 7 | `parrot/knowledge/ontology/schema.py` | `OntologyDefinition` | 421-448 | YAML ontology model: entities, relations, traversal patterns, ArangoSearch `search_views` | F005 |
| 8 | `parrot/knowledge/ontology/schema.py` | `TenantContext` | 531-546 | per-tenant context; `arango_db` is a required field | F007 |
| 9 | `parrot/knowledge/ontology/schema.py` | `ResolvedIntent.dialect` | 561-575 | query dialect of a resolved intent, default `aql` | F004 |
| 10 | `parrot/knowledge/ontology/defaults/base.ontology.yaml` | `traversal_patterns` | 116-149 | bundled patterns whose templates are literal AQL (also knowledge, legal, field_services, contracts, procedures) | F004, F018 |
| 11 | `parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml` | `search_views` | 145-205 | ArangoSearch view declarations and a pattern querying the view by name | F004 |
| 12 | `parrot/knowledge/ontology/intent.py` | `dialect` | 76-265 | intent resolver: default dialect `aql`, LLM-generated dynamic query | F004 |
| 13 | `parrot/knowledge/ontology/validators.py` | `validate_aql` | 36-144 | AQL safety validator registered per dialect | F004 |
| 14 | `parrot/knowledge/ontology/mixin.py` | `OntologyRAGMixin._run_graph_query` | 509-545 | single query-time entry into the store, inside a 4-level degradation chain | F016 |
| 15 | `parrot/knowledge/ontology/refresh.py` | `ArangoOntologyGraphStore` | 22-80 | refresh pipeline typed against the concrete Arango class | F003 |
| 16 | `parrot/knowledge/ontology/concept_catalog/service.py` | `ConceptCatalogService` | 100-117 | sole SQL writer of the Postgres `ontology_concept*` tables | F008 |
| 17 | `parrot/knowledge/ontology/concept_catalog/worker.py` | `ConceptCatalogSyncWorker` | 1-53 | outbox worker materialising concepts into ArangoDB | F008, F003 |
| 18 | `parrot/knowledge/ontology/concept_embedding.py` | `ConceptEmbeddingPipeline` | 1-101 | concept embeddings in pgvector table `ontology.concepts` | F008 |
| 19 | `parrot/knowledge/ontology/tenant.py` | `TenantOntologyManager.__init__` | 60-83 | tenant → graph database / pgvector schema templates | F007 |
| 20 | `parrot/loaders/graphindex.py` | `_make_persistence` | 227-248 | only production call site of the ontology factory, hard-coding `arangodb` | F003 |
| 21 | `parrot/knowledge/graphindex/backends.py` | `GraphBackendSpec` | 22-52 | GraphIndex backend registry (sqlite, null, postgres, arangodb) | F010 |
| 22 | `parrot/knowledge/graphindex/persist_arango.py` | `ArangoPersistence` | 52-884 | GraphIndex Arango persistence | F003, F020 |
| 23 | `parrot/knowledge/graphindex/persist_postgres.py` | `PostgresPersistence` | 207 | shipped Postgres GraphIndex backend (temporal, embeddings, hybrid) | F010, F020 |
| 24 | `parrot/knowledge/wiki/store.py` | `_BUILTIN_WIKI_BACKENDS` | 764-787 | wiki backends: sqlite, memory (local); arangodb, postgres (server) | F009 |
| 25 | `parrot/knowledge/wiki/store.py` | `BaseWikiStore` | 870-1247 | wiki store contract | F009 |
| 26 | `parrot/knowledge/wiki/postgres_store.py` | `PostgresWikiStore` | 127-160 | shipped Postgres wiki server plane over `graphindex.*` | F009, F025 |
| 27 | `parrot/knowledge/wiki/arango_store.py` | `ArangoDBWikiStore` | 137-335 | Arango wiki backend to retire | F009, F019 |
| 28 | `parrot/knowledge/wiki/serve.py` | `build_server_app` | 137-141 | `wikitoolkit serve` refuses any backend but `arangodb` | F009 |
| 29 | `parrot/knowledge/wiki/sources_backend.py` | `SourceManifestBackend` | 50-380 | source-manifest contract (sqlite, json, arangodb) | F009 |
| 30 | `parrot/knowledge/wiki/project.py` | `WikiProjectConfig` | 589-831 | per-repo wiki config with `arango_*` fields | F009, F013 |
| 31 | `packages/ai-parrot-tools/src/parrot_tools/legal/boe/queries.py` | `ArangoOntologyGraphStore` | 8-152 | legal/BOE pack typed against the Arango store (also `boe/sync.py`, `legal/wiki_store.py`, `legal/librarian/suppression.py`) | F003 |
| 32 | `parrot/knowledge/bookstore/catalog.py` | `CatalogStore` | 163-738 | Bookstore catalog on sync SQLite + FTS5 | F028, F011 |
| 33 | `parrot/knowledge/retrieval/wiki_cache.py` | `WikiPage` | — | L1 synthesis cache models; no persistence layer found | F029, F017 |
| 34 | `packages/ai-parrot/pyproject.toml` | `db` extra | 233-239 | pulls `asyncdb[...,arangodb,...]` | F012 |
| 35 | `packages/ai-parrot-embeddings/pyproject.toml` | `arango` extra | 63-99 | `python-arango-async` for the Arango vector store | F012 |
| 36 | `packages/ai-parrot/tests/knowledge/graphindex/persistence_conformance.py` | `case_apply_and_revert` | 1-45 | house pattern for a backend-agnostic conformance suite | F010, F015 |
| 37 | `sdd/specs/helixdb-provider.spec.md` | §1 Non-Goals | — | approved FEAT-670: HelixDB as a peer on the same planes, ArangoDB not retired | F031 |
| 38 | `sdd/specs/graphindex-core-seams.spec.md` | §1 Non-Goals | — | FEAT-540 positions the removal reverses | F030 |
| 39 | `sdd/proposals/Grafos open source para ai-parrot.md` | "Arquitectura recomendada" | 54-62 | research note behind the draft: ArangoDB licence terms, ten-engine comparison, ranking | F032 |

Outside the knowledge planes, 43 more source files in four distributions reference ArangoDB
(F014). The heaviest are `packages/ai-parrot-embeddings/src/parrot/stores/arango.py`,
`packages/ai-parrot-tools/src/parrot_tools/arangodbsearch.py`,
`parrot/interfaces/hierarchy.py`,
`packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/asyncdb_store.py` and
`parrot/registry/routing/rules.py`. Their roles are inferred from path and match count; the files
were not opened.

### 2.2 Constraints Discovered

- **The seams already exist.** FEAT-540 shipped contracts and registries for the ontology store,
  GraphIndex persistence, the wiki store and the source manifest.
  *Implication*: the new stores should be registrations into these seams. The draft's parallel
  `OntologyStore` / `KnowledgeStore` Protocols and its decision D7 duplicate shipped work unless
  they are layered on top.
  *Evidence*: F001, F009, F010, F030

- **The traversal contract is dialect-bound.** A store declares a `dialect`; a pattern without a
  template in that dialect raises `TraversalPatternUnavailable`; a dynamic query in another
  dialect is rejected.
  *Implication*: a non-AQL backend serves nothing until patterns, validator and prompt exist for
  its dialect.
  *Evidence*: F002, F004

- **AQL is ontology content.** The bundled `*.ontology.yaml` patterns, the ArangoSearch
  `search_views`, the LLM dynamic-query path and the validators are all AQL, and tenant YAML
  outside the repository carries more.
  *Implication*: the removal has a content-migration track the draft does not describe.
  *Evidence*: F004, F005, F018

- **The coded ontology is not RDF.** It is a layered YAML property-graph schema plus a per-tenant
  instance graph with discovery, refresh and authorization reachability. No RDF, Turtle, SKOS or
  IRI exists, and `rdflib` / `pyshacl` are undeclared.
  *Implication*: the draft's OntologyStore is a new object; it does not replace what
  `parrot.knowledge.ontology` does today.
  *Evidence*: F005, F006, F016, F027

- **Tenancy is per-tenant databases.** One graph database and one pgvector schema per tenant;
  `TenantContext.arango_db` is required.
  *Implication*: the draft's `ontology_id` / namespace partitioning is a different axis, and
  per-tenant ontology overlays need a slot in it.
  *Evidence*: F007

- **Concepts already live in Postgres.** `ontology_concept*` tables with a five-state review
  machine and an outbox; ArangoDB holds only a materialised copy; embeddings are in
  `ontology.concepts`.
  *Implication*: two concept authorities would coexist, and `CREATE SCHEMA ontology` collides
  with an existing schema name.
  *Evidence*: F008

- **Postgres planes already ship (FEAT-520).** asyncpg only, no SQLAlchemy, no `PgVectorStore`
  reuse, bitemporal append-only versioning, `ts_rank_cd` judged sufficient, fresh ingests only.
  *Implication*: the draft's rejection of plain Postgres for the wiki reverses a recorded
  decision; the spec must justify it and say what happens to `PostgresWikiStore`.
  *Evidence*: F009, F010, F020, F022, F025

- **The concrete Arango class is imported directly.** Seven modules in two distributions, plus
  the public package export.
  *Implication*: callers must move to the contracts before the class can be deleted.
  *Evidence*: F003

- **asyncdb has no SurrealDB driver.** `surrealdb` is declared in no `pyproject.toml`.
  *Implication*: the raw SDK is an exception to the house convention of going through asyncdb.
  *Evidence*: F012, F017

- **The graph path fails soft.** The ontology RAG mixin degrades to `vector_only`.
  *Implication*: the new backend must keep that behaviour.
  *Evidence*: F016

- **Engine selection criteria.** Stated by the user and backed by the research note:
  open-source, non-enterprise editions only; no paid SaaS; deployable on the AWS services in use
  (Apache AGE is not installable on Amazon RDS); and a simpler platform, which rules out
  multi-service stacks such as JanusGraph (Cassandra plus Elasticsearch).
  *Implication*: any backend the spec proposes is checked against these four criteria; they also
  explain why the note's own first choice (PostgreSQL + AGE) is not the one adopted.
  *Evidence*: F032

- **The licence decision is reasoned but not recorded.** The research note documents the
  ArangoDB licence terms and the engine comparison, but it is an untracked file; no commit, ADR
  or decision page records the decision, and FEAT-540 and FEAT-670 both state ArangoDB stays.
  *Implication*: the feature needs an ADR that cites the note and supersedes those positions.
  *Evidence*: F021, F024, F030, F031, F032

- **Bookstore, PageIndex and L1 are not ArangoDB data.** Bookstore is SQLite plus PageIndex
  files, FEAT-670 had decided projection-only for it, and the L1 cache has no persistence.
  *Implication*: moving them is re-platforming, independent of the removal.
  *Evidence*: F011, F028, F029, F017

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `bf86780d88` | 2026-10-15 | Jesus | feat(graphindex-core-seams): TASK-4327 | `ontology/contracts.py` (new), `exceptions.py`, `validators.py` |
| `3ae3dc2820` | 2026-10-15 | Jesus | feat(graphindex-core-seams): TASK-4328 — ArangoOntologyGraphStore typed traversals | `ontology/graph_store.py` |
| `5097106625` | 2026-10-15 | Jesus | feat(graphindex-core-seams): TASK-4329 — query_templates, ResolvedIntent query/dialect | `ontology/intent.py`, `mixin.py`, `schema.py` |
| `4a2944dcf2` | 2026-10-15 | Jesus | feat(graphindex-core-seams): TASK-4320 — persist.py → persist_arango.py | `graphindex/persist_arango.py` |
| `cbcbe45644` | 2026-09-28 | revbot | feat(wikitoolkit-structural-coverage): TASK-3825 — meta API for arango and postgres | `knowledge/wiki` |
| `8b0e889f03` | 2026-09-25 | Jesus | feat(training-agent): TASK-3701 — procedures.ontology.yaml | `ontology/defaults/domains/procedures.ontology.yaml` |
| `edbd5c4645` | 2026-09-19 | Jesus | feat(wiki-adr): TASK-3483 — compare_and_swap_page on ArangoDBWikiStore | `knowledge/wiki` |
| `5f06b90fa9` | 2026-09-09 | Jesus Lara | sdd: add spec for FEAT-541 — parrot-graphindex-package | `sdd/specs/parrot-graphindex-package.spec.md` |
| `a27df8ac7c` | 2026-09-03 | Jesus | feat(graphindex-postgres-backend): TASK-2771 — hybrid_retrieve one-pass SQL + rerank | `knowledge/graphindex` |
| `edcbb26dd1` | 2026-09-03 | Jesus | feat(graphindex-postgres-backend): TASK-2764 — pg_schema.py DDL, migration, pool | `graphindex/pg_schema.py` |
| `e5f23ec002` | 2026-08-27 | Jesus Lara | feat(legal-librarian-answer-layer): TASK-2493 — declarative ArangoSearch views | `ontology/schema.py`, `merger.py`, `graph_store.py` |
| `aa517c6074` | 2026-08-01 | Jesus | feat(wikitoolkit-arangodb-backend): TASK-2061 — CLI integration | `knowledge/wiki` |

Three overlapping features are done and merged on `origin/dev`: FEAT-520
`graphindex-postgres-backend` (10/10, 2026-09-03), FEAT-400 `wikitoolkit-arangodb-backend`
(7/7, 2026-08-01) and FEAT-540 `graphindex-core-seams` (34/34, 2026-10-15) (F022). FEAT-541
`parrot-graphindex-package` is spec'd and not implemented (F023). No commit mentions the
ArangoDB licence, an ArangoDB removal or SurrealDB (F021). The ontology package has had no
commit since 2026-10-15 (F018).

---

## 3. Probable Scope

The scope below follows the user's four decisions (§5): the draft's design is adopted in full
and ArangoDB leaves the whole workspace.

### What's New

- **PostgreSQL OntologyStore (draft §4)** — RDF-faithful concept vocabulary, Turtle publication
  pipeline (rdflib + pyshacl), read-only SQLite snapshot, `resolve` / `expand` / `canonical`
  contract. Entirely greenfield. *Evidence*: F006, F005, F012
- **Reconciliation with the existing concept catalog** — map the reviewed, tenant-scoped
  `ontology_concept*` tables and pgvector `ontology.concepts` onto the IRI/versioned model, and
  pick a schema name that does not collide. *Evidence*: F008
- **SurrealDB KnowledgeStore (draft §5)** — wiki, Bookstore and L1 cache in server mode, reachable
  by existing callers through `register_wiki_backend` and `SourceManifestBackend`.
  *Evidence*: F009, F030, F026
- **First persistence for the L1 cache** — a store for `WikiPage` / `WikiSection`, which is
  section-level with multi-source digests, richer than the draft's flat `synth` table.
  *Evidence*: F029, F017
- **Bookstore on the KnowledgeStore** — async, server-backed replacement of the sync SQLite
  catalog and PageIndex tree storage. *Evidence*: F028, F011
- **A new home for the instance graph and its query content** — per-tenant instance data,
  traversal patterns, dynamic queries, search views and their validator in a non-AQL form
  (open question U5). *Evidence*: F004, F005, F016, F027
- **SurrealDB dependency, extra and local daemon** — `surrealdb` SDK, `parrot knowledge daemon`,
  with the draft's spike G1 as the go/no-go gate. *Evidence*: F012, F017
- **Conformance suites** for the ontology and knowledge stores, on the
  `persistence_conformance.py` pattern. *Evidence*: F015, F010
- **Licence ADR and FEAT-670 supersession** — the ADR cites the research note and the four
  selection criteria, and says why PostgreSQL + AGE and FalkorDB were passed over.
  *Evidence*: F024, F030, F031, F032
- **Data move** for ontology tenants, wiki namespaces with `backend=arangodb`, GraphIndex Arango
  planes and Arango vector collections. *Evidence*: F019, F025, F026, F014

### What Changes

- **`parrot/knowledge/ontology/contracts.py`::`create_ontology_graph_store`** — new built-in,
  `arangodb` lazy import removed, `UpsertResult` hosted here. *Evidence*: F001, F002
- **`parrot/knowledge/ontology/schema.py`::`TenantContext`** — `arango_db` generalised; `aql`
  default of `ResolvedIntent.dialect` and ArangoSearch-shaped `search_views` revisited.
  *Evidence*: F007, F004, F005
- **`parrot/knowledge/ontology/refresh.py`**, **`concept_catalog/reconcile.py`**,
  **`concept_catalog/worker.py`** — typed against the contracts; the Arango materialisation of
  concepts is replaced or dropped. *Evidence*: F003, F008
- **`parrot/knowledge/ontology/intent.py`**, **`validators.py`**, bundled
  **`defaults/*.ontology.yaml`** — dialect, validator and templates follow the new store.
  *Evidence*: F004
- **`packages/ai-parrot-tools/src/parrot_tools/legal/…`** — the legal/BOE pack depends on the
  contract, not on the Arango class. *Evidence*: F003
- **`parrot/loaders/graphindex.py`::`_make_persistence`** and
  **`parrot/knowledge/graphindex/backends.py`** — `arangodb` branch and registration removed
  together with `persist_arango.py`. *Evidence*: F003, F010
- **`parrot/knowledge/wiki/store.py`**, **`serve.py`**, **`sources_backend.py`**, **`project.py`**
  — `arangodb` entry, serve gate, Arango source manifest and `arango_*` config removed or
  re-targeted. *Evidence*: F009, F013
- **`packages/ai-parrot-embeddings/src/parrot/stores/arango.py`** and its `arango` extra —
  removed. *Evidence*: F014, F012
- **`packages/ai-parrot-tools/src/parrot_tools/arangodbsearch.py`** — removed or re-targeted.
  *Evidence*: F014, F013
- **`parrot/interfaces/hierarchy.py`** — ported off direct AQL. *Evidence*: F014, F030
- **`packages/parrot-formdesigner/…/sinks/asyncdb_store.py`**, **`parrot/registry/routing/rules.py`**
  — ArangoDB targets removed. *Evidence*: F014
- **`parrot/knowledge/bookstore/catalog.py`::`CatalogStore`**,
  **`parrot/knowledge/retrieval/wiki_cache.py`::`WikiPage`** — served and persisted by the
  KnowledgeStore. *Evidence*: F028, F011, F029, F017
- **`packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py`** — parity guard
  re-targeted away from `ARANGODB_HOST`. *Evidence*: F024
- **`packages/ai-parrot/pyproject.toml`** `db` extra — `arangodb` removed. *Evidence*: F012
- **`sdd/specs/helixdb-provider.spec.md`** — marked superseded by FEAT-824. *Evidence*: F031

### What's Untouched (Non-Goals)

- GraphIndex's structural plane: the shipped `sqlite` and `postgres` backends stay.
- pgvector as the vector plane for ontology entities and as the primary vector store.
- git as the source of truth for OKF pages (draft D5).
- OWL DL reasoning, free Cypher/SPARQL access for agents, ontology editing UI (draft non-goals).
- Whether `PostgresWikiStore` remains as a peer wiki backend is not decided here; nothing in
  FEAT-824 requires removing it.

### Patterns to Follow

- Register backends by name with a lazy factory and declared capabilities, never by
  `if backend ==` branches. *Evidence*: F010, F009, F001
- Prove each backend with a shared conformance suite of backend-agnostic `case_*` coroutines.
  *Evidence*: F010, F015
- Postgres plane conventions of FEAT-520: asyncpg pool, versioned DDL migration, a settings
  resolver in the style of `GRAPHINDEX_PG_*`. *Evidence*: F010, F020, F025
- Postgres as writer of record with an outbox drained by a `FOR UPDATE SKIP LOCKED` worker for
  cross-store materialisation — the existing analogue of the draft's deprecation propagation.
  *Evidence*: F008
- Graph failures degrade to vector-only. *Evidence*: F016

### Integration Risks

- **Size.** The four decisions make this a multi-feature programme: new ontology model, new
  knowledge store, port of every consumer, workspace-wide removal, data migration. One spec and
  one worktree will not hold it; see the suggested phasing below. *Evidence*: F014, F003, F009, F030
- **Engine documented but untested here.** The research note records BM25, HNSW, RRF and
  multi-process server mode for SurrealDB, and also that the Python SDK 3.x is beta and
  transactions exist only over WebSocket. Spike G1 must run first. SurrealDB is BSL 1.1
  (source-available, not OSI): unlike ArangoDB it has no restrictive binary licence, but users
  who offer it as a service carry that obligation. *Evidence*: F032, F017, F021
- **Third choice of the research.** The note ranks PostgreSQL + AGE first and FalkorDB second;
  AGE is excluded by Amazon RDS, FalkorDB by SSPL, per-graph write serialisation and no BM25.
  The note also recommends keeping ArangoDB as an optional legacy adapter, while the decision
  here is removal from the whole workspace — the removal should be the last phase, after parity.
  *Evidence*: F032
- **The pipeline the draft omits.** With ArangoDB gone everywhere, the instance graph, traversal
  patterns, dynamic queries, refresh and authorization reachability need a destination in the
  same programme (U5). *Evidence*: F004, F005, F016, F027, F003
- **Two concept authorities.** The reviewed Postgres concept catalog and the Turtle-published
  OntologyStore; the draft's `ontology_id` axis has no slot for per-tenant overlays.
  *Evidence*: F008, F007
- **Model mismatch on the knowledge side.** The wiki contract is page-level, Bookstore is
  PageIndex trees, L1 is section-level; the draft's bundle/document/section/chunk schema matches
  none of them one-to-one. *Evidence*: F009, F026, F028, F029, F019
- **Reversed decisions.** FEAT-520 (Postgres FTS sufficient, fresh ingests only), FEAT-540
  (ArangoDB unchanged) and FEAT-670 (Bookstore/PageIndex canonical on files) are overturned
  without a record. *Evidence*: F025, F030, F031, F028, F024
- **AQL outside the repository.** Tenant-authored and LLM-generated AQL needs a content
  migration and a new safety validator. *Evidence*: F004
- **No migration tooling** exists for any ArangoDB plane. *Evidence*: F025, F026, F019
- **Sequencing** with FEAT-541 (package extraction) and the unmerged `feat-255-ontology-rag-kb`
  branch, which touch the same seams. *Evidence*: F023, F022

### Suggested phasing (for the spec to confirm)

1. Spike G1 on SurrealDB plus the licence ADR and FEAT-670 supersession — go/no-go.
2. PostgreSQL OntologyStore: schema, publisher, snapshot, contract suite, reconciliation with
   the concept catalog.
3. SurrealDB KnowledgeStore behind the wiki seams, then Bookstore and L1.
4. Destination for the instance-graph pipeline and port of its consumers (legal/BOE, contracts,
   manuals, `hierarchy.py`).
5. Workspace-wide removal: Arango backends, vector store, tool, sinks, extras, docker, tests.
6. Data migration and the draft's §10 benchmarks.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | The ontology store has a backend-neutral seam: two ABCs and a name-keyed registry, `arangodb` the only built-in | F001 | high | `contracts.py` read in full; confirmed by the wiki lane |
| C2 | `ArangoOntologyGraphStore` is the only implementation, isolates tenants by database, builds AQL inline | F002 | high | class header and key methods read directly |
| C3 | Seven modules in two distributions import the concrete class; the factory has one call site hard-coding `arangodb` | F003 | high | repository-wide grep with line-level hits |
| C4 | AQL is embedded in ontology YAML, the LLM dynamic-query path and the validators | F004 | high | grep with excerpts across YAML, `intent.py`, `validators.py`, `schema.py` |
| C5 | The coded ontology is a layered YAML property-graph schema with an instance graph; no RDF/Turtle/SKOS/IRI exists | F005, F006, F027 | high | `schema.py` and `parser.py` read; two greps returned zero; FEAT-053 agrees |
| C6 | The concept vocabulary is authoritative in Postgres; ArangoDB holds an outbox-materialised copy | F008 | high | service, models and worker read; the table DDL was not located |
| C7 | GraphIndex has a shipped, merged Postgres backend with temporal plane and hybrid retrieval | F010, F020, F022, F025 | high | registry, DDL, commits and task index agree |
| C8 | The wiki has a shipped Postgres server backend; `wikitoolkit serve` accepts only `arangodb` | F009, F022 | high | backend table and serve gate read directly |
| C9 | Bookstore does not use ArangoDB | F011, F028 | high | package grep has no hit; wiki pages describe SQLite + PageIndex |
| C10 | The L1 synthesis cache has no persistence layer today | F029, F017 | medium | `wiki_cache.py` has no I/O; three sibling modules were not opened |
| C11 | 43 files outside ontology/wiki/GraphIndex reference ArangoDB, among them a vector store, a tool, the hierarchy interface and a formdesigner sink | F014, F030 | medium | the count is exact; five roles are inferred, not read |
| C12 | FEAT-670 is approved with 26 tasks pending, no code on dev, no remote branch, and declares ArangoDB not retired | F031, F017 | high | spec read through its wiki page; absence checked by grep and `git branch -r` |
| C13 | No commit, ADR or decision page records the licence decision or any SurrealDB work | F021, F024 | medium | negative result of targeted searches |
| C14 | ArangoDB's licensing makes it unsafe as a default backend for an MIT project distributed commercially: source under BUSL-1.1, binaries and Docker images under a Community License with no commercial-use rights and a 100 GiB cap | F032, F021 | medium | documented in the research note with links to ArangoDB's licence pages; the links were not re-fetched |
| C15 | SurrealDB 3.3.x server mode provides what the draft relies on (BM25 + HNSW + RRF, unlimited namespaces, multi-process), with known gaps: BSL 1.1, SDK 3.x beta, WebSocket-only transactions | F032, F017, F021 | medium | documented in the note's engine matrix; nothing is exercised in the repository yet |
| C16 | A coherent replacement registers into the FEAT-540 seams rather than adding parallel Protocols | F001, F009, F010, F030 | medium | design judgement inferred from the shipped seams |
| C17 | The draft's OntologyStore does not cover the instance graph, traversal patterns, authorization reachability and refresh | F005, F016, F027 | high | both the draft contract and the coded pipeline were read |
| C18 | Tenancy is one graph database and one pgvector schema per tenant, `arango_db` required | F007 | high | model and templates read directly |
| C19 | Removing ArangoDB reverses recorded non-goals of FEAT-540 and FEAT-670 | F030, F031 | high | both non-goal sections read |
| C20 | asyncdb has no SurrealDB driver; `surrealdb`, `rdflib`, `pyshacl` are declared nowhere | F017, F012 | high | driver directory listed; all pyproject files grepped |
| C21 | HelixDB does not fit the write model: it has a single writer process (many readers, no concurrent writers), unlike SQLite WAL where several processes can write, serialised; and its Python client `helix-py` is GPL-3.0. Both support superseding FEAT-670 | F032, F031 | medium | single-writer stated by the user and by the research note ("single writer process", no documented multi-process access); GPL-3.0 stated in the note with a link; neither re-verified here |
| C22 | The engine choice is governed by four criteria: open-source non-enterprise, no paid SaaS, deployable on the AWS services in use (no AGE on RDS), simpler platform | F032 | medium | stated by the user; the note backs the JanusGraph and NebulaGraph exclusions, the AGE-on-RDS exclusion is user-stated |
| C23 | The research note ranks PostgreSQL + AGE first, FalkorDB second, SurrealDB server third, and recommends keeping ArangoDB as an optional adapter | F032 | high | read directly in the note |

Distribution: **15** high, **8** medium, **0** low.

> C14 and C15 are the premises of the whole feature. They rest on the research note, not on
> anything exercised in the repository, and its external links were not re-fetched here. That,
> the open question U5 and the size of the programme keep the overall confidence at medium, and
> are why the spike comes first.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **How does FEAT-824 relate to FEAT-670 (HelixDB provider, approved, 26 tasks pending)?** —
  *Resolved*: "Sustituir FEAT-670" — PostgreSQL + SurrealDB replace the HelixDB plan; FEAT-670 is
  cancelled and an ADR records the licence decision.
  *Resolves claims*: C12, C19
- [x] **How far does "remove ArangoDB" reach in this feature?** — *Resolved*: "Todo el
  workspace" — every ArangoDB consumer in the four distributions, including the vector store,
  the `arangodbsearch` tool, `hierarchy.py`, the formdesigner sink and `docker/arango`.
  *Resolves claims*: C11, C3
- [x] **Which ontology model does the new backend serve?** — *Resolved*: "Adoptar el RDF del
  borrador" — the draft's RDF/Turtle OntologyStore in Postgres becomes the ontology; the existing
  pattern pipeline is ported or retired afterwards.
  *Resolves claims*: C5, C16
- [x] **Does FEAT-824 include the SurrealDB KnowledgeStore for wiki, Bookstore and L1?** —
  *Resolved*: "KnowledgeStore completo" — the full design of the draft.
  *Resolves claims*: C8, C9, C10

- [x] **What evidence backs the licence and engine premises, and why not Apache AGE?** —
  *Resolved*: the research note `sdd/proposals/Grafos open source para ai-parrot.md`; "se
  descartó Apache AGE porque no se puede instalar en Amazon AWS y cualquier servicio SaaS de
  pago, solo servicios open-source no-enterprise y que a su vez descomplejize la plataforma
  (Janus por ejemplo, requiere no solo Cassandra sino a su vez Elasticsearch)".
  *Resolves claims*: C14, C15, C22

### Unresolved (defer to spec / implementation)

- [ ] **Where do the per-tenant instance graph and its machinery go** (YAML entities/relations,
  traversal patterns, LLM dynamic queries, discovery/refresh, authorization reachability, the
  legal/BOE, contracts and manuals packs, `hierarchy.py`)? — *Owner*: tbd
  *Blocks claims*: C17, C4, C16
  *Plausible answers*: a) SurrealDB `entity` / `related` behind `OntologyTraversalStore`, with
  patterns re-templated in a `surrealql` dialect · b) re-model each consumer on the two-step flow
  (`OntologyStore.expand` then `KnowledgeStore.search`) and retire traversal patterns and dynamic
  queries · c) Postgres edge tables with recursive CTEs for the instance graph, SurrealDB only
  for documents

Follow-ups the spec can answer by reading code (not user questions): location of the
`ontology_concept*` DDL; real roles of `stores/arango.py`, `interfaces/hierarchy.py`,
`parrot_tools/wiki/toolkit.py`, the formdesigner sink and `routing/rules.py`; whether
`test_ontology_graph_store.py` needs a live server; how Postgres-backed tests get a database in
CI; which wiki namespaces use `backend=arangodb`; the FEAT-541 spec's stance on backends; the
state of the `feat-255-ontology-rag-kb` branch.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-824`** — *Rationale*: the user closed the four architectural forks in favour
of the draft and the localization is high-confidence (C1–C9). The spec must phase the programme,
put spike G1 first, and settle the one open question (instance-graph destination). The licence
and engine premises are now documented (C14, C15, F032); overall confidence stays medium because
SurrealDB is untested in this repository and U5 is open.

### Alternatives

- **`/sdd-brainstorm FEAT-824`** — to compare the three destinations for the instance-graph
  pipeline before writing the spec.
- **Split into several specs** — one per phase of §3 "Suggested phasing"; FEAT-824 becomes the
  umbrella and the spike its first deliverable.
- **Manual review** — if spike G1 fails, the engine choice reopens and this proposal must be
  revised before any spec.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-824/state.json` |
| Source (raw) | `sdd/state/FEAT-824/source.md` |
| Research plan | `sdd/state/FEAT-824/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-824/findings/F001-*.md` … `F032-*.md` |
| Lane originals | `sdd/state/FEAT-824/findings/.audit/` (FC-*, FG-*, FW-*) |
| Synthesis (JSON) | `sdd/state/FEAT-824/synthesis.json` |

**Budget consumed** (profile `default`):
- Files read: 27 / 40
- Grep calls: 25 / 25
- Git calls: 10 / 10
- Wall time: about 2400 s / 300 s — the wall limit was exceeded and not enforced
- Truncated: **no** — all 30 planned queries ran, plus one follow-up; the cross-lane follow-ups
  recorded in finding Notes were not executed

**Research mode**: three parallel lanes (codebase 16 findings, git 6, wiki 11) plus one parent
follow-up, merged into 31 canonical findings; F032 (the research note, read after the user
pointed to it) was added in a second revision. Citations of F001–F031 were verified by an inline script
instead of probe agents: all 145 cited repository paths exist and every cited line range is
inside its file (two further citations are wiki memory ids, not paths).

**Mode determination**: `auto` → resolved to `enrichment` (the source is a design for a new
capability plus a removal, not a defect report).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (with Claude Code) |
