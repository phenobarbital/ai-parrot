---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-embeddings, parrot-formdesigner]
tags: [ontology, arangodb-removal, postgres, surrealdb, knowledge-store, graph-backend]
docs:
  policy: required
  pages:
    - wiki/knowledge/ontology-backend-programme.md
    - wiki/knowledge/ontology-vocabulary-store.md
  api_modules:
    - parrot.knowledge.ontology.vocabulary
---

# Feature Specification: Ontology backend — retire ArangoDB (programme) + PostgreSQL OntologyStore

**Feature ID**: FEAT-824
**Date**: 2026-11-06
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.2.0
**Source proposal**: `sdd/proposals/ontology-backend.proposal.md` (status `discussion`; 5 resolved
questions; read from the working tree, including review corrections not yet committed there)
**Source draft**: `sdd/proposals/SPEC_ontology_backend_postgres_surrealdb.md` (draft v0.1 with the
same review corrections) · **Research note**: `sdd/proposals/Grafos open source para ai-parrot.md`
**Supersedes**: FEAT-670 `helixdb-provider` (approved, 26 tasks pending, no code on `dev`)
**Builds on**: FEAT-540 `graphindex-core-seams` (done) and FEAT-520 `graphindex-postgres-backend` (done)

> **Scope of this document.** FEAT-824 is a seven-phase programme. This spec does two things:
> (1) it fixes the **architecture, decisions and gates of the whole programme** (§2), and
> (2) it specifies, down to interface skeletons, **only Phases 1–2** — the SurrealDB go/no-go
> spike G1, the licence ADR with the FEAT-670 supersession, and the PostgreSQL OntologyStore.
> §3 lists only those modules; `/sdd-task` decomposes only those. Phases 3–7 are specified in
> follow-on specs written after the G1 verdict (§2 "Programme roadmap").

---

## 1. Motivation & Business Requirements

### Problem Statement

ai-parrot must stop depending on ArangoDB. The research note documents why: ArangoDB's source is
BUSL-1.1 and its binaries and Docker images ship under a Community License with no
commercial-use rights and a 100 GiB cap, which makes it unsafe as a default backend of an
MIT-licensed framework that is distributed commercially.

ArangoDB is not one thing in this repository. It hosts:

- the per-tenant ontology **instance graph**, through `ArangoOntologyGraphStore` — the only
  implementation of the ontology store contracts, with AQL embedded in the ontology YAML
  (`traversal_patterns`, `search_views`), in LLM-generated dynamic queries and in `validate_aql`;
- a server plane for the **wiki** (`ArangoDBWikiStore`) and the source manifest;
- a **GraphIndex** persistence backend (`persist_arango.py`);
- a **vector store**, a search tool, the hierarchy interface, a formdesigner sink — 43 further
  files in four distributions.

The repository already holds most of the scaffolding for a replacement. FEAT-540 shipped
backend-neutral contracts and registries for every knowledge plane; FEAT-520 shipped PostgreSQL
backends for GraphIndex and the wiki; the concept vocabulary is already authoritative in
PostgreSQL (`ConceptCatalogService`), with ArangoDB holding only an outbox-materialised copy.

Two things are missing. There is no **ontology vocabulary store**: nothing in the code is
RDF-faithful, versioned, exportable as Turtle, or able to answer "resolve this term" and "expand
this concept" deterministically for a router. And there is no **engine for the planes that only
ArangoDB serves** — the instance graph and a multi-writer knowledge store with real BM25, vector
search and graph edges.

The user's decisions (proposal §5) settle the direction: PostgreSQL for the ontology vocabulary,
SurrealDB in server mode for the knowledge store and the instance graph, HelixDB (FEAT-670)
dropped, ArangoDB removed from the whole workspace.

### Goals

Programme goals (all phases):

1. Remove every ArangoDB dependency from the four affected distributions, as the **last** step,
   after validated migration, parity and a demonstrated rollback.
2. Give each ArangoDB plane exactly one destination, plugged into the existing FEAT-540 seams
   rather than into parallel abstractions.
3. Keep the same access code for the central shared mode and the local mode (several repos and
   consoles on one machine), and keep local reads working offline.

Goals of this spec (Phases 1–2):

4. Decide go/no-go on SurrealDB 3.3.x and its Python SDK with a reproducible spike (G1) that
   covers the knowledge store, the transactional sync guarantees **and** the instance-graph
   traversal surface.
5. Record the licence and engine decision as an ADR and mark FEAT-670 superseded.
6. Deliver the **PostgreSQL OntologyStore**: an RDF-faithful, append-only, versioned vocabulary
   with materialised closure per publication, a Turtle publication pipeline validated with SHACL,
   a hybrid `resolve`, a deterministic `expand`, and a read-only SQLite snapshot for local and
   offline use — both backends passing one shared conformance suite.
7. Make the existing reviewed concept catalog a **publisher into** that store, so there is one
   read model for concepts.

### Non-Goals (explicitly out of scope)

- **Phases 3–7** are not decomposed here: the SurrealDB KnowledgeStore (wiki, Bookstore, L1
  cache, local daemon, sync), the SurrealDB instance-graph store and the port of its consumers,
  data migration, cutover, and the removal of ArangoDB code. §2 fixes their architecture only.
- **No ArangoDB code, dependency, extra, Docker asset or test is removed or disabled by this
  spec.** Every removal belongs to Phase 7.
- OWL DL reasoning, free Cypher/SPARQL/SurrealQL access for agents, an ontology editing UI
  (draft non-goals).
- GraphIndex's structural plane: the shipped `sqlite` and `postgres` backends stay as they are.
- pgvector stays the vector plane for ontology entities and the primary vector store.
- Whether `PostgresWikiStore` remains as a peer wiki backend is not decided here.
- HelixDB was rejected in the proposal — single writer process and a GPL-3.0 Python client; see
  `sdd/proposals/ontology-backend.proposal.md` C21.
- Apache AGE (not installable on Amazon RDS), FalkorDB (SSPL, no BM25) and JanusGraph
  (Cassandra plus Elasticsearch) were rejected by the engine selection criteria; see proposal C22–C23.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:27017f5526f0981c604e5962813ef5721a8b4194ac198adf9e6dd931e28f1139 evaluation_digest=sha256:f0b0cce10740dbc572eb4ceac1d6245f64a01abe1d1cee0647915486774e01b3 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

#### Programme architecture (all phases)

Each ArangoDB plane gets one destination and enters through a seam that already exists.

| Plane | Today | Destination | Seam it plugs into | Phase |
|---|---|---|---|---|
| Ontology **vocabulary** (concepts, labels, hierarchies, versions) | Postgres `ontology_concept*` (reviewed, per tenant) + ArangoDB copy; no RDF | **PostgreSQL OntologyStore** + SQLite snapshot | new `vocabulary` registry (this spec) | 2 |
| Ontology **instance graph** (per-tenant entities/relations, traversal patterns, dynamic queries, refresh, authorization reachability) | `ArangoOntologyGraphStore`, dialect `aql` | **SurrealDB** store, dialect `surrealql` | `register_ontology_backend`, `TraversalPattern.query_templates`, `register_query_validator` | 4 |
| Wiki, source manifest, Bookstore, L1 synthesis cache | `ArangoDBWikiStore` (server), SQLite (local), no L1 persistence | **SurrealDB KnowledgeStore** (server mode, central and local) | `register_wiki_backend`, `SourceManifestBackend` | 3 |
| GraphIndex structural plane | `sqlite`, `postgres`, `arangodb` | `sqlite`, `postgres` (shipped) | `register_graph_backend` — `arangodb` entry removed | 7 |
| Vectors | pgvector (primary), Arango vector store | pgvector | — Arango store removed | 7 |

Decisions that bind every phase:

- **D-P1 — Engines.** PostgreSQL 17 on RDS (`vector`, `pg_trgm`) and SurrealDB 3.3.x in server
  mode. SurrealDB is BSL 1.1 (source-available, not OSI); it is accepted because, unlike
  ArangoDB, its binaries carry no commercial-use restriction, and it is the only evaluated engine
  that gives BM25 + HNSW + graph edges + multi-process writers on one binary. The ADR (Module 2)
  records this and why PostgreSQL + AGE and FalkorDB, ranked first and second by the research
  note, were passed over.
- **D-P2 — Seams, not parallel abstractions.** Every new backend is a registered implementation
  of a FEAT-540 contract. The draft's `KnowledgeStore` Protocol, where Phase 3 keeps it, is
  layered on top of those registrations, never beside them.
- **D-P3 — Instance graph goes to SurrealDB** (user decision, 2026-11-06). The SurrealDB store
  implements `GraphDocumentStore` and `OntologyTraversalStore` with `dialect = "surrealql"`;
  bundled and tenant traversal patterns gain a `surrealql` entry in `query_templates`; a
  `surrealql` validator is registered; the LLM dynamic-query prompt follows the store dialect.
  Consumers move from the concrete Arango class to the contracts. Tenant isolation maps the
  current one-database-per-tenant model onto SurrealDB namespaces/databases.
- **D-P4 — The seam between the two stores is the IRI.** SurrealDB records keep `concept_iri` as
  a string plus the `ontology_version` they were tagged with. Hierarchies are never copied.
  Retrieval is two steps: `resolve` and `expand` in the OntologyStore, then filter in SurrealDB.
- **D-P5 — git is the source of truth for OKF pages and for domain ontologies** (Turtle).
- **D-P6 — Transactional synchronisation.** Local mutations, stream counters and outbox records
  commit together; central mutations, deduplication receipts and download changes commit
  together; ACKs follow commit; operation identity is `(origin, ns, db, seq)` plus a
  `request_id`. JSONL is an export format, never a second source of truth.
- **D-P7 — Removal is last.** Legacy implementations and dependencies stay operational through
  migration, cutover and the rollback window.

#### Programme roadmap

| Phase | Content | Spec | Gate to start |
|---|---|---|---|
| 1 | Spike G1, licence ADR, FEAT-670 supersession | **this spec** | — |
| 2 | PostgreSQL OntologyStore, snapshot, conformance suite, concept-catalog publication | **this spec** | — (independent of G1) |
| 3 | SurrealDB KnowledgeStore behind the wiki seams; Bookstore; L1 cache; local daemon; transactional sync; ontology-deprecation propagation | follow-on spec | G1 = GO |
| 4 | SurrealDB instance-graph store, `surrealql` patterns/validator/prompt, port of legal/BOE, contracts, manuals, `hierarchy.py` | follow-on spec | G1 = GO |
| 5 | Resumable migration rehearsal per tenant and plane, parity, authorization checks, benchmarks — ArangoDB still running | follow-on spec | Phases 2–4 merged |
| 6 | Freeze, final delta, cutover with checkpoints, rehearsed rollback | follow-on spec | Phase 5 parity accepted |
| 7 | Workspace-wide removal of ArangoDB | follow-on spec | **Retirement gate** (below) |

Follow-on specs take their own FEAT-ID at authoring time and name FEAT-824 in a `Depends on` line.

**Retirement gate (Phase 7 precondition, carried from the proposal).** Per-tenant and per-plane
migration checkpoints, data and query parity, permission parity, benchmark results and a
demonstrated rollback. New writes after cutover are never silently discarded by a rollback.

**If G1 is NO-GO**, the engine choice for Phases 3–4 reopens and the proposal is revised before
any follow-on spec. Phase 2 is unaffected: nothing in the OntologyStore depends on SurrealDB.

#### Phase 1 — Spike G1

A reproducible harness run against a pinned SurrealDB 3.3.x server image and a pinned `surrealdb`
Python SDK, producing a report with one row per check and a verdict. Blocking checks:

| ID | Check | Why it blocks |
|---|---|---|
| G1-01 | `AsyncSurreal` connects, authenticates and reconnects over WebSocket | every store depends on it |
| G1-02 | The draft §5.2 schema applies (SCHEMAFULL tables, `FLEXIBLE` objects, relation tables) | KnowledgeStore schema |
| G1-03 | BM25 full-text search with a Spanish snowball analyzer | hybrid retrieval |
| G1-04 | HNSW index, 1024 dimensions, cosine KNN | hybrid retrieval |
| G1-05 | BM25 and KNN each combined with `CONTAINSANY` over up to 200 IRIs; latency recorded | ontology filter (D-P4) |
| G1-07 | `LIVE SELECT` delivers changes and a consumer recovers after a disconnect | central → local sync |
| G1-08 | A multi-statement transaction commits data, an outbox row and a stream counter atomically | D-P6 |
| G1-09 | Eight writer processes: unique `(origin, ns, db, seq)` and `request_id`, no lost or duplicated mutation | D-P6, local concurrency |
| G1-10 | Failure injected before local commit, after local commit before dispatch, after central commit before ACK, after ACK before local persistence; replay converges | D-P6 |
| G1-11 | Graph traversal: `RELATE` edges, bounded multi-hop traversal, reachability, bind parameters, and a way to run a dynamic query that cannot mutate | D-P3 |
| G1-12 | `GraphDocumentStore` shape: tables created at runtime, upsert by key, soft delete, equality filters, one namespace/database per tenant with no cross-tenant read | D-P3 |

Informational checks (recorded, never blocking): G1-06 availability and signature of
`search::rrf` (client-side RRF is mandatory anyway); G1-13 SDK licence, image digest, and several
processes sharing one local server.

Verdict: **GO** only if every blocking check passes. Before declaring NO-GO on an SDK defect the
harness is re-run with the fallbacks the draft names (SDK 2.0.0 stable, or a thin HTTP client
over `/sql`) and the report says which fallback, if any, turns the check green.

#### Phase 2 — PostgreSQL OntologyStore

A new subpackage, `parrot.knowledge.ontology.vocabulary`, holds the store. "Vocabulary" names the
plane (classes, properties, SKOS concepts, their labels and hierarchies) and keeps it apart from
the instance graph served by `parrot.knowledge.ontology.contracts`.

**Data model.** Everything projects to triples so Turtle round-trips. `ontology_id` acts as a
named graph. Tables live in a dedicated schema, default `ontology_store` (setting
`ONTOLOGY_PG_SCHEMA`) — the schema name `ontology` is already used by the pgvector table
`ontology.concepts`.

- `ontology(ontology_id PK, base_iri, title, current_version)`.
- `version(ontology_id, version, released_at, checksum, turtle_canonical, turtle_uri, notes)`.
- `concept_identity(ontology_id, iri)` — stable identity, never deleted.
- `concept`, `label`, `relation`, `statement` — **versioned rows** with `since_version` and
  `until_version`. Changing an attribute closes the current row and inserts a new one; nothing is
  overwritten. Partial unique indexes on `until_version IS NULL` forbid two current rows for one
  logical identity. `relation.inferred` marks rows materialised from `owl:inverseOf`, so export
  can leave them out. A statement's identity is subject, predicate and the full RDF object
  (value, datatype, language), carried as `object_hash`.
- `closure(ontology_id, version, family, ancestor_iri, descendant_iri, depth)` — computed and
  **retained per publication**; depth 0 is the reflexive row.
- `publication_outbox` — one row per publication with its diff, the Postgres-side source of the
  `OntologyPublished` event that Phase 3 consumes.

**Temporal semantics.** Intervals are half-open: a row is visible at version `v` when
`since_version <= v AND (until_version IS NULL OR v < until_version)`. Every operation captures
one published version and reads everything — rows, labels, closure — at that version. `as_of`
must name an existing version (`1..current_version`); anything else raises
`OntologyVersionNotFound`. A relation removed in v2 and reintroduced in v3 is two rows.

**Publication pipeline** (central only; the publisher is the only writer):

```
Turtle bytes ─► parse (rdflib) ─► validate (pyshacl + parrot rules) ─► diff vs base version N
            ─► diff empty? return version N, changed=False
            ─► prepare embeddings and closure for candidate N+1          (outside the transaction)
            ─► TX: lock ontology row (FOR UPDATE), check current_version == N,
                   insert version N+1, close/insert rows, insert closure(N+1),
                   update current_version, insert publication_outbox
            ─► PublishResult(version=N+1, changed=True, diff)
```

If the base version moved while the candidate was prepared, the transaction rolls back and the
candidate is recomputed (bounded retries, then `PublishConflict`). Parsing, SHACL validation and
closure building are CPU-bound and run in a process pool, never on the event loop.

Parrot validation rules, on top of SHACL: every defined subject is inside `base_iri`; no IRI
present in the base version disappears (it must carry `owl:deprecated true`, optionally
`dcterms:isReplacedBy`); no cycle in the `subclass`, `subproperty`, `broader` and `partof`
families; every class and SKOS concept has at least one `skos:prefLabel`; blank nodes are
rejected in v1.

The checksum is the SHA-256 of the canonical form: the sorted N-Triples of the asserted graph.
`export(as_of=v)` regenerates the graph from versioned rows, and its canonical form must hash to
`version.checksum` — that equality is the temporal-fidelity test.

**Read contract.** `resolve` is hybrid — exact match on any label, then trigram similarity above
0.45, then vector similarity when the caller passes a query embedding — fused by reciprocal rank
fusion (`k = 60`) and returned with `matched_by` so the router can apply deterministic policies.
Deprecated concepts are not returned by `resolve`; `canonical` follows `replaced_by` to a live
IRI. `expand` reads the closure of one version, is closed and reflexive, and always returns the
input IRIs.

**Snapshot.** A read-only SQLite file per `(ontology_id, version)` under
`{ONTOLOGY_SNAPSHOT_DIR}/{ontology_id}/v{version}.sqlite`, containing only the rows visible at
that version and that version's closure, embeddings as float32 BLOBs, and an FTS5 trigram index
over labels. Vector similarity is NumPy brute force in process. A snapshot declares its version
and rejects any other `as_of`. On start, when a `SnapshotSource` is configured and reachable, the
store compares versions and downloads a newer snapshot; otherwise it serves the newest local file
and reports `stale=True`.

**Concept catalog publishes to the store** (user decision, 2026-11-06). The reviewed,
tenant-scoped catalog stays the authoring and review workflow for tenant concepts. A bridge
projects it into one ontology per tenant, `ontology_id = "tenant.<tenant_id>"`, published through
the same publisher. Domain and framework ontologies are published from Turtle in git. Two
authoring paths, one read model. Mapping:

| Catalog | Vocabulary |
|---|---|
| `ConceptRow` (approved) | concept of kind `skos_concept`, IRI `urn:parrot:tenant:<tenant_id>:<slug>` |
| `label` / `synonyms` / `description` | `skos:prefLabel` / `skos:altLabel` / `skos:definition` |
| `domain` | statement `urn:parrot:core:domain` |
| `IsaEdgeRow` (approved), tenant parent | `skos:broader` to the parent concept's IRI |
| `IsaEdgeRow` (approved), framework parent | `skos:broader` to `urn:parrot:framework:<parent_ref>` |
| any published concept that is no longer `approved` | kept, `deprecated = true` |

The existing outbox worker gains an optional publisher and, after draining a batch, republishes
each tenant seen in it. Publication is a full-state projection and publishing an unchanged
ontology does not create a version, so the call is idempotent. The ArangoDB materialisation in
the worker is untouched until Phase 7.

### Component Diagram

```
 Turtle in git ──► parrot ontology publish ──┐
                                             ▼
 ConceptCatalogService ─► outbox ─► ConceptCatalogSyncWorker ─► CatalogVocabularyPublisher
        (Postgres ontology_concept*)         │  (ArangoDB copy: unchanged until Phase 7)
                                             ▼
                                PostgresOntologyPublisher
                       parse ─ validate ─ diff ─ closure ─ embeddings
                                             │ one transaction
                                             ▼
                       PostgreSQL schema  ontology_store.*
                       (versioned rows, closure per version, publication_outbox)
                             │                         │
                             ▼                         ▼
                  PostgresOntologyStore          build_snapshot ─► v{N}.sqlite
                  resolve / expand / get /             │      (HTTP: /api/ontology/vocabularies/…)
                  canonical / export                   ▼
                             │                  SnapshotOntologyStore
                             └────────┬──────────  (aiosqlite + NumPy, offline, stale flag)
                                      ▼
                          create_ontology_store(backend)      ◄── router / L2 (Phase 3+)

 Phase 1, independent:  scripts/spikes/surrealdb_g1 ─► sdd/state/FEAT-824/g1/report.md (GO | NO-GO)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.knowledge.ontology.exceptions.OntologyError` | extends | new vocabulary exceptions derive from it |
| `ConceptCatalogSyncWorker` | modifies | optional `vocabulary_publisher`; republish tenants after a batch |
| `ConceptCatalogService.get_live_concepts` | uses | source of approved `ConceptRow`s for the bridge |
| Postgres tables `ontology_concept`, `ontology_concept_isa` | reads | the bridge reads approved is_a edges; the service stays the only writer |
| `parrot.knowledge.wiki.project.resolve_setting` | uses | explicit → environment → navconfig → default, as `resolve_pg_settings` does |
| `parrot.cli.cli` (`LazyGroup`) | extends | new lazy command `ontology` |
| `concept_catalog/http.py::register_routes` | pattern | same `register_routes(app, prefix)` shape and session check |
| `GraphBackendSpec` / `create_graph_persistence` | pattern | name-keyed registry with lazy `"module:callable"` factories |
| `graphindex/pg_schema.py` | pattern | idempotent DDL builder, `ensure_schema`, asyncpg pool, extension checks |
| `persistence_conformance.py` | pattern | backend-agnostic `case_*` coroutines |
| `packages/ai-parrot/pyproject.toml` extras | extends | new `ontology-store` extra |
| `sdd/specs/helixdb-provider.spec.md` | modifies | status → superseded by FEAT-824 |
| `docs/decisions/` | extends | new ADR |

### Data Models

```python
ConceptKind = Literal[
    "class", "object_property", "datatype_property", "individual", "concept_scheme", "skos_concept",
]
ClosureFamily = Literal["subclass", "subproperty", "broader", "partof"]
LabelKind = Literal["pref", "alt", "hidden"]

class ConceptRef(BaseModel):
    iri: str
    ontology_id: str
    kind: ConceptKind
    pref_label: str | None = None
    definition: str | None = None
    deprecated: bool = False
    replaced_by: str | None = None
    version: int                      # the published version this row was read at

class Resolution(BaseModel):
    concept: ConceptRef
    score: float
    matched_by: Literal["exact", "trgm", "vector"]

class StoreStatus(BaseModel):
    ontology_id: str
    version: int
    stale: bool = False
    backend: str

class ParsedConcept(BaseModel):
    iri: str
    kind: ConceptKind
    pref_label: str | None = None
    definition: str | None = None
    deprecated: bool = False
    replaced_by: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

class ParsedLabel(BaseModel):
    iri: str
    lang: str
    kind: LabelKind
    text: str

class ParsedRelation(BaseModel):
    subject_iri: str
    predicate: str
    object_iri: str
    inferred: bool = False

class ParsedStatement(BaseModel):
    subject_iri: str
    predicate: str
    object: dict[str, Any]            # {"value", "datatype", "lang"} | {"iri"}

class OntologyContent(BaseModel):
    base_iri: str
    concepts: list[ParsedConcept]
    labels: list[ParsedLabel]
    relations: list[ParsedRelation]
    statements: list[ParsedStatement]

class ClosureRow(BaseModel):
    family: ClosureFamily
    ancestor_iri: str
    descendant_iri: str
    depth: int

class VersionContent(BaseModel):
    ontology_id: str
    version: int
    checksum: str
    content: OntologyContent
    closure: list[ClosureRow]
    embeddings: dict[str, list[float]] = Field(default_factory=dict)

class PublishDiff(BaseModel):
    added_iris: list[str] = Field(default_factory=list)
    changed_iris: list[str] = Field(default_factory=list)
    deprecated: dict[str, str | None] = Field(default_factory=dict)   # iri -> replaced_by
    relations_added: int = 0
    relations_closed: int = 0

class PublishResult(BaseModel):
    ontology_id: str
    version: int
    changed: bool
    checksum: str
    diff: PublishDiff

class ValidationIssue(BaseModel):
    code: str                         # e.g. IRI_OUTSIDE_BASE, IRI_REMOVED, HIERARCHY_CYCLE,
    message: str                      #      MISSING_PREF_LABEL, BLANK_NODE_UNSUPPORTED, SHACL
    subject: str | None = None
```

DDL (schema name substituted for `{s}`, embedding dimension for `{dim}`):

```sql
CREATE TABLE IF NOT EXISTS {s}.ontology (
  ontology_id text PRIMARY KEY, base_iri text NOT NULL, title text,
  current_version int NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS {s}.version (
  ontology_id text NOT NULL REFERENCES {s}.ontology, version int NOT NULL,
  released_at timestamptz NOT NULL DEFAULT now(), checksum text NOT NULL,
  turtle_canonical text NOT NULL, turtle_uri text, notes text,
  PRIMARY KEY (ontology_id, version));
CREATE TABLE IF NOT EXISTS {s}.concept_identity (
  ontology_id text NOT NULL REFERENCES {s}.ontology, iri text NOT NULL,
  PRIMARY KEY (ontology_id, iri));
CREATE TABLE IF NOT EXISTS {s}.concept (
  ontology_id text NOT NULL, iri text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('class','object_property','datatype_property',
                                     'individual','concept_scheme','skos_concept')),
  pref_label text, definition text, deprecated boolean NOT NULL DEFAULT false, replaced_by text,
  since_version int NOT NULL, until_version int,
  embedding vector({dim}), extra jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (ontology_id, iri, since_version),
  FOREIGN KEY (ontology_id, iri) REFERENCES {s}.concept_identity,
  FOREIGN KEY (ontology_id, since_version) REFERENCES {s}.version,
  FOREIGN KEY (ontology_id, until_version) REFERENCES {s}.version,
  CHECK (until_version IS NULL OR until_version > since_version));
CREATE TABLE IF NOT EXISTS {s}.label (
  ontology_id text NOT NULL, iri text NOT NULL, lang text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('pref','alt','hidden')), text text NOT NULL,
  since_version int NOT NULL, until_version int,
  PRIMARY KEY (ontology_id, iri, lang, kind, text, since_version),
  FOREIGN KEY (ontology_id, iri) REFERENCES {s}.concept_identity,
  FOREIGN KEY (ontology_id, since_version) REFERENCES {s}.version,
  FOREIGN KEY (ontology_id, until_version) REFERENCES {s}.version,
  CHECK (until_version IS NULL OR until_version > since_version));
CREATE TABLE IF NOT EXISTS {s}.relation (
  ontology_id text NOT NULL, subject_iri text NOT NULL, predicate text NOT NULL,
  object_iri text NOT NULL, inferred boolean NOT NULL DEFAULT false,
  since_version int NOT NULL, until_version int,
  PRIMARY KEY (ontology_id, subject_iri, predicate, object_iri, since_version),
  FOREIGN KEY (ontology_id, since_version) REFERENCES {s}.version,
  FOREIGN KEY (ontology_id, until_version) REFERENCES {s}.version,
  CHECK (until_version IS NULL OR until_version > since_version));
CREATE TABLE IF NOT EXISTS {s}.statement (
  ontology_id text NOT NULL, subject_iri text NOT NULL, predicate text NOT NULL,
  object jsonb NOT NULL, object_hash text NOT NULL,
  since_version int NOT NULL, until_version int,
  PRIMARY KEY (ontology_id, subject_iri, predicate, object_hash, since_version),
  FOREIGN KEY (ontology_id, since_version) REFERENCES {s}.version,
  FOREIGN KEY (ontology_id, until_version) REFERENCES {s}.version,
  CHECK (until_version IS NULL OR until_version > since_version));
CREATE TABLE IF NOT EXISTS {s}.closure (
  ontology_id text NOT NULL, version int NOT NULL,
  family text NOT NULL CHECK (family IN ('subclass','subproperty','broader','partof')),
  ancestor_iri text NOT NULL, descendant_iri text NOT NULL, depth int NOT NULL,
  PRIMARY KEY (ontology_id, version, family, descendant_iri, ancestor_iri),
  FOREIGN KEY (ontology_id, version) REFERENCES {s}.version);
CREATE TABLE IF NOT EXISTS {s}.publication_outbox (
  id bigserial PRIMARY KEY, ontology_id text NOT NULL, version int NOT NULL,
  diff jsonb NOT NULL, enqueued_at timestamptz NOT NULL DEFAULT now(), processed_at timestamptz,
  attempts int NOT NULL DEFAULT 0, last_error text,
  FOREIGN KEY (ontology_id, version) REFERENCES {s}.version);

CREATE UNIQUE INDEX IF NOT EXISTS concept_current   ON {s}.concept (ontology_id, iri) WHERE until_version IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS label_current     ON {s}.label (ontology_id, iri, lang, kind, text) WHERE until_version IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS relation_current  ON {s}.relation (ontology_id, subject_iri, predicate, object_iri) WHERE until_version IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS statement_current ON {s}.statement (ontology_id, subject_iri, predicate, object_hash) WHERE until_version IS NULL;
CREATE INDEX IF NOT EXISTS label_text_trgm     ON {s}.label USING gin (text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS concept_label_trgm  ON {s}.concept USING gin (pref_label gin_trgm_ops);
CREATE INDEX IF NOT EXISTS relation_by_subject ON {s}.relation (ontology_id, predicate, subject_iri);
CREATE INDEX IF NOT EXISTS relation_by_object  ON {s}.relation (ontology_id, predicate, object_iri);
CREATE INDEX IF NOT EXISTS closure_by_ancestor ON {s}.closure (ontology_id, version, family, ancestor_iri);
-- ANN index over current rows only, kind from ONTOLOGY_ANN_INDEX_KIND (hnsw | ivfflat):
-- CREATE INDEX IF NOT EXISTS concept_embedding_ann ON {s}.concept
--   USING hnsw (embedding vector_cosine_ops) WHERE until_version IS NULL;
```

Settings (resolved explicit → environment → navconfig → default):

| Key | Default | Meaning |
|---|---|---|
| `ONTOLOGY_BACKEND` | `postgres` | `postgres` or `snapshot` |
| `ONTOLOGY_PG_DSN` | none (must be set for `postgres`) | asyncpg DSN |
| `ONTOLOGY_PG_SCHEMA` | `ontology_store` | schema holding the tables |
| `ONTOLOGY_EMBEDDING_DIM` | `1024` | `concept.embedding` dimension |
| `ONTOLOGY_ANN_INDEX_KIND` | `hnsw` | `hnsw` or `ivfflat` |
| `ONTOLOGY_SNAPSHOT_DIR` | `~/.parrot/ontology` | snapshot root |
| `ONTOLOGY_SNAPSHOT_URL` | none | base URL of the snapshot HTTP source |
| `ONTOLOGY_DEFAULT_LANG` | `es` | language of labels that declare none |

### New Public Interfaces

```python
from parrot.knowledge.ontology.vocabulary import (
    OntologyStore, OntologyPublisher,             # Protocols
    PostgresOntologyStore, PostgresOntologyPublisher, SnapshotOntologyStore,
    create_ontology_store, register_vocabulary_backend,
    ConceptRef, Resolution, PublishResult, StoreStatus,
)

store = create_ontology_store()                    # backend from ONTOLOGY_BACKEND
hits = await store.resolve("legal_es", "arrendamiento", k=5)
iris = await store.expand("legal_es", [hits[0].concept.iri], family="subclass", direction="down")
```

CLI: `parrot ontology init-schema | register | publish | version | export | snapshot | publish-catalog`.
HTTP: `GET /api/ontology/vocabularies/{ontology_id}/version`, `…/snapshot`, `…/export`.

---

## 3. Module Breakdown

> Phases 1–2 only. Phases 3–7 have no modules in this spec.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: G1 spike harness and report | no | check list and verdict rule fixed (§2) | SurrealQL syntax and SDK behaviour are what the spike discovers; a host with Docker and network must run it |
| M2: Licence ADR + FEAT-670 supersession | yes | ADR file format, statement, supersession line fixed | — |
| M3: Vocabulary contracts, settings, registry | yes | models, Protocols, exceptions, registry signatures fixed | — |
| M4: PostgreSQL schema | yes | DDL fixed in §2; `ensure_schema` pattern from `graphindex/pg_schema.py` | — |
| M5: Turtle model, validation, closure | no | signatures and rule codes fixed | RDF-to-row mapping and canonicalisation need judgement on real Turtle fixtures |
| M6: Publisher | no | transaction order and signatures fixed | concurrency and retry behaviour must be reasoned, not transcribed |
| M7: `PostgresOntologyStore` | yes | read semantics, RRF constants and signatures fixed | — |
| M8: Snapshot build, store, refresh | no | file layout and signatures fixed | trigram-score parity with `pg_trgm` needs design judgement |
| M9: Conformance suite + temporal gate | yes | case list fixed in §4 | — |
| M10: Concept-catalog bridge | yes | mapping table and worker hook fixed | — |
| M11: CLI, HTTP, packaging | yes | command and route list fixed | — |
| M12: Documentation | yes | page list fixed in §10 | — |

Paths below under `parrot/…` are relative to `packages/ai-parrot/src/`.

### Module 1: G1 spike harness and report
- **Path**: `scripts/spikes/surrealdb_g1/` (`README.md`, `docker-compose.yml`, `harness.py`,
  `checks/`), `tests/spikes/test_surrealdb_g1_harness.py`, `sdd/state/FEAT-824/g1/report.md`
- **Responsibility**: run the §2 check list against a pinned server image (by digest) and a
  pinned SDK version, render the report, state the verdict. The harness is not shipped in any
  wheel and adds no dependency to any `pyproject.toml`; it runs in a task-local environment
  (`uv run --no-project --with surrealdb==<pin>`).
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # scripts/spikes/surrealdb_g1/harness.py  (new)
  class CheckResult(BaseModel):
      """Outcome of one G1 check."""
      check_id: str                       # "G1-01" … "G1-13"
      title: str
      blocking: bool
      status: Literal["pass", "fail", "skipped"]
      evidence: str                       # command/query run and what came back
      measurements: dict[str, float] = Field(default_factory=dict)
      fallback: str | None = None         # fallback that turned a failing check green, if any

  Check = Callable[["SpikeContext"], Awaitable[CheckResult]]

  class SpikeContext(BaseModel):
      """Connection settings and pinned versions for one run."""
      url: str
      username: str
      password: str
      server_image: str                   # image reference pinned by digest
      sdk_version: str

  def verdict(results: Sequence[CheckResult]) -> Literal["GO", "NO-GO"]:
      """GO only when every blocking check has status 'pass'."""

  def render_report(ctx: SpikeContext, results: Sequence[CheckResult]) -> str:
      """Render the Markdown report: versions, one row per check, measurements, verdict."""

  async def run(ctx: SpikeContext, checks: Sequence[Check]) -> list[CheckResult]:
      """Run every check in order; a check that raises is recorded as 'fail' with the error."""

  def main(argv: Sequence[str] | None = None) -> int:
      """CLI entry: run all checks, write the report, exit 0 on GO and 1 on NO-GO."""
  ```

### Module 2: Licence ADR + FEAT-670 supersession
- **Path**: `docs/decisions/graph-backends-postgres-surrealdb.md` (new),
  `sdd/specs/helixdb-provider.spec.md` (status line)
- **Responsibility**: record the decision in the repository's ADR format (frontmatter `id`,
  `title`, `status`; Context, Decision, Consequences, Decision Metadata), citing the research
  note and the four selection criteria, and stating why PostgreSQL + AGE and FalkorDB were passed
  over, why BSL 1.1 is acceptable for SurrealDB, and that the positions of FEAT-540 and FEAT-670
  that ArangoDB stays are reversed. Change the FEAT-670 status line to
  `superseded by FEAT-824 (sdd/specs/ontology-backend.spec.md)`.
- **Depends on**: the research note being tracked in git (§8).
- **Interface Skeleton**: no code. The ADR's Decision Metadata block mirrors the entries of this
  spec's `## Decisions` section.

### Module 3: Vocabulary contracts, settings, registry
- **Path**: `parrot/knowledge/ontology/vocabulary/__init__.py`, `contracts.py`, `exceptions.py`,
  `settings.py`, `backends.py`
- **Responsibility**: the data models of §2, the two Protocols, the exceptions, the settings
  resolver and the name-keyed backend registry. `__init__.py` exposes the complete public table
  lazily (PEP 562, as `parrot/knowledge/ontology/__init__.py` does) so that later modules never
  edit it and importing the package loads neither `asyncpg` nor `rdflib`.
- **Depends on**: existing `OntologyError`, `resolve_setting`.
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/ontology/vocabulary/exceptions.py  (new)
  class VocabularyError(OntologyError):  # OntologyError verified: parrot/knowledge/ontology/exceptions.py:4
      """Base class for vocabulary-store errors."""
  class OntologyNotFound(VocabularyError):
      """The ontology_id is not registered."""
  class OntologyVersionNotFound(VocabularyError):
      """as_of names a version that was never published, or one a snapshot does not hold."""
  class OntologyValidationError(VocabularyError):
      """Publication rejected; `issues` holds every ValidationIssue."""
      def __init__(self, issues: Sequence[ValidationIssue]) -> None: ...
  class PublishConflict(VocabularyError):
      """The base version kept moving; bounded retries were exhausted."""

  # parrot/knowledge/ontology/vocabulary/contracts.py  (new) — models of §2 "Data Models", plus:
  EmbedFn = Callable[[Sequence[str]], Awaitable[list[list[float]]]]

  @runtime_checkable
  class OntologyStore(Protocol):
      """Read contract of the ontology vocabulary. Every call reads one published version."""
      async def version(self, ontology_id: str) -> int:
          """Current published version; 0 when registered but never published.
          Raises OntologyNotFound."""
      async def status(self, ontology_id: str) -> StoreStatus:
          """Version, backend name and whether the data may be behind the central store."""
      async def get(self, ontology_id: str, iri: str, *, as_of: int | None = None) -> ConceptRef | None:
          """Concept visible at `as_of` (default: current). None when the IRI is not visible.
          Raises OntologyVersionNotFound."""
      async def resolve(self, ontology_id: str, term: str, *, lang: str | None = None, k: int = 10,
                        kinds: Sequence[str] | None = None,
                        embedding: Sequence[float] | None = None) -> list[Resolution]:
          """Hybrid lookup at the current version: exact label, trigram (> 0.45), vector when
          `embedding` is given; RRF k=60; deprecated concepts excluded; at most k results."""
      async def expand(self, ontology_id: str, iris: Sequence[str], *, family: ClosureFamily = "subclass",
                       direction: Literal["down", "up", "both"] = "down", max_depth: int | None = None,
                       include_deprecated: bool = False, as_of: int | None = None) -> set[str]:
          """Closure of `iris` at one version. Reflexive: always contains the input IRIs."""
      async def neighbors(self, ontology_id: str, iri: str, predicate: str | None = None, *,
                          as_of: int | None = None) -> list[tuple[str, str]]:
          """Outbound (predicate, object_iri) pairs, asserted and inferred."""
      async def canonical(self, ontology_id: str, iris: Sequence[str]) -> dict[str, str]:
          """Map each IRI to its live replacement by following replaced_by (cycle-safe, at most
          16 hops). IRIs that are live, unknown, or deprecated without a replacement map to themselves."""
      async def export(self, ontology_id: str, fmt: Literal["turtle", "jsonld"] = "turtle", *,
                       as_of: int | None = None) -> bytes:
          """Serialise the asserted graph visible at `as_of`; inferred relations are left out."""
      async def close(self) -> None:
          """Release connections and file handles."""

  @runtime_checkable
  class OntologyPublisher(Protocol):
      """Write contract; implemented only by the PostgreSQL backend."""
      async def ensure_ontology(self, ontology_id: str, *, base_iri: str, title: str | None = None) -> None: ...
      async def publish(self, ontology_id: str, turtle: bytes, *, notes: str = "",
                        shapes: bytes | None = None) -> PublishResult: ...
      async def publish_content(self, ontology_id: str, content: OntologyContent, *, notes: str = "",
                                carry_forward_missing: bool = False) -> PublishResult: ...

  # parrot/knowledge/ontology/vocabulary/settings.py  (new)
  class OntologyStoreSettings(BaseModel):
      """Resolved ONTOLOGY_* settings (table in §2)."""
      backend: str = "postgres"
      dsn: str | None = None
      schema_name: str = "ontology_store"
      embedding_dim: int = 1024
      ann_index_kind: str = "hnsw"
      snapshot_dir: Path = Path("~/.parrot/ontology")
      snapshot_url: str | None = None
      default_lang: str = "es"

  def resolve_ontology_settings(*, backend: str | None = None, dsn: str | None = None,
                                schema: str | None = None) -> OntologyStoreSettings:
      """Resolve settings at call time via resolve_setting.   # verified: parrot/knowledge/wiki/project.py:864
      Raises ValueError when the schema name is not a plain SQL identifier."""

  # parrot/knowledge/ontology/vocabulary/backends.py  (new)
  class VocabularyBackendSpec(BaseModel):
      """Registry entry — same shape as GraphBackendSpec.   # pattern verified: parrot/knowledge/graphindex/backends.py:22"""
      name: str
      factory: str                      # "module:callable", imported on first use
      required_options: tuple[str, ...] = ()
      extra: str | None = None          # pip extra named in the ImportError message

  def register_vocabulary_backend(spec: VocabularyBackendSpec) -> None:
      """Register or replace a backend spec. Built-ins: 'postgres', 'snapshot'."""
  def vocabulary_backend_names() -> tuple[str, ...]:
      """Registered names in registration order."""
  def create_ontology_store(backend: str | None = None, **options: Any) -> OntologyStore:
      """Build a store; backend defaults to the ONTOLOGY_BACKEND setting.
      Raises ValueError for an unknown backend or a missing required option; ImportError naming
      the extra when a driver is absent."""
  ```

### Module 4: PostgreSQL schema
- **Path**: `parrot/knowledge/ontology/vocabulary/pg_schema.py`
- **Responsibility**: the idempotent DDL of §2, extension checks (`vector`, `pg_trgm`), the ANN
  index, and the asyncpg pool. Does **not** import from `parrot.knowledge.graphindex` — FEAT-541
  will move that tree into another distribution — and carries its own identifier check.
- **Depends on**: Module 3 (settings, exceptions).
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/ontology/vocabulary/pg_schema.py  (new)
  ONTOLOGY_PG_SCHEMA_VERSION = "1"

  def validate_schema_name(schema: str) -> None:
      """Raise ValueError unless `schema` is a plain, unquoted SQL identifier."""
  def _ddl(schema: str, embedding_dim: int) -> str:
      """Full idempotent DDL (tables and non-ANN indexes) for the vocabulary schema."""
  async def ensure_schema(pool: asyncpg.Pool, schema: str | None = None, *,
                          embedding_dim: int | None = None, ann_index_kind: str | None = None) -> None:
      """Create extensions, schema, tables and indexes if missing.
      Raises RuntimeError with an actionable message when an extension cannot be created."""
  async def create_ontology_pg_pool(dsn: str | None = None, *, schema: str | None = None,
                                    min_size: int = 1, max_size: int = 10, **kwargs: Any) -> asyncpg.Pool:
      """asyncpg pool with the pgvector codec registered on every connection.
      Raises ValueError when no DSN is given and ONTOLOGY_PG_DSN is unset."""
  ```

### Module 5: Turtle model, validation, closure
- **Path**: `parrot/knowledge/ontology/vocabulary/turtle.py`, `closure.py`,
  `shapes/parrot-core.shacl.ttl`
- **Responsibility**: pure, synchronous, picklable functions — Turtle to `OntologyContent` and
  back, the canonical form and checksum, SHACL plus the parrot rules, the diff, and the closure
  with `owl:inverseOf` materialisation. No I/O, no event loop.
- **Depends on**: Module 3 (models). External: `rdflib`, `pyshacl`.
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/ontology/vocabulary/turtle.py  (new)
  PARROT_NS = "urn:parrot:core:"

  def parse_turtle(turtle: bytes, *, base_iri: str, default_lang: str) -> OntologyContent:
      """Parse Turtle into rows. IRI-object triples become relations; skos/rdfs label triples
      become labels; skos:definition, owl:deprecated and dcterms:isReplacedBy become concept
      attributes; every other literal triple becomes a statement.
      Raises OntologyValidationError(BLANK_NODE_UNSUPPORTED) on any blank node."""
  def validate_content(content: OntologyContent, *, previous_iris: frozenset[str] = frozenset(),
                       shapes: bytes | None = None) -> list[ValidationIssue]:
      """Bundled SHACL shapes, optional extra shapes, and the parrot rules of §2.
      Returns every issue; an empty list means valid."""
  def canonical_ntriples(content: OntologyContent) -> bytes:
      """Sorted N-Triples of the asserted graph (inferred relations excluded)."""
  def content_checksum(content: OntologyContent) -> str:
      """sha256 hex digest of canonical_ntriples(content)."""
  def serialize(content: OntologyContent, fmt: Literal["turtle", "jsonld"]) -> bytes:
      """Serialise the asserted graph."""
  def diff_content(base: OntologyContent | None, candidate: OntologyContent) -> PublishDiff:
      """Row-level difference; an all-empty diff means 'nothing to publish'."""
  def statement_object_hash(obj: Mapping[str, Any]) -> str:
      """sha256 of the canonical JSON of a statement object (value, datatype, lang | iri)."""

  # parrot/knowledge/ontology/vocabulary/closure.py  (new)
  FAMILY_PREDICATES: dict[str, str]     # subclass→rdfs:subClassOf, subproperty→rdfs:subPropertyOf,
                                        # broader→skos:broader, partof→PARROT_NS + "partOf"
  def materialise_inverses(relations: Sequence[ParsedRelation]) -> list[ParsedRelation]:
      """Relations implied by owl:inverseOf, each with inferred=True."""
  def find_cycle(relations: Sequence[ParsedRelation], family: str) -> list[str] | None:
      """One cycle in a hierarchy family as a list of IRIs, or None."""
  def build_closure(relations: Sequence[ParsedRelation], iris: Iterable[str]) -> list[ClosureRow]:
      """Transitive closure per family over a DAG, including the depth-0 row of every IRI."""
  ```

### Module 6: Publisher
- **Path**: `parrot/knowledge/ontology/vocabulary/publisher.py`
- **Responsibility**: the §2 publication pipeline. Sole writer of the schema.
- **Depends on**: Modules 3, 4, 5.
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/ontology/vocabulary/publisher.py  (new)
  class PostgresOntologyPublisher:
      """Serialised, append-only publication of ontology versions."""
      MAX_PUBLISH_RETRIES: ClassVar[int] = 3

      def __init__(self, pool: asyncpg.Pool, *, schema: str | None = None, embed: EmbedFn | None = None,
                   executor: concurrent.futures.Executor | None = None) -> None:
          """`embed=None` leaves concept.embedding NULL. `executor=None` uses a lazily created
          single-worker ProcessPoolExecutor for parse / validate / closure."""
      async def ensure_ontology(self, ontology_id: str, *, base_iri: str, title: str | None = None) -> None:
          """Register an ontology at version 0. Idempotent; raises ValueError when it exists with
          a different base_iri."""
      async def publish(self, ontology_id: str, turtle: bytes, *, notes: str = "",
                        shapes: bytes | None = None) -> PublishResult:
          """Parse, then publish_content with carry_forward_missing=False.
          Raises OntologyNotFound, OntologyValidationError, PublishConflict."""
      async def publish_content(self, ontology_id: str, content: OntologyContent, *, notes: str = "",
                                carry_forward_missing: bool = False) -> PublishResult:
          """Validate, diff against the current version, and commit version N+1 in one
          transaction. An empty diff returns the current version with changed=False and writes
          nothing. With carry_forward_missing=True, concepts visible in the base version and
          absent from `content` are kept and marked deprecated instead of failing validation."""
      async def close(self) -> None:
          """Shut down the executor this instance created; the pool belongs to the caller."""
  ```

### Module 7: `PostgresOntologyStore`
- **Path**: `parrot/knowledge/ontology/vocabulary/postgres_store.py`
- **Responsibility**: the read contract over the versioned rows, plus `load_version` for
  snapshot building.
- **Depends on**: Modules 3, 4, 5 (`serialize`).
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/ontology/vocabulary/postgres_store.py  (new)
  class PostgresOntologyStore:
      """OntologyStore over PostgreSQL. Each call captures one version and reads only at it."""
      backend_name: ClassVar[str] = "postgres"
      TRGM_THRESHOLD: ClassVar[float] = 0.45
      RRF_K: ClassVar[int] = 60

      def __init__(self, pool: asyncpg.Pool, *, schema: str | None = None) -> None: ...
      # version / status / get / resolve / expand / neighbors / canonical / export / close:
      #   exactly the OntologyStore signatures of Module 3.
      async def load_version(self, ontology_id: str, version: int | None = None) -> VersionContent:
          """Everything visible at one version — rows, closure, embeddings — for build_snapshot.
          Raises OntologyNotFound, OntologyVersionNotFound."""

  def _create_postgres(*, dsn: str | None = None, schema: str | None = None, pool: Any = None,
                       **_: Any) -> OntologyStore:
      """Registry factory for the 'postgres' backend."""
  ```

### Module 8: Snapshot build, store, refresh
- **Path**: `parrot/knowledge/ontology/vocabulary/snapshot.py`
- **Responsibility**: write a snapshot file from a `VersionContent`; serve the read contract from
  it with `aiosqlite` and NumPy; refresh from a `SnapshotSource`.
- **Depends on**: Modules 3, 5 (`serialize`, checksum). External: `numpy`; `aiosqlite` is core.
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/ontology/vocabulary/snapshot.py  (new)
  def snapshot_path(root: Path, ontology_id: str, version: int) -> Path:
      """{root}/{ontology_id}/v{version}.sqlite"""
  async def build_snapshot(content: VersionContent, dest_root: Path) -> Path:
      """Write the snapshot atomically (temporary file, then rename) and return its path."""
  def trigram_similarity(a: str, b: str) -> float:
      """pg_trgm-compatible similarity: lower-cased, word-padded trigram sets, |A∩B| / |A∪B|."""

  @runtime_checkable
  class SnapshotSource(Protocol):
      async def latest_version(self, ontology_id: str) -> int: ...
      async def fetch(self, ontology_id: str, version: int, dest_root: Path) -> Path: ...

  class HttpSnapshotSource:
      """SnapshotSource over the Module 11 HTTP routes, using aiohttp."""
      def __init__(self, base_url: str, *, headers: Mapping[str, str] | None = None,
                   session: aiohttp.ClientSession | None = None) -> None: ...

  class SnapshotOntologyStore:
      """Read-only OntologyStore over local snapshot files."""
      backend_name: ClassVar[str] = "snapshot"

      def __init__(self, snapshot_dir: Path | str | None = None, *,
                   source: SnapshotSource | None = None) -> None: ...
      async def refresh(self, ontology_id: str) -> StoreStatus:
          """Fetch a newer snapshot when the source is reachable. Never raises on network
          failure: it keeps the newest local file and reports stale=True.
          Raises OntologyNotFound when there is neither a local file nor a reachable source."""
      # version / status / get / resolve / expand / neighbors / canonical / export / close:
      #   the OntologyStore signatures; as_of other than the snapshot's own version raises
      #   OntologyVersionNotFound.

  def _create_snapshot(*, snapshot_dir: Any = None, source: Any = None, **_: Any) -> OntologyStore:
      """Registry factory for the 'snapshot' backend."""
  ```

### Module 9: Conformance suite + temporal gate
- **Path**: `packages/ai-parrot/tests/knowledge/ontology/vocabulary/` — `store_conformance.py`,
  `test_postgres_store.py`, `test_snapshot_store.py`, `test_temporal_fidelity.py`,
  `fixtures/*.ttl`, `conftest.py`
- **Responsibility**: backend-agnostic `case_*` coroutines run against both backends over the
  same golden Turtle, and the temporal-fidelity gate of §5.
- **Depends on**: Modules 6, 7, 8.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/tests/knowledge/ontology/vocabulary/store_conformance.py  (new)
  Case = Callable[[OntologyStore, str], Awaitable[None]]   # (store, ontology_id)
  async def case_version_matches_published(store: OntologyStore, ontology_id: str) -> None: ...
  async def case_get_known_and_unknown(store: OntologyStore, ontology_id: str) -> None: ...
  async def case_resolve_exact_trgm_order(store: OntologyStore, ontology_id: str) -> None: ...
  async def case_resolve_excludes_deprecated(store: OntologyStore, ontology_id: str) -> None: ...
  async def case_expand_closed_and_reflexive(store: OntologyStore, ontology_id: str) -> None: ...
  async def case_expand_multiple_inheritance(store: OntologyStore, ontology_id: str) -> None: ...
  async def case_canonical_follows_replaced_by(store: OntologyStore, ontology_id: str) -> None: ...
  async def case_export_checksum_roundtrip(store: OntologyStore, ontology_id: str) -> None: ...
  async def case_unknown_version_rejected(store: OntologyStore, ontology_id: str) -> None: ...
  ALL_CASES: tuple[Case, ...]
  ```

### Module 10: Concept-catalog bridge
- **Path**: `parrot/knowledge/ontology/vocabulary/catalog_bridge.py` (new),
  `parrot/knowledge/ontology/concept_catalog/worker.py` (modify)
- **Responsibility**: project one tenant's approved catalog into `OntologyContent` by the §2
  mapping and publish it with `carry_forward_missing=True`; let the outbox worker trigger it.
- **Depends on**: Module 6.
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/ontology/vocabulary/catalog_bridge.py  (new)
  def tenant_ontology_id(tenant_id: str) -> str:
      """'tenant.<tenant_id>'. Raises ValueError unless tenant_id matches [A-Za-z0-9_.-]+."""
  def tenant_base_iri(tenant_id: str) -> str:
      """'urn:parrot:tenant:<tenant_id>:'"""
  def content_from_catalog(tenant_id: str, concepts: Sequence[ConceptRow], edges: Sequence[IsaEdgeRow], *,
                           default_lang: str) -> OntologyContent:
      """Pure projection of approved rows.   # ConceptRow verified: concept_catalog/models.py:17
      An edge whose tenant parent is not among `concepts` is skipped."""

  class CatalogVocabularyPublisher:
      """Publishes a tenant's reviewed concept catalog as the ontology 'tenant.<tenant_id>'."""
      def __init__(self, pg_pool: Any, publisher: OntologyPublisher, *, default_lang: str | None = None) -> None: ...
      async def publish_tenant(self, tenant_id: str) -> PublishResult:
          """Read approved concepts and approved is_a edges, ensure the ontology exists, publish.
          Read-only on the catalog tables."""

  # parrot/knowledge/ontology/concept_catalog/worker.py  (modifies :44-55 and :57-131)
  class ConceptCatalogSyncWorker:
      def __init__(self, pg_pool: Any, graph_store: ArangoOntologyGraphStore, redis_client: Any, *,
                   vocabulary_publisher: CatalogVocabularyPublisher | None = None) -> None: ...
      async def run_once(self, batch_size: int = 50) -> int:
          """Unchanged contract. After the batch transaction commits, when a vocabulary publisher
          is set, call publish_tenant once per distinct payload['tenant_id'] seen in the batch;
          a failure is logged and never raised."""
  ```

### Module 11: CLI, HTTP, packaging
- **Path**: `parrot/knowledge/ontology/vocabulary/cli.py`, `http.py` (new);
  `parrot/cli/__init__.py`, `packages/ai-parrot/pyproject.toml` (modify)
- **Responsibility**: the `parrot ontology` command group, the three read-only HTTP routes that
  feed `HttpSnapshotSource`, the lazy command registration, and the `ontology-store` extra.
- **Depends on**: Modules 6, 7, 8, 10.
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/ontology/vocabulary/cli.py  (new) — LazyGroup resolves the attribute named
  # after the command.                                   # verified: parrot/cli/__init__.py:99-100
  @click.group()
  def ontology() -> None:
      """Ontology vocabulary store: publish, export and snapshot."""
  # Subcommands (each a thin asyncio.run wrapper over Modules 4, 6, 7, 8, 10):
  #   init-schema
  #   register <ontology_id> --base-iri <iri> [--title <text>]
  #   publish <ontology_id> <turtle_file> [--shapes <file>] [--notes <text>]
  #   version <ontology_id>
  #   export <ontology_id> [--as-of <n>] [--format turtle|jsonld] [-o <file>]
  #   snapshot <ontology_id> [--version <n>] [--dest <dir>] [--from-turtle <file> --base-iri <iri>]
  #   publish-catalog --tenant <tenant_id>

  # parrot/knowledge/ontology/vocabulary/http.py  (new)
  async def get_version(request: web.Request) -> web.Response:
      """GET {prefix}/vocabularies/{ontology_id}/version → {"ontology_id", "version", "checksum"}"""
  async def get_snapshot(request: web.Request) -> web.StreamResponse:
      """GET {prefix}/vocabularies/{ontology_id}/snapshot[?version=N] → the SQLite file, built on
      demand and cached under ONTOLOGY_SNAPSHOT_DIR."""
  async def get_export(request: web.Request) -> web.Response:
      """GET {prefix}/vocabularies/{ontology_id}/export[?as_of=N&fmt=turtle|jsonld]"""
  def register_routes(app: web.Application, prefix: str = "/api/ontology") -> None:
      """Register the three routes. Handlers read request.app['ontology_store']; they require a
      session (401 otherwise) and, for 'tenant.<id>' ontologies, the session's tenant or the
      topic_admin role (403 otherwise).   # pattern verified: concept_catalog/http.py:45, :371"""
  ```
  `pyproject.toml`: `ontology-store = ["asyncpg>=0.29", "pgvector>=0.2", "rdflib>=7.0", "pyshacl>=0.26", "numpy>=1.26"]`.
  `cli/__init__.py`: `"ontology": "parrot.knowledge.ontology.vocabulary.cli",` and a `_lazy_extras`
  hint `ai-parrot[ontology-store]`.

### Module 12: Documentation
- **Path**: `wiki/knowledge/ontology-backend-programme.md`, `wiki/knowledge/ontology-vocabulary-store.md`
- **Responsibility**: the pages listed in §10.
- **Depends on**: Modules 1–11.
- **Interface Skeleton**: no code.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_verdict_requires_all_blocking` | M1 | NO-GO when one blocking check fails; informational failures do not block |
| `test_report_lists_every_check` | M1 | report has one row per check, the pinned versions and the verdict |
| `test_models_roundtrip` | M3 | every model validates and serialises |
| `test_registry_unknown_backend` | M3 | `create_ontology_store("nope")` raises `ValueError` naming the known backends |
| `test_package_import_is_light` | M3 | importing `parrot.knowledge.ontology.vocabulary` loads neither `asyncpg` nor `rdflib` |
| `test_settings_precedence` | M3 | explicit beats environment beats default; bad schema name rejected |
| `test_ddl_is_idempotent_text` | M4 | every `CREATE` in `_ddl` is `IF NOT EXISTS`; schema name is validated |
| `test_parse_kinds_labels_relations` | M5 | golden Turtle maps to the expected rows |
| `test_blank_node_rejected` | M5 | `BLANK_NODE_UNSUPPORTED` |
| `test_rules_each_code` | M5 | one failing fixture per rule code |
| `test_checksum_ignores_formatting` | M5 | two formattings of one graph share a checksum |
| `test_closure_dag_and_reflexive` | M5 | multiple inheritance, depths, depth-0 rows |
| `test_inverse_materialised_not_exported` | M5 | inferred relations exist and are absent from `canonical_ntriples` |
| `test_trigram_similarity_reference_values` | M8 | fixed pairs match values recorded from `pg_trgm` |
| `test_content_from_catalog_mapping` | M10 | every row of the §2 mapping table |
| `test_worker_republishes_tenants` | M10 | one `publish_tenant` per distinct tenant; a publisher error does not fail `run_once` |
| `test_worker_without_publisher_unchanged` | M10 | existing behaviour when the argument is omitted |
| `test_cli_commands_registered` | M11 | `parrot ontology --help` lists the seven subcommands |
| `test_http_auth` | M11 | 401 without a session; 403 for another tenant's ontology |

### Integration Tests

Need a live PostgreSQL with `vector` and `pg_trgm`. They read `ONTOLOGY_PG_DSN`, fall back to
`parrot.conf.default_dsn`, and are skipped when neither is set (the `test_persist_postgres.py`
pattern). Each run creates a uniquely named schema and drops it at teardown.

| Test | Description |
|---|---|
| `test_ensure_schema_twice` | `ensure_schema` is idempotent on a live server |
| `test_publish_twice_same_version` | publishing the same Turtle twice does not create a version |
| `test_publish_removed_iri_rejected` | `IRI_REMOVED` unless deprecated |
| `test_concurrent_publish_serialised` | two concurrent publications yield consecutive versions, no overlapping intervals, no mixed-version read |
| `test_temporal_fidelity_v1_v2_v3` | the temporal gate of §5 |
| `test_conformance_postgres` / `test_conformance_snapshot` | `ALL_CASES` against each backend over the same published fixture |
| `test_snapshot_offline_stale` | with an unreachable source the store serves the local file and reports `stale=True` |
| `test_catalog_publish_tenant` | approved catalog rows become a published tenant ontology; un-approving a concept deprecates it |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/ontology/concept_catalog/test_worker.py
- packages/ai-parrot/tests/knowledge/ontology/concept_catalog/test_models.py
- packages/ai-parrot/tests/knowledge/ontology/test_contracts.py
- packages/ai-parrot/tests/knowledge/ontology/test_exceptions.py
- packages/ai-parrot/tests/knowledge/test_lazy_package_roots.py
- packages/ai-parrot/tests/knowledge/test_import_ceilings.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_import.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_validation.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_publisher.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_postgres_store.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_snapshot_store.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_temporal_fidelity.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_catalog_bridge.py
- packages/ai-parrot/tests/knowledge/ontology/concept_catalog/test_worker_vocabulary.py
- packages/ai-parrot/tests/knowledge/ontology/test_ontology_store_extra.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_contracts.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_settings.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_backends.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_fixtures.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_pg_schema.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_closure.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_turtle.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_postgres_reads.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_snapshot_build.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_snapshot_offline.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_cli.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_http.py
- packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_docs.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_rules.py
- tests/spikes/test_surrealdb_g1_harness.py
- tests/spikes/test_surrealdb_g1_checks.py
- tests/spikes/test_surrealdb_g1_report.py
markers: none

### Test Data / Fixtures

```python
# packages/ai-parrot/tests/knowledge/ontology/vocabulary/conftest.py
@pytest.fixture
def golden_v1() -> bytes: ...          # fixtures/legal_es.v1.ttl — classes, SKOS concepts, a DAG
@pytest.fixture
def golden_v2() -> bytes: ...          # labels, attributes and relations changed; one deprecation
@pytest.fixture
def golden_v3() -> bytes: ...          # a relation removed in v2 comes back

@pytest_asyncio.fixture
async def pg_schema_name() -> AsyncIterator[str]: ...     # unique schema, dropped at teardown
@pytest_asyncio.fixture
async def published_store(pg_schema_name, golden_v1) -> AsyncIterator[tuple[OntologyStore, str]]: ...
```

---

## 5. Acceptance Criteria

> Phases 1–2 are complete when ALL of the following are true.

Phase 1:

- [ ] `sdd/state/FEAT-824/g1/report.md` exists, names the pinned server image digest and SDK
      version, has one row per check G1-01 … G1-13 with evidence, and states `GO` or `NO-GO`.
- [ ] The G1 harness is reproducible from its README on a host with Docker; it adds no dependency
      to any `pyproject.toml`.
- [ ] `docs/decisions/graph-backends-postgres-surrealdb.md` exists in the repository ADR format,
      cites the research note and the four selection criteria, and names FEAT-540 and FEAT-670 as
      the positions it reverses.
- [ ] `sdd/specs/helixdb-provider.spec.md` carries `**Status**: superseded by FEAT-824 (…)`.

Phase 2:

- [ ] `ensure_schema` creates the §2 schema idempotently in `ontology_store` and does not touch
      the existing `ontology` schema or the `ontology_concept*` tables.
- [ ] Publishing the same Turtle twice does not change `version`.
- [ ] **Temporal fidelity**: publish v1; change labels, attributes and relations in v2;
      reintroduce a relation in v3. `get(as_of=1)` and `export(as_of=1)` reproduce v1, and the
      export's checksum equals `version.checksum` for v1, v2 and v3. Each version keeps its own
      closure. An `as_of` that was never published raises `OntologyVersionNotFound`.
- [ ] Concurrent publications never produce overlapping validity intervals or a mixed-version read.
- [ ] A Turtle that drops an IRI without deprecating it, creates a hierarchy cycle, leaves a class
      without `skos:prefLabel`, defines a subject outside `base_iri` or contains a blank node is
      rejected with the matching issue code, and nothing is written.
- [ ] `expand` is closed and reflexive, and correct on a DAG with multiple inheritance.
- [ ] `PostgresOntologyStore` and `SnapshotOntologyStore` pass the same `ALL_CASES` over the same
      published fixture.
- [ ] A snapshot of version `v` holds only rows visible at `v` and that version's closure, and
      rejects any other `as_of`.
- [ ] With the network unreachable, `SnapshotOntologyStore` serves every read from the local file
      and reports `stale=True`.
- [ ] `CatalogVocabularyPublisher.publish_tenant` publishes approved catalog concepts as
      `tenant.<tenant_id>`; a concept that stops being approved stays in the store as deprecated.
- [ ] `ConceptCatalogSyncWorker` behaves exactly as before when `vocabulary_publisher` is omitted,
      and its ArangoDB materialisation is unchanged.
- [ ] `parrot ontology --help` lists the seven subcommands; `pip install ai-parrot[ontology-store]`
      is the only install step they need beyond core.
- [ ] Importing `parrot.knowledge.ontology.vocabulary` loads neither `asyncpg` nor `rdflib`;
      `test_lazy_package_roots.py` and `test_import_ceilings.py` still pass.
- [ ] No file that imports or configures ArangoDB is deleted, and no ArangoDB extra, Docker asset
      or test is removed.
- [ ] `ruff check` passes on every new and modified file; no `requests`, `httpx`, SQLAlchemy or
      `print` is introduced.
- [ ] The validation contract of §4 passes.
- [ ] Documentation pages declared in §10 exist under `wiki/` (`parrot sdd techwiki check`).
- [ ] The publication time and the snapshot `resolve` latency for the largest golden fixture are
      measured and recorded in the Completion Note of the tasks that add them (no threshold in
      this spec; Phase 5 owns the benchmarks).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

Paths written `parrot/…` are under `packages/ai-parrot/src/`.

### Verified Imports

```python
from parrot.knowledge.ontology.exceptions import OntologyError            # verified: parrot/knowledge/ontology/exceptions.py:4
from parrot.knowledge.ontology.exceptions import QueryValidationError     # verified: parrot/knowledge/ontology/exceptions.py:27
from parrot.knowledge.ontology.exceptions import CycleError               # verified: parrot/knowledge/ontology/exceptions.py:82
from parrot.knowledge.ontology.concept_catalog.models import ConceptRow, IsaEdgeRow   # verified: …/concept_catalog/models.py:17, :55
from parrot.knowledge.ontology.concept_catalog.service import ConceptCatalogService   # verified: …/concept_catalog/service.py:100
from parrot.knowledge.ontology.concept_catalog.worker import ConceptCatalogSyncWorker # verified: …/concept_catalog/worker.py:18
from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore            # verified: parrot/knowledge/ontology/graph_store.py:62
from parrot.knowledge.ontology.contracts import (                         # verified: parrot/knowledge/ontology/contracts.py
    DynamicQuery,                    # :17
    GraphDocumentStore,              # :26
    OntologyTraversalStore,          # :106
    register_ontology_backend,       # :172
    create_ontology_graph_store,     # :182
)
from parrot.knowledge.ontology.validators import register_query_validator, validate_query  # verified: …/validators.py:107, :120
from parrot.knowledge.wiki.project import resolve_setting                 # verified: parrot/knowledge/wiki/project.py:864
from parrot.conf import default_dsn                                       # verified: parrot/conf.py:72 (None at :76 when DB env is unset)
from parrot.cli import cli                                                # verified: parrot/cli/__init__.py:165
import asyncpg                                                            # extra `graphindex-postgres`: packages/ai-parrot/pyproject.toml:296
import aiosqlite                                                          # core dependency: packages/ai-parrot/pyproject.toml:205
```

### Existing Class Signatures

```python
# parrot/knowledge/ontology/exceptions.py
class OntologyError(Exception): ...                                  # line 4
class QueryDialectMismatch(OntologyError): ...                       # line 42
class TraversalPatternUnavailable(OntologyError): ...                # line 46

# parrot/knowledge/ontology/contracts.py   (instance-graph seam — NOT modified by this spec)
class OntologyTraversalStore(ABC):                                   # line 106
    dialect: ClassVar[str]                                           # line 109
    async def is_reachable(self, ctx: TenantContext, start_id: str, target_id: str, *,
                           edge_collection: str, max_depth: int, direction: str = "outbound") -> bool: ...  # line 112
    async def execute_pattern(self, ctx: TenantContext, pattern: TraversalPattern, params: Mapping[str, Any],
                              collection_binds: Mapping[str, str] | None = None) -> list[dict[str, Any]]: ...  # line 155
    async def execute_query(self, ctx: TenantContext, query: DynamicQuery) -> list[dict[str, Any]]: ...  # line 165
_ONTOLOGY_BACKENDS: dict[str, Callable[..., GraphDocumentStore]] = {}  # line 169
def register_ontology_backend(name: str, factory: Callable[..., GraphDocumentStore]) -> None: ...  # line 172
def create_ontology_graph_store(backend: str, **options: Any) -> GraphDocumentStore: ...  # line 182 ("arangodb" lazy branch at :201)

# parrot/knowledge/ontology/graph_store.py
class UpsertResult(BaseModel): ...                                   # line 24
class ArangoOntologyGraphStore(GraphDocumentStore, OntologyTraversalStore):  # line 62
    dialect: ClassVar[str] = "aql"                                   # line 78

# parrot/knowledge/ontology/schema.py
class TraversalPattern(BaseModel):                                   # line 261
    query_template: str                                              # line 289
    query_templates: dict[str, str] = Field(default_factory=dict)    # line 290
class TenantContext(BaseModel):                                      # line 531
    tenant_id: str
    arango_db: str                                                   # required
    pgvector_schema: str
    ontology: MergedOntology
class ResolvedIntent(BaseModel):                                     # line 549
    dialect: str = "aql"

# parrot/knowledge/ontology/validators.py
_VALIDATORS: dict[str, Callable[[str, int | None], Awaitable[str]]] = {}   # line 104
def register_query_validator(dialect: str, validator: ...) -> None: ...   # line 107
register_query_validator("aql", validate_aql)                        # line 144

# parrot/knowledge/ontology/concept_catalog/models.py
class ConceptRow(BaseModel):                                         # line 17
    id: UUID; tenant_id: str; slug: str; label: str
    synonyms: list[str]; description: str | None; domain: str | None
    state: Literal["proposed", "pending_review", "approved", "rejected", "deprecated"]
    asserted_by: str; reviewed_by: str | None; reviewed_at: datetime | None
    rationale: str | None; effective_from: datetime; effective_to: datetime | None
class IsaEdgeRow(BaseModel):                                         # line 55
    id: UUID; tenant_id: str; child_id: UUID
    parent_tier: Literal["framework", "tenant"]
    parent_ref: str                 # framework concept name, or the tenant concept id as str
    state: Literal["proposed", "pending_review", "approved", "rejected", "deprecated"]
    asserted_by: str; reviewed_by: str | None; rationale: str | None

# parrot/knowledge/ontology/concept_catalog/service.py
class ConceptCatalogService:                                         # line 100
    def __init__(self, pg_pool: Any) -> None: ...                    # line 115
    async def get_live_concepts(self, tenant_id: str, domain: str | None = None) -> list[ConceptRow]: ...  # line 457 — approved only
    async def get_isa_subgraph(self, tenant_id: str, concept_id: UUID) -> dict[str, Any]: ...  # line 523

# parrot/knowledge/ontology/concept_catalog/worker.py
class ConceptCatalogSyncWorker:                                      # line 18
    OPERATIONS: dict[str, str] = {"publish_to_graph": "_op_publish",
                                  "deprecate_in_graph": "_op_deprecate",
                                  "invalidate_cache": "_op_invalidate"}
    def __init__(self, pg_pool: Any, graph_store: ArangoOntologyGraphStore, redis_client: Any) -> None: ...  # line 44
    async def run_once(self, batch_size: int = 50) -> int: ...       # line 57; `return len(rows)` at :131
    # tenant id comes from the row payload JSON: payload.get("tenant_id")   # lines 146-148

# parrot/knowledge/ontology/concept_catalog/http.py
def _check_role(request: web.Request, allowed_roles: set[str]) -> str: ...   # line 45 — session = request.get("session")
def register_routes(app: web.Application, prefix: str = "/api/ontology") -> None: ...  # line 371 — base = f"{prefix}/concepts"
# handlers read request.app["concept_catalog_service"]                # line 110

# parrot/knowledge/ontology/concept_embedding.py
class ConceptEmbeddingPipeline:                                      # line 62
    def __init__(self, vector_store: Any, embedder: Any, ontology_dir: Path | str,
                 schema: str = "ontology", table: str = "concepts") -> None: ...  # line 89

# parrot/knowledge/graphindex/backends.py   (pattern only — do not import)
class GraphBackendSpec(BaseModel):                                   # line 22
    name: str; factory: str; required_options: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = (); extra: str | None = None; project_options: str | None = None
def register_graph_backend(spec: GraphBackendSpec) -> None: ...      # line 46
def create_graph_persistence(backend: str, **options: Any) -> GraphPersistence: ...  # line 94

# parrot/knowledge/graphindex/pg_schema.py   (pattern only — do not import)
def validate_schema_name(schema: str) -> None: ...                   # line 34
def resolve_pg_settings(*, dsn: Optional[str] = None, schema: Optional[str] = None) -> PgSettings: ...  # line 78
def _ddl(schema: str) -> str: ...                                    # line 198
async def ensure_schema(pool: asyncpg.Pool, schema: str = DEFAULT_PG_SCHEMA) -> None: ...  # line 401
async def create_pg_pool(dsn: Optional[str] = None, *, schema: str = DEFAULT_PG_SCHEMA,
                         min_size: int = 1, max_size: int = 10, **kwargs: Any) -> asyncpg.Pool: ...  # line 483

# parrot/knowledge/wiki/store.py   (Phase 3 seam — NOT modified by this spec)
class WikiBackendSpec(BaseModel): ...                                # line 712
_BUILTIN_WIKI_BACKENDS: dict[str, WikiBackendSpec] = {...}           # line 782 — sqlite, memory, arangodb, postgres
def register_wiki_backend(name: str, factory: Callable[..., BaseWikiStore], *,
                          kind: Literal["local", "server"] = "server",
                          resolve_options: Callable[[Any], dict[str, Any]] | None = None) -> None: ...  # line 794
class BaseWikiStore(ABC): ...                                        # line 870

# parrot/cli/__init__.py
@click.group(cls=LazyGroup)
def cli(): ...                                                       # line 164-165
cli._lazy_commands = {...}                                           # line 170 — command name -> module path
cli._lazy_extras = {...}                                             # line 217 — command name -> install hint
# LazyGroup.get_command returns getattr(mod, cmd_name.replace("-", "_"))   # lines 99-100
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `VocabularyError` | `OntologyError` | subclass | `parrot/knowledge/ontology/exceptions.py:4` |
| `resolve_ontology_settings` | `resolve_setting` | function call | `parrot/knowledge/wiki/project.py:864` |
| `CatalogVocabularyPublisher.publish_tenant` | `ConceptCatalogService.get_live_concepts` | method call | `…/concept_catalog/service.py:457` |
| `CatalogVocabularyPublisher.publish_tenant` | table `ontology_concept_isa` | read-only `SELECT … WHERE tenant_id = $1 AND state = 'approved'` | table used at `…/concept_catalog/service.py:539` |
| `ConceptCatalogSyncWorker.run_once` | `CatalogVocabularyPublisher.publish_tenant` | method call after the batch transaction | `…/concept_catalog/worker.py:57-131` |
| `ontology` click group | `cli._lazy_commands` | new dict entry | `parrot/cli/__init__.py:170-174` |
| `vocabulary/http.py::register_routes` | aiohttp `app.router` | `add_get` | pattern at `…/concept_catalog/http.py:371-391` |
| `ontology-store` extra | `[project.optional-dependencies]` | new extra beside `graphindex-postgres` | `packages/ai-parrot/pyproject.toml:296` |
| Postgres integration tests | `default_dsn` fallback + `skipif` | fixture | `packages/ai-parrot/tests/knowledge/graphindex/test_persist_postgres.py:24-25` |
| conformance suite | `case_*` coroutine pattern | same shape | `packages/ai-parrot/tests/knowledge/graphindex/persistence_conformance.py:1-45` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.ontology.vocabulary`~~ — does not exist yet; this spec creates it.
- ~~`parrot.ontology`~~, ~~`parrot.knowledge.stores`~~, ~~`parrot.ontology.stores`~~ — the draft's
  package names; none exists. The ontology package is `parrot.knowledge.ontology`.
- ~~`OntologyStore`~~, ~~`KnowledgeStore`~~, ~~`resolve()` / `expand()` / `canonical()`~~ on any
  existing class — `parrot/knowledge/ontology/contracts.py` has only the instance-graph contracts.
- ~~`rdflib`~~, ~~`pyshacl`~~, ~~`surrealdb`~~, ~~`testcontainers`~~ — declared in no
  `pyproject.toml` of the workspace.
- ~~an asyncdb SurrealDB driver~~ — asyncdb has none.
- ~~a DDL or migration file for `ontology_concept`, `ontology_concept_isa`, `ontology_concept_audit`,
  `ontology_concept_outbox`~~ — the tables are used by `service.py` and `worker.py` but their DDL
  exists only as text in `sdd/specs/topic-authority-ontology.spec.md:169-264`. Do not add one here.
- ~~`ontology_concept_outbox.tenant_id`~~ — no such column; the tenant is in the payload JSON.
- ~~`ConceptCatalogService.list_isa_edges()`~~ or any method returning all approved is_a edges of
  a tenant — only `get_isa_subgraph(tenant_id, concept_id)` exists.
- ~~`parrot ontology`~~ — no such CLI command today.
- ~~a `knowledge-ontology` subsystem in `sdd/taxonomy/subsystems.yaml`~~ — the knowledge
  subsystems are `knowledge-wiki` and `knowledge-graphindex`.
- ~~an L1 synthesis-cache persistence layer~~ — `parrot/knowledge/retrieval/wiki_cache.py` has
  models only (Phase 3).
- ~~Turtle, SKOS or IRI handling anywhere in `parrot.knowledge.ontology`~~ — the coded ontology
  is layered YAML.
- The PostgreSQL schema name `ontology` is **taken** (pgvector table `ontology.concepts`); the
  vocabulary store must not create or alter anything in it.

### Edit Sites (Blueprint Anchors)

Verified against: `2d34bb3a8d` (local `dev`); none of these files differs on `origin/dev` `fb9bc0a33b`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/worker.py` | MODIFY | `        redis_client: Any,` | `worker.py:48` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/worker.py` | MODIFY | `        return len(rows)` | `worker.py:131` | 1 |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `    "wiki": "parrot.knowledge.wiki.cli",` | `__init__.py:174` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `graphindex-postgres = [` | `pyproject.toml:296` | 1 |
| `sdd/specs/helixdb-provider.spec.md` | MODIFY | `**Status**: approved` | `helixdb-provider.spec.md:14` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/contracts.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/exceptions.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/settings.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/backends.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/pg_schema.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/turtle.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/closure.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/shapes/parrot-core.shacl.ttl` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/publisher.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/postgres_store.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/snapshot.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/catalog_bridge.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/cli.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/http.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/` (test files of §4) | CREATE | — | — | — |
| `scripts/spikes/surrealdb_g1/` (harness files of Module 1) | CREATE | — | — | — |
| `tests/spikes/test_surrealdb_g1_harness.py` | CREATE | — | — | — |
| `sdd/state/FEAT-824/g1/report.md` | CREATE | — | — | — |
| `docs/decisions/graph-backends-postgres-surrealdb.md` | CREATE | — | — | — |
| `wiki/knowledge/ontology-backend-programme.md` | CREATE | — | — | — |
| `wiki/knowledge/ontology-vocabulary-store.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow

- **Registry by name with lazy factories** — never `if backend ==` branches
  (`GraphBackendSpec`, `parrot/knowledge/graphindex/backends.py:22`).
- **FEAT-520 PostgreSQL conventions** — asyncpg only, no SQLAlchemy, no `PgVectorStore` reuse;
  idempotent DDL with `IF NOT EXISTS`; extension checks that fail with an actionable message;
  settings resolved at call time, never at import.
- **One shared conformance suite** of backend-agnostic `case_*` coroutines
  (`persistence_conformance.py`).
- **PostgreSQL as writer of record with an outbox** drained by a `FOR UPDATE SKIP LOCKED` worker
  (`ConceptCatalogSyncWorker.run_once`); `publication_outbox` follows it.
- **Lazy package root** — PEP 562 `__getattr__`, as `parrot/knowledge/ontology/__init__.py`.
  `rdflib`, `pyshacl`, `asyncpg` and `numpy` are imported inside the modules that need them.
- **CPU-bound work off the event loop** — parsing, SHACL and closure go through a process pool;
  they exchange only picklable Pydantic models, never an `rdflib.Graph`.
- **Graph failures degrade to vector-only** (`OntologyRAGMixin`); the vocabulary store raises
  typed `VocabularyError`s so callers can keep that behaviour.
- Pydantic v2 models, Google-style docstrings, strict type hints, `self.logger`, aiohttp for HTTP.

### Known Risks / Gotchas

- **The engine is documented but untested here.** SurrealDB's capabilities come from the research
  note; the SDK 3.x is beta and transactions exist only over WebSocket. Mitigation: G1 runs
  first and Phases 3–4 wait for its verdict.
- **G1 cannot run in the worker sandbox.** It needs Docker and network access to pull the image
  and the SDK. Mitigation: a sandboxed worker delivers the harness and its unit test; the run and
  the report are a host step (§ Worktree Strategy).
- **Third choice of the research.** The note ranks PostgreSQL + AGE first and FalkorDB second,
  and recommends keeping ArangoDB as an optional adapter. The ADR must say why the decision
  differs; removal stays the last phase.
- **Two models of "ontology" coexist.** The YAML property-graph schema and its instance graph are
  untouched by Phase 2. The vocabulary store is a new object beside them until Phase 4 ports the
  consumers. Nothing in Phase 2 may change `parrot/knowledge/ontology/contracts.py`,
  `schema.py`, `graph_store.py`, `intent.py` or `validators.py`.
- **Schema name collision.** `ontology` already holds `ontology.concepts`. The store uses
  `ontology_store`; `validate_schema_name` guards the configurable name.
- **Catalog tables have no DDL in the repository.** The bridge only reads them; integration tests
  that need them create them from the DDL text in `topic-authority-ontology.spec.md`.
- **Tenancy axis.** The vocabulary is partitioned by `ontology_id`; tenants appear as
  `tenant.<tenant_id>` ontologies. A tenant's view over its own ontology plus a framework or
  domain ontology is a union across `ontology_id`s — composed by the caller, not by the store (§8).
- **Cross-ontology parents.** A tenant concept whose parent is a framework concept gets a
  `skos:broader` to an IRI outside its own ontology. It appears in that ontology's closure as an
  ancestor without an identity row; `get` on it returns `None`.
- **Trigram parity.** `pg_trgm` and the snapshot's Python `trigram_similarity` must rank alike.
  Mitigation: reference values recorded from `pg_trgm`; the conformance suite asserts ranked IRIs
  and `matched_by`, and scores within a tolerance of 0.02.
- **Closure retention.** Closure is stored per version and never replaced, so storage grows with
  versions × closure size. Phase 5 measures it; no pruning in this spec.
- **Embedding dimension.** `ONTOLOGY_EMBEDDING_DIM` fixes the column type at schema creation;
  changing it later is a migration, not a setting flip. GraphIndex's default is 1536, the draft's
  is 1024.
- **ANN index kind.** FEAT-520 measured `ivfflat` faster than `hnsw` on pgvector 0.5.0 at 5k
  rows; the draft asks for `hnsw`. The kind is a setting; the default follows the draft.
- **Blank nodes are rejected**, which excludes OWL restrictions and RDF lists (§8).
- **Sequencing.** FEAT-541 (`parrot-graphindex-package`, draft) will move the graph tree into its
  own distribution, and the unmerged branch `feat-255-ontology-rag-kb` touches the ontology
  package. The vocabulary package imports nothing from `parrot.knowledge.graphindex`; its one
  import from `parrot.knowledge.wiki.project` (`resolve_setting`) is lazy and isolated in
  `settings.py`.
- **Import ceilings.** `test_lazy_package_roots.py` and `test_import_ceilings.py` guard the
  knowledge tree; a module-level `import rdflib` in the package root would break them.
- **Size of the retirement.** 43 files outside the knowledge planes still reference ArangoDB; the
  roles of five of them were inferred, not read (proposal C11). Phase 7's spec must read them.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncpg` | `>=0.29` | PostgreSQL driver (already in `graphindex-postgres`) |
| `pgvector` | `>=0.2` | vector codec for asyncpg (already in `graphindex-postgres`) |
| `rdflib` | `>=7.0` (unverified — confirm the current release at implementation) | Turtle and JSON-LD parsing and serialisation |
| `pyshacl` | `>=0.26` (unverified — confirm the current release at implementation) | SHACL validation |
| `numpy` | `>=1.26` | snapshot vector similarity |
| `aiosqlite` | core (`>=0.17`) | snapshot reads |
| `surrealdb` (Python SDK) | pinned in the G1 harness only | spike; not added to any `pyproject.toml` in this spec |
| SurrealDB server image | 3.3.x, pinned by digest in the G1 harness | spike |

---

## Decisions

```yaml
schema_version: 1
document_id: ontology-backend
entries:
  - id: arangodb-retired-postgres-surrealdb
    statement: ArangoDB is retired from the workspace; the ontology vocabulary, GraphIndex and vectors are served by PostgreSQL, and the ontology instance graph and the wiki knowledge store by SurrealDB in server mode, subject to the G1 spike verdict.
    relation: constrains
    about: [knowledge-graphindex, knowledge-wiki]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py, file:packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py, file:packages/ai-parrot/src/parrot/knowledge/wiki/store.py]
    contradicts: []
    supersedes: []
    rationale: "ArangoDB binaries ship under a Community License without commercial-use rights and with a 100 GiB cap; the research note compares ten engines against four criteria (open-source non-enterprise, no paid SaaS, deployable on the AWS services in use, simpler platform). Reverses the non-goals of FEAT-540 and FEAT-670 that ArangoDB stays."
    rejected_alternatives: ["HelixDB (FEAT-670): single writer process, GPL-3.0 Python client", "PostgreSQL + Apache AGE: not installable on Amazon RDS", "FalkorDB: SSPL, per-graph write serialisation, no BM25", "JanusGraph: needs Cassandra plus Elasticsearch", "keep ArangoDB as an optional legacy adapter"]
  - id: new-backends-register-into-existing-seams
    statement: Every replacement backend is a registered implementation of an existing FEAT-540 contract; no parallel store abstraction is added beside those registries.
    relation: requires
    about: [knowledge-graphindex, knowledge-wiki]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py, file:packages/ai-parrot/src/parrot/knowledge/ontology/validators.py, file:packages/ai-parrot/src/parrot/knowledge/wiki/store.py]
    contradicts: []
    supersedes: []
    rationale: "FEAT-540 shipped contracts and registries for the ontology store, GraphIndex persistence, the wiki store and the source manifest; wikitoolkit, federation and the decision plane reach their backends only through them."
    rejected_alternatives: ["the draft's standalone KnowledgeStore Protocol as the only entry point"]
  - id: instance-graph-on-surrealdb-surrealql
    statement: The per-tenant ontology instance graph moves to a SurrealDB store that implements GraphDocumentStore and OntologyTraversalStore with dialect surrealql; traversal patterns carry a surrealql template and dynamic queries pass a surrealql validator.
    relation: constrains
    about: [knowledge-graphindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py, file:packages/ai-parrot/src/parrot/knowledge/ontology/schema.py, file:packages/ai-parrot/src/parrot/knowledge/ontology/validators.py]
    contradicts: []
    supersedes: []
    rationale: "User decision 2026-11-06. The dialect slot, per-dialect query_templates and the validator registry already exist; consumers barely change."
    rejected_alternatives: ["PostgreSQL edge tables with recursive CTEs", "retire traversal patterns and re-model consumers on resolve/expand plus search"]
  - id: vocabulary-append-only-versioned
    statement: The ontology vocabulary store is append-only and versioned; an IRI is never deleted, only deprecated, attribute changes close a row and insert a new one, and closure is retained per published version.
    relation: constrains
    about: [knowledge-graphindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/models.py, file:packages/ai-parrot/src/parrot/knowledge/ontology/concept_embedding.py]
    contradicts: []
    supersedes: []
    rationale: "Referential integrity between PostgreSQL and SurrealDB is by convention on the IRI; historical get/export and version-specific snapshots must stay reproducible."
    rejected_alternatives: ["physical deletion", "one mutable row per concept with since/until only", "closure recomputed in place on each publication"]
  - id: catalog-publishes-to-vocabulary
    statement: The reviewed concept catalog remains the authoring and review workflow for tenant concepts and publishes them into the vocabulary store as the ontology tenant.<tenant_id>; the vocabulary store is the single read model for concepts.
    relation: requires
    about: [knowledge-graphindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/worker.py, file:packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/service.py]
    contradicts: []
    supersedes: []
    rationale: "User decision 2026-11-06. Keeps the five-state review used by topic-authority while giving the router one place to resolve and expand."
    rejected_alternatives: ["retire the catalog and author every concept in Turtle", "keep catalog and vocabulary store as two separate authorities"]
  - id: arangodb-removal-is-last
    statement: No ArangoDB implementation, dependency, extra, Docker asset or test is removed before every tenant and plane is migrated, parity and permissions are verified, benchmarks pass and a rollback has been demonstrated.
    relation: forbids
    about: [knowledge-graphindex, knowledge-wiki]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py, file:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_arango.py, file:packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py]
    contradicts: []
    supersedes: []
    rationale: "Review requirement carried from the proposal: legacy code and infrastructure stay operational through the rollback window; new writes after cutover are never silently discarded."
    rejected_alternatives: ["remove ArangoDB code as each replacement lands"]
```

## Decision Waivers

<!-- none -->

## Consequences

<!-- decision-audit: input_digest=sha256:27017f5526f0981c604e5962813ef5721a8b4194ac198adf9e6dd931e28f1139 evaluation_digest=sha256:f0b0cce10740dbc572eb4ceac1d6245f64a01abe1d1cee0647915486774e01b3 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: arangodb-removal, graph-backend, knowledge-store, ontology, postgres, surrealdb
- Targets resolved: 12/12
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 12,
    "targets_total": 12,
    "unmapped_tags": [
      "arangodb-removal",
      "graph-backend",
      "knowledge-store",
      "ontology",
      "postgres",
      "surrealdb"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:f0b0cce10740dbc572eb4ceac1d6245f64a01abe1d1cee0647915486774e01b3",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:27017f5526f0981c604e5962813ef5721a8b4194ac198adf9e6dd931e28f1139",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:cca3a4e298ec5a4390554c560c09716266faa7eaa7b00b07e528dd2b9a012226",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```

## 8. Open Questions

> Questions that must be resolved before or during implementation.

Resolved — carried forward, not to be re-opened:

- [x] How does FEAT-824 relate to FEAT-670 (HelixDB provider)? — *Resolved in proposal*:
      "Sustituir FEAT-670" — PostgreSQL + SurrealDB replace the HelixDB plan; FEAT-670 is
      cancelled and an ADR records the licence decision. → Module 2, `## Decisions`.
- [x] How far does "remove ArangoDB" reach? — *Resolved in proposal*: "Todo el workspace" — every
      consumer in the four distributions. → §2 roadmap, Phase 7; D-P7.
- [x] Which ontology model does the new backend serve? — *Resolved in proposal*: "Adoptar el RDF
      del borrador". → §2 Phase 2, Modules 3–9.
- [x] Does FEAT-824 include the SurrealDB KnowledgeStore for wiki, Bookstore and L1? —
      *Resolved in proposal*: "KnowledgeStore completo". → §2 roadmap, Phase 3 (follow-on spec).
- [x] What evidence backs the licence and engine premises, and why not Apache AGE? — *Resolved in
      proposal*: the research note; "se descartó Apache AGE porque no se puede instalar en Amazon
      AWS y cualquier servicio SaaS de pago, solo servicios open-source no-enterprise y que a su
      vez descomplejize la plataforma". → §1 Non-Goals, D-P1, Module 2.
- [x] Where do the per-tenant instance graph and its machinery go? — *Resolved 2026-11-06 (spec
      Q&A)*: SurrealDB behind the FEAT-540 seam, dialect `surrealql`. → D-P3, G1-11, G1-12.
- [x] What does this spec cover? — *Resolved 2026-11-06 (spec Q&A)*: the programme architecture
      plus Phases 1–2; later phases in follow-on specs after G1. → §2 roadmap, §3.
- [x] How does the existing concept catalog coexist with the OntologyStore? — *Resolved
      2026-11-06 (spec Q&A)*: the catalog publishes to the store. → §2, Module 10.

Open:

- [ ] The research note `sdd/proposals/Grafos open source para ai-parrot.md` is untracked, and the
      ADR and this spec cite it by path. It must be committed before Module 2 lands. — *Owner: Jesus Lara*
- [ ] FEAT-670 has 26 `pending` tasks in `sdd/tasks/index/helixdb-provider.json`. Module 2 changes
      only the spec status line. How should those tasks leave `/sdd-next` — set to `cancelled`
      (one precedent in the indexes), or another mechanism? — *Owner: Jesus Lara*
- [ ] The proposal is still `status: discussion` and holds uncommitted review corrections from
      another session; this spec was built from the working-tree text. Confirm that text, or
      re-run `/sdd-spec` after it changes. — *Owner: Jesus Lara*
- [ ] Namespaces `urn:parrot:core:`, `urn:parrot:tenant:<tenant_id>:` and
      `urn:parrot:framework:` are introduced here for parrot-defined predicates and for catalog
      concepts. Confirm them, or name the HTTP IRIs to use instead, before the first publication
      — IRIs cannot be renamed afterwards, only deprecated. — *Owner: Jesus Lara*
- [ ] Blank nodes are rejected in v1, which rules out OWL restrictions and RDF lists. Confirm no
      ontology planned for the first publications needs them. — *Owner: Jesus Lara*
- [ ] Which framework or domain ontology supplies the parents that catalog is_a edges reference
      with `parent_tier = "framework"`, and under which `ontology_id`? Until one is published,
      those parents are IRIs with no identity row. — *Owner: Jesus Lara*
- [ ] Default embedding dimension: 1024 (draft) or 1536 (GraphIndex default)? It fixes the column
      type at schema creation. — *Owner: Jesus Lara*
- [ ] The decision-audit taxonomy has no ontology subsystem, so the `## Decisions` entries are
      filed under `knowledge-graphindex` and `knowledge-wiki`. Add a `knowledge-ontology`
      subsystem? — *Owner: Jesus Lara*
- [ ] Where is the canonical Turtle archived outside PostgreSQL (`version.turtle_uri`, S3 in the
      draft)? This spec stores it in `version.turtle_canonical` and leaves `turtle_uri` empty. —
      *Owner: deferred to Phase 3 (deployment)*
- [ ] Follow-ups the later specs must answer by reading code: real roles of `stores/arango.py`,
      `interfaces/hierarchy.py`, `parrot_tools/wiki/toolkit.py`, the formdesigner sink and
      `routing/rules.py`; which wiki namespaces use `backend=arangodb`; the state of the
      `feat-255-ontology-rag-kb` branch. — *Owner: follow-on specs*

---

## Worktree Strategy

- **Isolation**: one feature worktree for this spec; the `sdd-coder` engine gives each task its
  own sub-worktree inside it.
- **Module dependency graph** (an edge means "needs the symbols of"):
  - M4 → M3 (`OntologyStoreSettings`, exceptions)
  - M5 → M3 (`OntologyContent`, `ValidationIssue`, `ClosureRow`)
  - M6 → M3, M4, M5 (`ensure_schema`, `parse_turtle`, `validate_content`, `build_closure`)
  - M7 → M3, M4, M5 (`serialize`, `content_checksum`)
  - M8 → M3, M5 (`VersionContent`, `serialize`, `content_checksum`)
  - M9 → M6, M7, M8
  - M10 → M6 (`OntologyPublisher`, `publish_content`)
  - M11 → M6, M7, M8, M10
  - M12 → M1 … M11
  - M1 and M2 have no edge to any other module and none between them.

  Expected to run concurrently: {M1, M2, M3}; then {M4, M5}; then {M6, M7, M8}; then
  {M9, M10}; then M11; then M12.
- **Shared files**: none between modules. `vocabulary/__init__.py` is written once by M3 with the
  full lazy export table; `pyproject.toml` and `cli/__init__.py` are touched only by M11;
  `worker.py` only by M10.
- **Exclusive resources**:
  - M1's *run* needs Docker and network access; a sandboxed worker cannot do it. The harness and
    its unit test are an ordinary task; running it and committing the report is a host step by
    the operator (`parallel: false`).
  - PostgreSQL integration tests share one database but each uses its own uniquely named schema,
    so they are not exclusive.
  - M11 edits `packages/ai-parrot/pyproject.toml`; it must not regenerate `uv.lock` beyond the
    new extra and must not run `uv sync` in the worktree.
- **Cross-feature dependencies**: FEAT-540 and FEAT-520 are merged. FEAT-670 is superseded and
  must not be started. FEAT-541 (draft) touches the same package tree — coordinate before either
  moves files. The research note must be tracked before M2 lands.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: — · Status: skipped (the proposal's status is
> `discussion`, not `accepted`) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/knowledge/ontology-backend-programme.md` — create: the ArangoDB retirement programme —
    plane-to-destination table, binding decisions, phases and gates, the G1 verdict, and what is
    and is not removed yet.
  - `wiki/knowledge/ontology-vocabulary-store.md` — create: the OntologyStore — data model and
    temporal semantics, publishing Turtle, validation rules and issue codes, `resolve` and
    `expand`, snapshots and offline use, settings, the `parrot ontology` CLI, the HTTP routes,
    and how the concept catalog publishes into it.
- **API modules**:
  - `parrot.knowledge.ontology.vocabulary`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-06 | Jesus Lara (with Claude) | Initial draft: programme architecture plus Phases 1–2 |
