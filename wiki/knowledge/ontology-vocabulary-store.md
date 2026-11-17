---
title: Ontology vocabulary store
summary: Versioned RDF vocabularies on PostgreSQL with offline SQLite snapshots — publishing Turtle, resolve and expand, the ONTOLOGY_* settings, the parrot ontology CLI and HTTP routes (FEAT-824).
---

# Ontology vocabulary store

## Purpose

The vocabulary store holds versioned RDF vocabularies — classes, properties, SKOS concepts, their
labels and their hierarchies — one per `ontology_id`. Every publication creates an immutable
version. Every read captures one published version and reads only at it.

Two backends implement the read contract `OntologyStore`:

- `PostgresOntologyStore` reads from PostgreSQL. `PostgresOntologyPublisher` is the only writer.
- `SnapshotOntologyStore` reads from read-only SQLite files. It works offline and reports when its
  data may be behind the central store.

Use `resolve` to turn a free-text term into concept IRIs. Use `expand` to get the closure of
concepts, for example all subclasses of a class, and then filter another store by those IRIs
(D-P4 in the [programme page](ontology-backend-programme.md)). The vocabulary plane is separate
from the instance graph in `parrot.knowledge.ontology.contracts`.

The programme status and the G1 verdict are on the [programme page](ontology-backend-programme.md).

### Data model and temporal semantics

- Every concept, label, relation and statement row carries `since_version` and `until_version`.
  A row is visible at version `v` when `since_version <= v` and (`until_version` is NULL or
  `v < until_version`). Intervals are half-open.
- Changing an attribute closes the current row and inserts a new one. Nothing is overwritten.
  A relation removed in v2 and reintroduced in v3 is two rows.
- `as_of` must satisfy `1 <= as_of <= current_version`. Any other value raises
  `OntologyVersionNotFound`. Version 0 means the ontology is registered but never published.
- The closure (`subclass`, `subproperty`, `broader`, `partof`) is computed and stored for each
  version. Depth 0 is the reflexive row.
- The checksum is the SHA-256 of the sorted N-Triples of the asserted graph. Inferred relations
  are excluded. `export(as_of=v)` regenerates the graph from the rows, and its canonical form
  must hash to `version.checksum`. That equality is the temporal-fidelity check.
- Publishing an unchanged graph returns the current version with `changed=False` and writes
  nothing.

### Publishing Turtle

The publication pipeline is:

1. Parse the Turtle with rdflib. Blank nodes are rejected.
2. Validate with SHACL (the bundled `parrot-core.shacl.ttl` plus an optional caller shapes file) and
   with the parrot rules.
3. Diff against the current version.
4. Compute the closure and, if an embedding function was given, the concept embeddings.
5. In one transaction, lock the ontology row, check that the base version has not moved, insert
   version N+1 with the closure and the publication outbox row, and update `current_version`.

Parsing, validation and closure run in a single-worker process pool, not on the event loop. If the
base version moves while the candidate is prepared, the transaction is retried up to
`MAX_PUBLISH_RETRIES` (3) times, then `PublishConflict` is raised.

`PostgresOntologyPublisher(pool, schema=None, embed=None, executor=None)` owns the process pool
only when it created it. Call `close()` to shut that pool down. The pool passed in belongs to the
caller.

### Validation rules and issue codes

Validation collects every issue, not only the first. A rejected publication writes nothing.

| Code | Raised when |
|---|---|
| `SYNTAX` | the Turtle does not parse (raised before the other rules run) |
| `BLANK_NODE_UNSUPPORTED` | the graph contains any blank node; OWL restrictions and RDF lists need them |
| `IRI_OUTSIDE_BASE` | a concept IRI does not start with the ontology's `base_iri` |
| `IRI_REMOVED` | an IRI present in the current version is missing from the candidate; deprecate it instead (`owl:deprecated true`, optionally `dcterms:isReplacedBy`) |
| `HIERARCHY_CYCLE` | a cycle exists in the `subclass`, `subproperty`, `broader` or `partof` family |
| `MISSING_PREF_LABEL` | a class or `skos:Concept` has no `skos:prefLabel` |
| `SHACL` | a bundled or caller shape fails; the bundled shapes require `skos:prefLabel` on `skos:Concept`, IRI objects for `skos:broader` and `rdfs:subClassOf`, and a boolean `owl:deprecated` |

The CLI prints each issue to stderr as `CODE: message [subject]` and exits with status 1.

### resolve and expand

`resolve(ontology_id, term, *, lang, k, kinds, embedding)` is a hybrid lookup at the current
version. It matches:

- exact, case-insensitive, on any label;
- trigram similarity above `0.45` (the `pg_trgm` measure);
- cosine similarity to the query `embedding`, when one is given.

The matches are fused with reciprocal rank fusion (`k = 60`). Each result carries `matched_by`.
Deprecated concepts are excluded. At most `k` results are returned.

`expand(ontology_id, iris, *, family, direction, max_depth, include_deprecated, as_of)` returns
the closure of `iris` at one version. The result always contains the input IRIs.

- `direction="down"` returns descendants, the narrower concepts. `"up"` returns ancestors.
  `"both"` returns the union.
- Deprecated concepts are left out unless `include_deprecated=True`.

`canonical(ontology_id, iris)` follows `replaced_by` to a live IRI, at most 16 hops and cycle-safe.
IRIs that do not change are omitted from the result.

`export(ontology_id, fmt, *, as_of)` serialises the asserted graph as Turtle or JSON-LD. Inferred
relations are left out.

### Snapshots and offline use

A snapshot is one read-only SQLite file per `(ontology_id, version)`:

```
{ONTOLOGY_SNAPSHOT_DIR}/{ontology_id}/v{version}.sqlite
```

It holds only the rows visible at that version and that version's closure. Embeddings are stored
as float32 BLOBs. Labels are indexed by an FTS5 trigram table. A `meta` table records the
checksum and the base IRI.

- `build_snapshot` writes a `.tmp` file and renames it atomically. An existing file with the same
  checksum is reused. An existing file with a different checksum raises `ValueError`.
- `SnapshotOntologyStore(snapshot_dir, source=None)` treats the newest `v*.sqlite` as the current
  version. Vector similarity is computed in process with NumPy.
- A snapshot declares its own version and rejects any other `as_of` with `OntologyVersionNotFound`.
- With a `SnapshotSource`, the store refreshes once per ontology. When the source is unreachable it
  keeps serving the newest local file and `status()` reports `stale=True`. If there is no local file
  and no reachable source, `OntologyNotFound` is raised.

`HttpSnapshotSource(base_url)` reads `GET {base}/vocabularies/{ontology_id}/version` and
`GET {base}/vocabularies/{ontology_id}/snapshot?version=N`. The `snapshot` backend creates it from
`ONTOLOGY_SNAPSHOT_URL` when no source is passed. That setting is the base URL of the vocabulary
routes (`.../api/ontology`).

## Public API

- [`OntologyStore`](ref:parrot.knowledge.ontology.vocabulary.contracts) — read contract; every call reads one published version
- [`OntologyPublisher`](ref:parrot.knowledge.ontology.vocabulary.contracts) — write contract: `ensure_ontology`, `publish`, `publish_content`
- [`PostgresOntologyStore`](ref:parrot.knowledge.ontology.vocabulary.postgres_store) — PostgreSQL read backend (see Gotchas before relying on its read methods)
- [`PostgresOntologyPublisher`](ref:parrot.knowledge.ontology.vocabulary.publisher) — the only writer; runs the publication pipeline
- [`SnapshotOntologyStore`](ref:parrot.knowledge.ontology.vocabulary.snapshot) — read-only SQLite backend for offline and local use
- [`create_ontology_store`](ref:parrot.knowledge.ontology.vocabulary.backends) — builds a store by backend name; defaults to `ONTOLOGY_BACKEND`
- [`register_vocabulary_backend`](ref:parrot.knowledge.ontology.vocabulary.backends) — registers or replaces a `VocabularyBackendSpec`
- [`VocabularyBackendSpec`](ref:parrot.knowledge.ontology.vocabulary.backends) — registry entry: name, `module:callable` factory, required options, pip extra
- [`ConceptRef`](ref:parrot.knowledge.ontology.vocabulary.contracts), [`Resolution`](ref:parrot.knowledge.ontology.vocabulary.contracts), [`PublishResult`](ref:parrot.knowledge.ontology.vocabulary.contracts), [`StoreStatus`](ref:parrot.knowledge.ontology.vocabulary.contracts) — result models
- [`ValidationIssue`](ref:parrot.knowledge.ontology.vocabulary.contracts) — one reason a publication was rejected
- [`OntologyStoreSettings`](ref:parrot.knowledge.ontology.vocabulary.settings) and [`resolve_ontology_settings`](ref:parrot.knowledge.ontology.vocabulary.settings) — resolved `ONTOLOGY_*` settings
- [`VocabularyError`](ref:parrot.knowledge.ontology.vocabulary.exceptions) — base error; subclasses `OntologyNotFound`, `OntologyVersionNotFound`, `OntologyValidationError` (carries `issues`) and `PublishConflict`

## Configuration & Parameters

### Settings

Each setting is resolved at call time: explicit argument, then environment, then navconfig, then the
default.

| Key | Default | Meaning |
|---|---|---|
| `ONTOLOGY_BACKEND` | `postgres` | backend used by `create_ontology_store()`: `postgres` or `snapshot` |
| `ONTOLOGY_PG_DSN` | none | asyncpg DSN. Required for `postgres`; `create_ontology_pg_pool` raises `ValueError` without it |
| `ONTOLOGY_PG_SCHEMA` | `ontology_store` | schema that holds the tables. Must match `^[a-z_][a-z0-9_]*$` |
| `ONTOLOGY_EMBEDDING_DIM` | `1024` | dimension of `concept.embedding`, fixed when the schema is created |
| `ONTOLOGY_ANN_INDEX_KIND` | `hnsw` | ANN index on current embeddings: `hnsw` or `ivfflat` |
| `ONTOLOGY_SNAPSHOT_DIR` | `~/.parrot/ontology` | snapshot root |
| `ONTOLOGY_SNAPSHOT_URL` | none | base URL of the vocabulary HTTP routes, read by the snapshot backend |
| `ONTOLOGY_DEFAULT_LANG` | `es` | language of labels that declare none |

### PostgreSQL schema

`ensure_schema(pool, schema=None, *, embedding_dim=None, ann_index_kind=None)` is idempotent. It:

- creates the `vector` and `pg_trgm` extensions. If one cannot be created it raises `RuntimeError`
  with an actionable message;
- creates the schema, the tables and the non-ANN indexes;
- creates the ANN index on current `concept.embedding` rows.

It never touches the existing `ontology` schema, which holds the pgvector table `ontology.concepts`.

### CLI: `parrot ontology`

The group is registered lazily in `parrot.cli` and needs the `ontology-store` extra:
`pip install ai-parrot[ontology-store]`. Every database command accepts:

- `--dsn TEXT` — asyncpg DSN, default `ONTOLOGY_PG_DSN`;
- `--schema TEXT` — schema name, default `ONTOLOGY_PG_SCHEMA` or `ontology_store`.

| Command | Arguments and options | Effect |
|---|---|---|
| `init-schema` | `--dsn`, `--schema` | creates the vocabulary schema if missing |
| `register ONTOLOGY_ID` | `--base-iri TEXT` (required), `--title TEXT` | registers the ontology at version 0 |
| `publish ONTOLOGY_ID TURTLE_FILE` | `--shapes FILE`, `--notes TEXT` | publishes one Turtle file as the next version |
| `version ONTOLOGY_ID` | — | prints the current published version |
| `export ONTOLOGY_ID` | `--as-of N`, `--format turtle\|jsonld` (default `turtle`), `-o FILE` | writes the version to stdout or a file |
| `snapshot ONTOLOGY_ID` | `--version N`, `--dest DIR`, `--from-turtle FILE` with `--base-iri TEXT` | builds a SQLite snapshot from PostgreSQL, or from a Turtle file without any database |
| `publish-catalog` | `--tenant TEXT` (required), `--catalog-dsn DSN` | publishes one tenant's approved concept catalog as `tenant.<tenant>` |

`--base-iri` is required with `--from-turtle` and rejected without it.

### HTTP routes

`register_routes(app, prefix="/api/ontology")` adds three read-only routes. The host application must
call it and set `app["ontology_store"]` to a store. The handlers read that key.

| Route | Returns |
|---|---|
| `GET {prefix}/vocabularies/{ontology_id}/version` | JSON `{"ontology_id", "version", "checksum"}`; `version` 0 with `checksum` null when never published |
| `GET {prefix}/vocabularies/{ontology_id}/snapshot[?version=N]` | the SQLite snapshot, built on demand under `ONTOLOGY_SNAPSHOT_DIR` and cached |
| `GET {prefix}/vocabularies/{ontology_id}/export[?as_of=N&fmt=turtle\|jsonld]` | the asserted graph as Turtle or JSON-LD |

Authorization applies to all three routes:

- no session: `401`;
- an ontology whose id starts with `tenant.` is visible only to a session whose `tenant_id` matches
  the suffix, or to a session in the `topic_admin` group. Anyone else gets `403`.

## Usage Examples

### Publish Turtle with the CLI

Start from an empty database. Register the ontology before the first publication: `publish` raises
`OntologyNotFound` for an unregistered ontology. The example Turtle below uses only constructs the
parse and validation rules accept: typed classes, a `skos:prefLabel` on each, a subclass IRI, and a
base IRI that prefixes every concept.

```turtle
# legal_es.v1.ttl
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

<https://example.org/legal/es/Contrato> a owl:Class ;
    skos:prefLabel "Contrato"@es .

<https://example.org/legal/es/ContratoArrendamiento> a owl:Class ;
    skos:prefLabel "Contrato de arrendamiento"@es ;
    rdfs:subClassOf <https://example.org/legal/es/Contrato> .
```

```bash
parrot ontology init-schema --dsn "$ONTOLOGY_PG_DSN"
parrot ontology register legal_es --base-iri https://example.org/legal/es/ --title "Legal (es)"
parrot ontology publish legal_es legal_es.v1.ttl --notes "first release"
parrot ontology version legal_es
parrot ontology export legal_es --as-of 1 --format turtle -o legal_es.v1.exported.ttl
```

The `publish` command prints `version=… changed=… added=… changed_iris=… deprecated=…
relations_added=… relations_closed=…`. Publishing the same file again prints `changed=false` and
creates no version. The CLI does not pass an embedding function, so concept embeddings stay NULL
after a CLI publication.

### Resolve and expand offline

This example uses the snapshot backend, which needs no database. It assumes a snapshot for
`legal_es` exists under the snapshot directory. See the snapshot example below.

```python
from parrot.knowledge.ontology.vocabulary import create_ontology_store

store = create_ontology_store("snapshot", snapshot_dir="/srv/parrot/ontology")
try:
    hits = await store.resolve("legal_es", "Contrato de arrendamiento", k=5)
    if hits:
        iris = await store.expand(
            "legal_es",
            [hits[0].concept.iri],
            family="subclass",
            direction="up",  # ancestors of the matched concept
        )
    status = await store.status("legal_es")  # version, backend and stale flag
finally:
    await store.close()
```

Pass `embedding=` to `resolve` to add vector similarity. The query vector must have the same
dimension as the snapshot's stored embeddings.

### Build a snapshot offline from Turtle

```bash
parrot ontology snapshot legal_es --from-turtle legal_es.v1.ttl \
    --base-iri https://example.org/legal/es/ --version 1 --dest /srv/parrot/ontology
```

The command prints the path of the file written, `/srv/parrot/ontology/legal_es/v1.sqlite`. Without
`--from-turtle` the command reads the version from PostgreSQL instead.

### Create the PostgreSQL backend in Python

```python
from parrot.knowledge.ontology.vocabulary import create_ontology_store

store = create_ontology_store("postgres", dsn="postgresql://user:secret@db/parrot")
```

The DSN can also come from `ONTOLOGY_PG_DSN`. The store opens its pool on first use and closes it
in `close()`. Read the Gotchas below before calling its read methods.

### Publish a tenant's concept catalog

The reviewed concept catalog publishes into the vocabulary store as the ontology
`tenant.<tenant_id>`. The bridge is `CatalogVocabularyPublisher`. The concept-catalog sync worker
calls it after each outbox batch when it is given a publisher:

```python
from parrot.knowledge.ontology.concept_catalog.worker import ConceptCatalogSyncWorker
from parrot.knowledge.ontology.vocabulary.catalog_bridge import CatalogVocabularyPublisher

bridge = CatalogVocabularyPublisher(catalog_pool, publisher)
worker = ConceptCatalogSyncWorker(
    pg_pool,
    graph_store,
    redis_client,
    vocabulary_publisher=bridge,
)
```

Each distinct `tenant_id` in a batch is republished once. A failure is logged and never raised,
so the ArangoDB materialisation is not affected. `parrot ontology publish-catalog --tenant <id>`
runs the same publication once from the command line.

The catalog maps as follows:

| Catalog | Vocabulary |
|---|---|
| approved `ConceptRow` | concept of kind `skos_concept`, IRI `urn:parrot:tenant:<tenant_id>:<slug>` |
| `label` and `synonyms` | `skos:prefLabel` and `skos:altLabel`, language from `ONTOLOGY_DEFAULT_LANG` |
| `description` | `skos:definition` |
| `domain` | statement with predicate `urn:parrot:core:domain` |
| approved `IsaEdgeRow`, tenant parent | `skos:broader` to the parent concept's IRI |
| approved `IsaEdgeRow`, framework parent | `skos:broader` to `urn:parrot:framework:<parent_ref>` |
| a concept that is no longer approved | kept in the store with `deprecated = true` |

Publication is a full-state projection. Publishing an unchanged catalog creates no version, so the
call is idempotent.

## Gotchas

- **PostgreSQL read paths are not verified.** The live conformance suite (TASK-5264) skipped its
  PostgreSQL cases because no live server was available. A static review of
  `PostgresOntologyStore` found SQL that cannot run as written:
  - `get`, `neighbors` and `canonical` pass one bind parameter as both an IRI and the version, and
    `neighbors` and `canonical` pass fewer or more values than the query uses;
  - `resolve` compares label text to the version number, and its join refers to an ambiguous
    `ontology_id`;
  - `expand` selects an `iri` column that the closure table does not have, `max_depth` rewrites
    every `FROM`, and the `both` direction appends a condition after its subquery.

  `version`, `status` and `export` (through `load_version`) use code paths that the review did not
  flag. Those paths are still unexecuted against a live server. Until the conformance suite passes
  against a live server, use the snapshot backend for reads.
- **Schema name is `ontology_store`, not `ontology`.** The schema `ontology` already holds the
  pgvector table `ontology.concepts`. The store never creates or alters anything in it.
- **Blank nodes are rejected in v1.** OWL restrictions and RDF lists cannot be published. Model them
  as named concepts or statements instead.
- **The embedding dimension is fixed at schema creation.** `ONTOLOGY_EMBEDDING_DIM` sets the column
  type. Changing it later is a migration, not a setting change. The draft's default is 1024 and
  GraphIndex's default is 1536; the choice is still open.
- **IRIs cannot be renamed.** An IRI that is removed fails with `IRI_REMOVED`. Deprecate it with
  `owl:deprecated true` and point `dcterms:isReplacedBy` at its successor. The
  `urn:parrot:*` namespaces are also still open for confirmation before the first publication.
- **`base_iri` is a string prefix.** A concept IRI must start with it exactly. A base of
  `https://example.org/legal/es` (without the trailing `/`) accepts `…/legal/escritorio` as well.
- **Cross-ontology parents are not stored.** A tenant concept whose parent is a framework concept
  gets a `skos:broader` to an IRI outside its own ontology. That IRI appears in the closure but has
  no identity row there, so `get` on it returns `None`.
- **`publish_content` can raise `OntologyValidationError` with an empty `issues` list** when the
  candidate's `base_iri` differs from the registered one. `publish()` always uses the registered
  base, so only direct calls to `publish_content` can hit this.
- **`ensure_ontology` refuses a different base IRI** for an existing ontology with `ValueError`.
- **Trigram parity is by design, not by a recorded test here.** The snapshot's `trigram_similarity`
  follows `pg_trgm`. The conformance suite is the place to check that ranks and scores agree.
- **Closure is retained per version.** Storage grows with versions times closure size. No pruning
  is implemented.
- **`snapshot --from-turtle` does not catch validation errors.** An invalid Turtle file raises
  an uncaught `OntologyValidationError` from the command.
- **Concept embeddings are NULL unless an `embed` function is given** to `PostgresOntologyPublisher`.
  The CLI does not pass one, so vector matching in `resolve` has nothing to match against.

## Related

- [Ontology backend programme](ontology-backend-programme.md) — phases, binding decisions, the G1 verdict and the ArangoDB retirement gate.
- [ADR-0010: graph backends, PostgreSQL and SurrealDB](../../docs/decisions/graph-backends-postgres-surrealdb.md) — the accepted decision behind this plane.
