---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Local LanceDB Vector, Full-Text and Hybrid Search

**Feature ID**: FEAT-542
**Date**: 2026-09-10
**Author**: Codex, with product approval pending from Jesus Lara
**Status**: approved
**Target version**: next minor release
**Source**: [Brainstorm](../proposals/lancedb-vector-store.brainstorm.md), [proposal](../proposals/lancedb-vector-store.proposal.md)
**Research provenance**: FEAT-563 identifies the earlier proposal findings, not this implementation feature. The official allocator reserved FEAT-542 for this spec on `dev`.

---

## 1. Motivation & Business Requirements

### Problem Statement

Local autonomous agents need persistent semantic and lexical retrieval without provisioning PostgreSQL, pgvector, Docker, or a storage service. They should also be able to combine this local corpus with existing GraphIndex retrieval through the multi-store toolkit.

The repository has store and origin abstractions suitable for this integration, but no LanceDB backend or LanceDB hybrid origin. Selecting a different storage engine must not require changing configured model providers or replacing existing PostgreSQL deployments.

### Goals

- Add optional local-directory LanceDB storage with persistent collections, ingestion, upserts, deletion, vector search, native FTS and native hybrid search.
- Integrate with existing store dispatch, `VectorStoreSearchTool`, `VectorStoreOrigin`, and a new explicit `LanceDBOrigin` for hybrid federation.
- Combine LanceDB hybrid results with a separately configured existing `GraphIndexOrigin` in one toolkit request.
- Preserve metadata, stable identities, default parent exclusion, native scores and origin provenance.
- Make lexical queries independent of embedding-model construction and inference.
- Provide async operations, explicit errors, safe reopen behavior and an installation/configuration guide.

### Draft Decision Baseline

This spec develops brainstorm **Option A**. All five original scope questions are now answered in section 8 and those answers are binding: vector/FTS/hybrid **plus** optional graph federation in v1; a **fully offline agent after provisioning** (not merely embedded storage behind remote providers); **independent processes may write the same dataset concurrently**; graph **federation only**, never replacing the GraphIndex seed index; and **whole-origin failure** when a hybrid leg fails. The concurrency and offline answers supersede the draft's original single-writer / storage-only-offline assumptions wherever older text survives — TASK-3057 owns the reconciliation and must prove both contracts against the pinned SDK before dependent work starts.

### Non-Goals (explicitly out of scope)

- Changing the default store, migrating PostgreSQL data, removing PostgreSQL dependencies, or making the entire agent stack dependency-free.
- Downloading, provisioning or vendoring model weights, or shipping a bundled local model. A **fully offline agent after provisioning** IS in scope (section 8) and is proven by I8/AC6, but the feature supplies the offline *profile and proof*, not the weights.
- Replacing GraphIndex's internal semantic seed index or building graph artifacts from LanceDB rows.
- A generic hybrid API for all stores, adaptive-router/`StoreType` expansion, or changing toolkit ranking/deduplication.
- Distributed transactions, cloud/object-storage URIs, remote or network-filesystem guarantees. **Independent concurrent writer processes over one local directory ARE in scope** (section 8); what stays out of scope is any guarantee beyond a single local filesystem.
- ANN training/tuning, non-cosine vector metrics, MMR, arbitrary SQL, automatic schema migration, automatic version pruning, or corpus-scale latency/recall guarantees in v1.

---

## 2. Architectural Design

### Overview

Add `LanceDBStore(AbstractStore)` to the embeddings satellite. It owns all SDK access, persistent schema, filters, lazy embeddings and result conversion. Add `LanceDBOrigin(SearchOrigin)` to the tools satellite; it selects vector or native hybrid retrieval and normalizes results into `OriginHit`. The backend must not import the tools distribution.

Use exact cosine search initially, including for small and empty tables. Create a native FTS index during collection preparation. Native hybrid combines an explicitly generated query vector with query text; it does not install or invoke LanceDB's embedding registry. Current LanceDB documentation describes vector/FTS fusion with default reciprocal-rank fusion (RRF). [Official hybrid search documentation](https://docs.lancedb.com/search/hybrid-search).

### Component Diagram

```text
Existing vector tool/origin ──────────────┐
                                         v
MultiStoreSearchToolkit ── LanceDBOrigin ── LanceDBStore ── local LanceDB directory
          │                 vector/hybrid       │              vectors + native FTS
          │                                     └── existing embedding provider
          │                                         (ingest/vector/hybrid only)
          └─────────────── GraphIndexOrigin ── existing graph + seed source
                                                    └── optional SQLite FTS reader
```

### Integration Points

| Existing component | Integration | Required behavior |
|---|---|---|
| `AbstractStore` | New subclass | Implement every abstract operation; preserve signature-compatible adapters |
| Core `supported_stores` | Add `"lancedb": "LanceDBStore"` | Dynamic import resolves `parrot.stores.lancedb`; existing entries unchanged |
| Existing embedding registry/provider | Lazy reuse | Configure without loading a model; generate vectors only when needed |
| `VectorStoreSearchTool` | Existing factory and query path | Accept documented table/column aliases and cosine threshold semantics |
| `VectorStoreOrigin` | Existing adapter | Vector search and standalone FTS work without modification |
| Origin exports | Add `LanceDBOrigin` | Importing tools/origins must not require the LanceDB SDK |
| `MultiStoreSearchToolkit` | Compose existing origins | Preserve grouped native order, final BM25 reranking, deduplication and isolated errors |
| `GraphIndexOrigin` | Reuse unmodified | Its own retriever and optional reader remain separately configured |

### Configuration and Compatibility

The new `LanceDBConfig` is a Pydantic model for backend-owned settings. Constructor arguments remain compatible with `AbstractStore`; configuration normalization happens once, before SDK operations.

| Setting | Contract |
|---|---|
| `uri: str` | Required non-empty local directory; canonicalize path; reject URI schemes and do not fall back to another directory |
| `collection_name: str` | Default `my_collection`; names match `[A-Za-z_][A-Za-z0-9_]{0,127}`; `table` is a compatibility alias; conflicting explicit names raise `ValueError` |
| `dimension: int` | Positive, default 768; fixed for each collection; validate every vector before persistence/query |
| `metric_type: str` | `COSINE` only, case-insensitive; reject other metrics explicitly |
| `index_type: str` | `FLAT` only, case-insensitive; direct backend default is `FLAT`; factory users explicitly override `StoreConfig`'s `IVF_FLAT` default |
| `embedding_model` / `embedding` | Retain existing configuration forms; accept a provider exposing async `embed_documents` and `embed_query`; do not instantiate or call it for FTS |
| `embedding_id: str \| None` | Explicit stable identity required for an injected provider; otherwise derive from normalized model/provider/revision configuration, excluding credentials |
| `metadata_fields: dict[str, Literal["str", "bool", "int", "float"]]` | Fixed typed projection, merged with reserved standard fields below; incompatible redeclarations rejected |
| `read_consistency_interval_seconds: float` | Finite, nonnegative; default 0, passed as SDK read-consistency configuration |
| `batch_size: int` | Positive, default 128; controls ingestion batches, not transaction-wide atomicity |

Explicit collection creation requires an embedding identity, but not a loaded model. FTS-only reopening may omit provider configuration and identity: it reads the stored identity without attempting to construct that model. On reopen, unspecified dimension, projection and contextual settings come from the manifest; creation defaults must not override persisted settings. Explicit configuration supplied on reopen must match the stored schema, dimension, metric and identity. Contextual-embedding settings are part of the identity fingerprint. Reject mismatches without changing existing data.

Example configuration contract, not executed SDK validation:

```python
StoreConfig(
    vector_store="lancedb",
    table="agent_knowledge",
    dimension=768,
    metric_type="COSINE",
    index_type="FLAT",
    embedding_model={
        "model_type": "huggingface",
        "model_name": "sentence-transformers/all-mpnet-base-v2",
    },
    extra={"uri": "./data/agent-knowledge"},
)
```

The model example requires the existing Hugging Face extra and provisioned weights. A remote provider remains valid. The new installation extra is `ai-parrot-embeddings[lancedb]`; no dependency is installed by this specification.

### Data Models and Persistent Schema

Use an explicit Arrow schema, never first-row inference. Store a versioned collection manifest in persisted schema metadata, with schema version `1`, collection UUID, vector dimension, metric, embedding identity/fingerprint and metadata projection. Reopening an unsupported version raises an actionable error; it never overwrites or migrates the table.

| Row field | Type | Meaning |
|---|---|---|
| `record_id` | Non-null string | Logical identity within this collection |
| `document` | Non-null string | Original document/chunk text, not the augmented embedding input |
| `embedding` | Non-null fixed-size list of float32 | Exactly the configured dimension; reject non-finite or zero-norm vectors |
| `metadata_json` | Non-null string | Canonical JSON preserving supported nested JSON metadata |
| `meta_<field>` | Nullable typed scalar | Validated projection for filtering; absent and explicit null project to null |

Standard filterable fields are `source`, `source_type`, `parent_id`, `document_type` (strings) and `is_full_document`, `is_chunk` (booleans). Additional field names must match `[A-Za-z_][A-Za-z0-9_]{0,63}`. Preserve undeclared nested JSON metadata, but reject filtering on undeclared fields. Reject non-JSON values and non-finite numbers rather than stringifying them. User metadata may not use the reserved output key `_lancedb`.

IDs come from explicit `ids` aligned with documents, then a non-empty string `metadata["id"]`, then SHA-256 of original text plus canonical original metadata. Conflicting explicit/metadata IDs and duplicate IDs in one ingestion call raise `ValueError`. Calculate fallback IDs before contextual augmentation. Reingestion with the same ID upserts; updating content without supplying a stable ID creates a new identity. This is documented, not an automatic duplicate detector.

Expose result IDs as `lancedb:<collection_uuid>:<percent-encoded-record_id>`, with the original ID and collection name in `metadata["_lancedb"]`. This prevents unrelated collections' local IDs colliding in federation. Existing toolkit content-hash deduplication still applies across different IDs; do not change it.

New `LanceDBHybridHit` is a backend-owned Pydantic result with `id: str`, `content: str`, `metadata: dict[str, Any]`, `score: float`, `score_kind: Literal["rrf"]`, and `higher_is_better: Literal[True]`. It has no `distance` alias. It is not a new shared core hybrid interface.

### Lifecycle, Ingestion and Mutations

1. Construction validates configuration and retains provider settings lazily. Avoid the base constructor's eager provider setup by initializing base state without embedding arguments, then storing the normalized settings in the subclass. No broad base-class refactor.
2. `connection()` opens the directory through the async SDK and caches existing table handles. It returns `(connection, default_table_or_none)` and is idempotent. Async operations ensure the connection is open; the caller remains responsible for shutdown. Connecting alone never creates/replaces a collection. `get_vector()` returns an already-open default table, or raises `RuntimeError`; synchronous accessors do not perform async I/O.
3. `create_collection()` creates schema and native FTS when missing; on an existing compatible collection it is idempotent. A failed FTS setup leaves an explicit initialization error, not a successful searchable collection. A retry may finish index preparation without replacing rows. Do not overwrite an existing table.
4. `from_documents()` prepares the collection, adds documents and returns the store. `add_documents()` requires an existing prepared collection; missing collection raises `LookupError`. Empty document input is a no-op. Validate IDs/metadata for the full input before writes; generate and validate each vector batch before its upsert.
5. Use the existing contextual augmentation hook on copies of input documents. Persist original text and resulting contextual metadata without mutating caller objects. Use existing provider `embed_documents`/`embed_query`, not LanceDB embedding registration.
6. Upsert through the SDK merge-insert operation. Each successfully committed batch is durable; a later batch failure raises and identifies completed batch count without logging content. Do not claim all-batch rollback. Retry with stable IDs is idempotent.
7. Deletes use explicit IDs or compiled non-empty metadata predicates. Return the number actually removed, including 0 for no matches. Count and delete under the same mutation lock. Empty filters, missing selectors, or conflicting selectors raise `ValueError`; no implicit delete-all operation exists. Deletion includes matching parents, independent of search visibility.
8. `disconnect()` is idempotent and waits for this store's in-flight operations before releasing handles. Nested contexts close only at the outermost exit. Caller-injected and registry-returned embeddings are borrowed: override cleanup to release references without calling their `free()` method.

Mutations to a canonical directory/collection are serialized across store instances within one owning process/event loop by an async lock. That lock is **not** a cross-process lock, and the settled requirement is that independent processes write the same dataset concurrently — so in-process serialization is a local optimization, never the correctness mechanism. Cross-process correctness rests on the SDK's own commit semantics: the gate (I1/TASK-3057) must establish, for the pinned release, what happens on a concurrent-commit conflict between two processes doing merge-insert, delete and table/FTS-index creation, and whether the SDK retries, raises a distinguishable conflict error, or corrupts. Wrap conflict-raising commits in a bounded retry with jitter, surface an actionable error when the bound is exhausted, and — if the gate shows the SDK cannot make a needed operation safe — add a documented file-based inter-process lock over that operation specifically rather than declaring concurrency unsupported. Reopening after another process's write, and reading while another process rebuilds the FTS index, must both yield either the pre-write or post-write state, never a partial or erroring one. Readers reopen/refresh according to the configured SDK consistency interval. Cancellation must release locks and propagate; it cannot undo a write already committed by the SDK. If an SDK write is still running, retain mutation ownership until its outcome is known before allowing another mutation or shutdown.

Prefer native async SDK operations; move unavoidable blocking provider construction, Arrow conversion and synchronous SDK work off the event loop. Batch work to avoid unbounded event-loop stalls. No background pruning or destructive maintenance is scheduled. Updates/deletes must be visible to all three query modes without requiring users to run maintenance. Current index documentation describes combining indexed and unindexed data; verify this for the selected SDK in integration tests. [Official reindexing documentation](https://docs.lancedb.com/indexing/reindexing).

### Filters, Parent Visibility and Limits

One shared compiler constructs a single conjunctive prefilter for vector, FTS and both hybrid legs. Apply it before candidate limits. LanceDB documents prefiltering as the default and its application to both hybrid components; use an explicit single predicate to avoid query-builder overwrite surprises. [Official filtering documentation](https://docs.lancedb.com/search/filtering).

- Supported mapping values: exact typed scalar equality, a homogeneous scalar list for membership, or `None` for null/absent. Empty membership lists match nothing; lists containing null are rejected. Empty search filters mean unrestricted metadata, not unrestricted parent visibility.
- All keys combine with AND. No coercion of strings to numbers/booleans; booleans do not count as integers. Unknown fields/operators, raw SQL, mixed lists and nested filter objects raise `ValueError`.
- Compile only declared physical identifiers; escape string literals correctly and reject NUL/non-finite values. Test quotes, SQL-like payloads and malicious identifiers. Never interpolate unchecked identifiers or accept a caller-provided `where` expression.
- Unless `include_parents=True`, exclude any row whose `is_full_document` is true **or** whose `document_type` is `parent`/`parent_chunk`. Missing markers remain visible. An `is_chunk=True` marker cannot override an explicit parent marker. This follows the base class documentation, not PostgreSQL's stricter marker implementation.
- All modes accept positive integer `limit`; reject zero, negative, boolean or non-integer values. A blank query returns `[]` after parameter validation, without embedding generation. A prepared empty collection returns `[]`; a missing collection raises `LookupError`.

### Search and Score Contracts

| Mode | Backend result | Score/order | Provider requirement |
|---|---|---|---|
| Vector | `list[SearchResult]` | Raw cosine distance, lower is better; `distance` remains the existing alias | Query embedding required |
| FTS | `list[SearchResult]` | Native BM25, higher is better; retain SDK order | No provider construction or invocation |
| Hybrid | `list[LanceDBHybridHit]` | Native RRF relevance, higher is better; retain SDK order | Explicit query vector plus original query text |

Every result adds `_lancedb` metadata containing collection, raw record ID, search mode, score kind and direction. FTS returns `SearchResult` only for existing adapter compatibility: its legacy `distance` alias is numerically BM25, **not** a distance. Document this limitation prominently; do not change shared models. Hybrid uses its distinct type and converts directly to `OriginHit`.

For cosine vector search, `similarity_threshold=0.0` disables thresholding for base compatibility; nonzero values must be in `(0, 1]` and mean minimum cosine similarity. Existing tool `score_threshold`, when supplied, also means minimum cosine similarity in `[0, 1]`, matching that tool's documented input rather than treating it as raw distance. Apply `distance <= 1 - threshold`; if both thresholds are supplied, use the stricter enabled threshold. Result scores remain distances. FTS/hybrid do not accept these vector-only thresholds. `search_strategy="auto"` uses exact search; reject unsupported strategies explicitly.

### New Public Interfaces

These signatures describe **proposed** symbols, not currently importable implementations. Existing abstract signatures in section 6 remain authoritative for inherited operations.

| Interface | Contract |
|---|---|
| `LanceDBStore(embedding_model=None, embedding=None, **kwargs)` | Compatible constructor with the validated configuration above |
| `async fulltext_search(self, query: str, collection: str \| None = None, limit: int = 10, metadata_filters: dict[str, Any] \| None = None, include_parents: bool = False, **kwargs) -> list[SearchResult]` | Native lexical search; accepts the same collection aliases as vector search |
| `async hybrid_search(self, query: str, collection: str \| None = None, limit: int = 10, metadata_filters: dict[str, Any] \| None = None, include_parents: bool = False, **kwargs) -> list[LanceDBHybridHit]` | Native vector/FTS fusion; no silent fallback on a failed leg |
| `async mmr_search(self, **kwargs) -> list[SearchResult]` | Explicitly raises `NotImplementedError` explaining that v1 supports exact similarity search, so the existing tool's opt-in MMR path fails clearly |
| `LanceDBOrigin(store, *, name="lancedb", description="", mode: Literal["vector", "hybrid"]="hybrid", collection: str \| None=None, metadata_filters: dict[str, Any] \| None=None, include_parents: bool=False, timeout: float \| None=None)` | Borrows store; holds fixed collection/filter scope; `kind=SearchOriginKind.VECTOR`, `supports_fts=True` |
| `async LanceDBOrigin.search(self, query: str, k: int) -> list[OriginHit]` | Calls store `hybrid_search` or `similarity_search` with `limit=k` and configured scope |
| `async LanceDBOrigin.fts_search(self, query: str, k: int) -> list[OriginHit]` | Always calls store `fulltext_search`, regardless of normal mode |

Normalize with unchanged native score/order, 1-based `native_rank`, namespaced ID and all metadata. Propagate errors/cancellation to the toolkit; do not return empty success on backend failure. The caller owns connection lifetime; an origin never closes a borrowed store. Graph failure does not disable standalone LanceDB. Hybrid failure fails that origin while the toolkit retains successful graph/other origin sections.

Compatibility adapters must explicitly accept `table`/`collection` aliases and `schema=None`/`"public"` as a no-op namespace; other schemas are unsupported. Accept legacy column labels `document`, `embedding`, `cmetadata`, `id` and map them to this fixed schema. Reject custom column labels and non-empty `additional_columns`, rather than silently dropping them. Accept a null `dsn` from existing factories; reject a non-null DSN in favor of explicit `uri`. Reject unknown operational kwargs. Provider/contextual configuration and the named backend settings are recognized constructor options, not ignored extras.

`prepare_embedding_table()` maps default legacy arguments to `create_collection()`. It accepts `conn=None` or this store's connection, matching dimension, default column labels and default `use_jsonb=True` as a compatibility-only flag; no JSONB database is created. Reject `drop_columns=True`, foreign connections and schema-changing options. `create_all_indexes` never requests ANN; native FTS preparation is mandatory even when it is false. `delete_documents()` accepts a non-empty homogeneous list of documents or raw logical IDs via its `documents` selector, or `pk` plus `values`; documents use the ingestion identity algorithm. `pk="id"` targets raw logical IDs and other keys must be declared metadata fields. `delete_documents_by_filter()` uses the same compiler without the search-only parent predicate. Conflicting table/collection selectors always raise.

---

## 3. Module Breakdown

All paths marked **new** are implementation proposals; existing contracts are verified in section 6. Do not add a satellite `parrot/stores/__init__.py`.

| Module | Owned files / responsibility | Dependencies |
|---|---|---|
| M1: schema/config/filter contract | **New** `packages/ai-parrot-embeddings/src/parrot/stores/lancedb_models.py`, `lancedb_filters.py`; validated settings, manifest, hybrid record, identity and safe predicates; associated new `tests/test_lancedb_filters.py` | Existing core models; SDK/Arrow compatibility gate |
| M2: store lifecycle and writes | **New** `packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py`; subclass, lazy providers, context ownership, schema/FTS setup, upserts/deletes and compatibility adapters; new `tests/test_lancedb_store.py` lifecycle cases | M1 |
| M3: retrieval | Same backend file and store tests, sequenced after M2; exact vector, FTS, native hybrid, filters/thresholds and score conversion | M1, M2 |
| M4: federation adapter | **New** `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/lancedb.py`; update existing origins `__init__.py`; new `tests/multistoresearch/test_lancedb_origin.py` | M1 result contract; existing `SearchOrigin`; real SDK integration waits for M3 |
| M5: packaging and release integration | Existing embeddings `pyproject.toml`, root `uv.lock`, core stores `__init__.py`, existing namespace/backend tests — specifically **two** files that each assert **exact dict equality** on `supported_stores` and therefore cannot pass unmodified: `packages/ai-parrot-embeddings/tests/test_store_backends_present.py` (`test_supported_stores_unchanged` at :27, plus the `STORE_BACKENDS` list at :7 driving a parametrized resolution test) and `packages/ai-parrot-embeddings/tests/test_namespace_imports.py` (`test_supported_stores_unchanged` at :126). Extend only the intentional `lancedb` key in both; preserve the pre-existing `faiss_store`/`arango` mismatches those files mark "do NOT fix"; **new** `packages/ai-parrot-tools/tests/multistoresearch/test_lancedb_integration.py` and `docs/lancedb-vector-store.md` | SDK gate first; final regression/docs depend on M2–M4 |

The first implementation activity is an isolated SDK compatibility test and dependency resolution, not an unverified production API implementation. The manifest/lock changes remain part of M5 ownership even if required early. No new source files or packages are introduced by this draft.

---

## 4. Test Specification

### Unit Tests

| Test group | Module | Required assertions |
|---|---|---|
| U1 configuration/schema | M1 | Local path validation; explicit FLAT factory config; metric/dimension checks; immutable projections; JSON validation; collection identity mismatch |
| U2 filters | M1 | Typed equality/IN/null; empty lists; absent markers; contradictory parent markers; quoted values; hostile keys/payloads; invalid operators rejected before SDK calls |
| U3 lifecycle/provider ownership | M2 | Lazy constructor and FTS; concurrent first-use initializes provider once; nested context; repeated connect/disconnect; borrowed provider never freed; event-loop heartbeat |
| U4 ingestion/deletion | M2 | Stable/generated IDs; duplicate/conflicting selectors; contextual copies; dimension/non-finite/zero-vector rejection; upsert; safe delete counts; partial batch error and idempotent retry |
| U5 query contracts | M3 | Empty/blank cases; aliases; validation errors; raw distance; cosine thresholds including tool alias; FTS metadata; hybrid result has no distance; unsupported MMR |
| U6 adapter | M4 | Vector/hybrid dispatch; fixed filters/collection; FTS routing; rank/provenance; no tools-to-SDK import requirement; borrowed-store ownership; errors and cancellation propagate |
| U7 packaging/factory | M5 | SDK absent and present in isolated processes; the six pre-existing map entries unchanged and `lancedb` added (update the exact-equality assertions in **both** `test_store_backends_present.py:27` and `test_namespace_imports.py:126`; do not weaken either to a subset check); new backend resolves from satellite and is added to that file's `STORE_BACKENDS`; selecting LanceDB without the extra names `ai-parrot-embeddings[lancedb]`; default tool column aliases; no satellite namespace initializer |

### Integration Tests

Run these against the selected real SDK, not only mocks. Optional SDK absence may skip the general suite, but the dedicated feature job installs the extra and must execute all integration tests without skips.

| Test | Required proof |
|---|---|
| I1 SDK gate | Python/Arrow resolution, async local connection, persistent manifest, native FTS creation, vector/text hybrid, conjunctive filters and merge-insert work on the pinned release |
| I2 persistence | Create/ingest, close, open in a fresh subprocess, retrieve identical IDs/metadata; incompatible reopen leaves original data readable |
| I3 retrieval/filter matrix | Vector, lexical and hybrid on the same corpus; a lexical-only identifier and semantic-only neighbor are both eligible for hybrid; excluded parents/metadata never consume the requested candidate budget |
| I4 mutation visibility | Upsert and delete reflected in all modes before/after reopen, including rows added after FTS index creation; delete count correct under serialized mutations |
| I5 model-free lexical path | Reopen with no provider and with a configured provider factory that would raise; FTS succeeds without construction/inference; vector/hybrid fail explicitly without a working provider |
| I6 federation | Real LanceDB hybrid origin plus existing `GraphIndexOrigin` in the real toolkit; grouped native order and origin score metadata preserved, merged cap/dedup unchanged; one failed/timed-out origin does not erase the other |
| I7 async and cancellation | Multiple async reads, serialized mutations across two store instances, cancellation during an in-flight write, clean reopen; no prematurely released mutation lock |
| I9 concurrent writer processes | Two or more independent OS processes ingest/upsert/delete into one local directory concurrently (disjoint IDs, then deliberately colliding IDs); every acknowledged write is present after a fresh reopen, no row is lost or duplicated, conflicts surface as the documented distinguishable error or succeed under bounded retry, and a reader running throughout never observes a partial or erroring table — including while another process creates or rebuilds the FTS index |
| I8 no network at all | Disable socket connections around the whole exercised path — not only storage — with a locally provisioned embedding model: ingest, vector, FTS and hybrid retrieval all complete with sockets denied. Proves the fully offline profile, not merely embedded storage. No PostgreSQL process, container, storage account or remote endpoint required, and no provider that would dial out |

### Test Data / Fixtures

- Use pytest `tmp_path`, pytest-asyncio and a deterministic async embedding fixture with dimension 8, named identity `lancedb-test-embedding-v1`, known nonzero vectors and call counters. No downloaded weights or external services.
- Use 24 fixed documents: child chunks across two sources, a lexical identifier `ZXQ731`, a semantic-only neighbor with non-overlapping query text, explicit parents, contradictory parent/chunk markers, legacy unmarked rows, null/absent fields and quoted filter values. Use two collections with overlapping logical IDs and different content to test identity isolation.
- For adapter tests, reuse the verified fake graph retriever/reader pattern. For I6, include a real graph retriever over a tiny local graph with deterministic seed results; optional SQLite FTS uses a local fixture. Verify graph fixture constructors before implementing them; this spec does not invent a graph-builder API.
- Record a non-gating 1,000-row deterministic ingestion/search baseline (SDK/Python/Arrow versions, dimension, corpus size, warmup, elapsed samples). No product p95 or recall SLO was supplied.
- A separate blocking-work unit fixture holds provider construction/Arrow conversion for 200 ms; a 10 ms heartbeat must advance at least five times before completion. This verifies offloading, not production latency.
- Store all test/compatibility/benchmark output under `artifacts/logs/lancedb-vector-store-*.log`. Run the new store/filter suites, existing embeddings namespace/backend suites and the entire existing multi-store test directory.

---

## 5. Acceptance Criteria

Completion requires every item below, after draft scope approval. None is claimed complete by this documentation change.

- [ ] AC1: Optional extra resolves against current workspace Python/Arrow constraints; SDK gate I1 passes; unrelated core/tools imports work without the SDK (U7).
- [ ] AC2: `supported_stores["lancedb"]` resolves the satellite class; direct and existing tool/origin configurations work with documented FLAT/column aliases; no other mapping changes (U5, U7).
- [ ] AC3: Collections persist across process restart; manifest/schema/model mismatches fail non-destructively and local IDs cannot collide across different collection UUIDs (U1, I2).
- [ ] AC4: IDs, metadata and original text survive ingestion; upserts/deletes have defined counts, visibility and retry behavior; caller documents and borrowed models remain intact (U3, U4, I4).
- [ ] AC5: Vector, FTS and native hybrid retrieval pass the same prefilter/parent-visibility matrix; unsupported inputs fail explicitly; thresholds preserve raw vector score semantics (U2, U5, I3).
- [ ] AC6: FTS neither constructs nor invokes embedding models; and with a locally provisioned model the complete ingest/vector/FTS/hybrid path runs with sockets denied — no network service, database container or remote provider (I5, I8).
- [ ] AC7: Hybrid-origin and graph federation preserve native score/rank provenance and current merged ranking/dedup semantics; isolated failures/timeouts retain successful origins (U6, I6).
- [ ] AC8: Async heartbeat, concurrent reads, same-process mutation serialization, cancellation and nested-context cleanup pass; and independent OS processes write one directory concurrently without loss, duplication or partial reads, with conflicts either retried within the bound or raised as the documented error (U3, I7, I9).
- [ ] AC9: Existing backend/namespace and complete multi-store regression suites pass; dedicated real-SDK feature tests execute without skips; logs identify versions and commands.
- [ ] AC10: Documentation covers install/configuration, local-model provisioning versus storage locality, FTS's legacy score alias, write ownership, failures, unsupported modes, safe reopen/deletion and hybrid-plus-graph composition; the baseline benchmark is recorded without claiming an SLO.

---

## 6. Codebase Contract

These references were read on synchronized `dev` during specification. Source inspection verifies definitions and existing import usage; runtime import compatibility and the new SDK remain implementation tests. Implementation agents must read any additional symbol before relying on it, and recheck paths if package layout changes.

### Verified Imports

```python
from parrot.stores import AbstractStore
# Existing usage: packages/ai-parrot-embeddings/tests/test_namespace_imports.py:151
from parrot.models import OriginHit, SearchOriginKind
# packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:10
from parrot.models.stores import SearchResult
# packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:11
from .base import SearchOrigin
# packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:13
from parrot_tools.multistoresearch.origins import GraphIndexOrigin
# packages/ai-parrot-tools/tests/multistoresearch/test_graphindex_origin.py:5
```

### Existing Class Signatures and Data Contracts

| Verified location | Existing signature / behavior |
|---|---|
| `packages/ai-parrot/src/parrot/stores/abstract.py:117` | `AbstractStore.__init__(self, embedding_model: Union[dict, str] = None, embedding: Union[dict, Callable] = None, **kwargs)`; eager provider creation at 155 |
| `packages/ai-parrot/src/parrot/stores/abstract.py:202` | `async connection(self) -> tuple`; sync `get_connection(self) -> Any` at 205; `engine(self)` at 208; async `disconnect(self) -> None` at 212 |
| `packages/ai-parrot/src/parrot/stores/abstract.py:216` | Nested async context entry; `_free_resources` at 222 calls provider `free()`; outermost exit disconnects at 227 |
| `packages/ai-parrot/src/parrot/stores/abstract.py:238` | `get_vector(self, metric_type: str = None, **kwargs)`; `get_vectorstore(self)` delegates at 241 |
| `packages/ai-parrot/src/parrot/stores/abstract.py:245` | `async similarity_search(self, query: str, collection: Union[str, None] = None, limit: int = 2, similarity_threshold: float = 0.0, search_strategy: str = "auto", metadata_filters: Union[dict, None] = None, include_parents: bool = False, **kwargs) -> list` |
| `packages/ai-parrot/src/parrot/stores/abstract.py:276` | `async from_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs) -> Callable` |
| `packages/ai-parrot/src/parrot/stores/abstract.py:295` | `async create_collection(self, collection: str) -> None`; `async add_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs) -> None` at 308 |
| `packages/ai-parrot/src/parrot/stores/abstract.py:383` | `async generate_embedding(self, documents: List[Any]) -> List[Any]`; contextual augmentation at 391 modifies metadata, requiring caller-safe copies |
| `packages/ai-parrot/src/parrot/stores/abstract.py:455` | `async prepare_embedding_table(self, tablename: str, conn: Any = None, embedding_column: str = 'embedding', document_column: str = 'document', metadata_column: str = 'cmetadata', dimension: int = None, id_column: str = 'id', use_jsonb: bool = True, drop_columns: bool = False, create_all_indexes: bool = True, **kwargs)` |
| `packages/ai-parrot/src/parrot/stores/abstract.py:494` | `async delete_documents(self, documents: Optional[Any] = None, pk: str = 'source_type', values: Optional[Union[str, List[str]]] = None, table: Optional[str] = None, schema: Optional[str] = None, collection: Optional[str] = None, **kwargs) -> int` |
| `packages/ai-parrot/src/parrot/stores/abstract.py:520` | `async delete_documents_by_filter(self, search_filter: Dict[str, Union[str, List[str]]], table: Optional[str] = None, schema: Optional[str] = None, collection: Optional[str] = None, **kwargs) -> int` |
| `packages/ai-parrot/src/parrot/embeddings/base.py:169` | `async embed_documents(self, texts: List[str], batch_size: Optional[int] = None) -> List[List[float]]`; `async embed_query(self, text: str, as_nparray: bool = False) -> Union[List[float], List[np.ndarray]]` at 188 |
| `packages/ai-parrot/src/parrot/stores/models.py:19` | `Document` has `page_content: str` and `metadata: Dict[str, Any]` |
| `packages/ai-parrot/src/parrot/models/stores.py:46` | `SearchResult` requires string id/content, float score; metadata defaults empty; computed `distance` at 74 returns score unchanged |
| `packages/ai-parrot/src/parrot/models/stores.py:79` | `OriginHit` has optional id/native score, content, metadata, origin, origin_kind and 1-based native_rank |
| `packages/ai-parrot/src/parrot/models/stores.py:162` | `StoreConfig` includes string `vector_store`, table/schema, embedding_model, dimension, dsn, metric/index settings and `extra`; index default is `IVF_FLAT` |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:42` | `async search(self, query: str, k: int) -> List[OriginHit]`; optional `async fts_search(self, query: str, k: int) -> List[OriginHit]` at 54 |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/graphindex.py:43` | Constructor takes required retriever and optional reader; reader controls `supports_fts` at 67 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py:186` | `GraphExpandedRetriever` requires graph/nodes and at least one of embedder or hybrid_search; it is not initialized by a LanceDB path |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py:320` | `async search_symbols(self, query: str, *, limit: int = 20) -> list[dict]`; native SQLite FTS5 score is negative, ascending best |

### Verified Call Mappings

| New component | Existing connection | Verified at |
|---|---|---|
| Store registration | Add only one key/class to `supported_stores`; factory imports `parrot.stores.{name}` | `packages/ai-parrot/src/parrot/stores/__init__.py:6`; `packages/ai-parrot/src/parrot/interfaces/vector.py:42` |
| Configured store | Tool passes embedding/dimension/metric/index and overlays `extra` | `packages/ai-parrot/src/parrot/tools/vectorstoresearch.py:131` |
| Vector tool search | `await store.similarity_search(**search_kwargs)`; forwards table/schema/column names, optional score_threshold/metadata_filters; MMR is a separate opt-in call | `packages/ai-parrot/src/parrot/tools/vectorstoresearch.py:184` |
| Lazy embeddings | Reuse `create_embedding` registry lookup only on demand; avoid implicit default-provider generation in FTS | `packages/ai-parrot/src/parrot/stores/abstract.py:326` |
| Existing vector origin | `await self._store.similarity_search(query, limit=k)` and `await self._store.fulltext_search(query, limit=k)` | `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:50`; FTS at 66 |
| Toolkit dispatch | Chooses origin.search or origin.fts_search per call; gathers exceptions and applies origin timeouts | `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:268` |
| Toolkit response | BM25 rerank before dedup; dedup checks raw ID then content hash; final cap retained | `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:246`; ranking at 359; dedup at 390 |
| Graph adapter | `retriever.search(query, seed_top_k=k)`; optional `reader.search_symbols(query, limit=k)` | `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/graphindex.py:69`; FTS at 109 |
| Namespace regression | Two exact store-map assertions require the intentional new entry; satellite must not own namespace initializer | `packages/ai-parrot-embeddings/tests/test_store_backends_present.py:27`; `packages/ai-parrot-embeddings/tests/test_namespace_imports.py:126` |

### Does NOT Exist (Anti-Hallucination)

- `LanceDBStore`, `LanceDBOrigin`, `LanceDBConfig`, `LanceDBHybridHit`, and the proposed backend/origin files do not exist yet.
- No declared `lancedb` dependency exists in the inspected package manifests; it is a proposed optional extra, not safe to assume installed.
- No generic `HybridSearchResult`, `HybridStoreOrigin`, or hybrid mode on the existing `VectorStoreOrigin` can be reused by name.
- `StoreType` currently lists PGVECTOR, FAISS and ARANGO only; this feature does not promise adaptive-router support by adding a dispatch key.
- GraphIndex's SQLite reader is lexical retrieval, not a replacement semantic seed provider.
- No universal cross-origin score or toolkit preservation of native hybrid order in the merged list exists. Only grouped origin sections preserve that order.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first, strict Python type hints, Pydantic structured models and black/isort formatting; focused changes only.
- Keep SDK imports lazy so importing the backend class and origins remains safe without the SDK; selecting/opening LanceDB reports the exact install extra when missing.
- Preserve the embeddings satellite namespace layout. Do not relocate existing stores or fix unrelated dispatch-name mismatches.
- Use the existing provider registry and contextual augmentation; never free registry-shared models from this store.
- Avoid logging document text, vectors, credentials or filter values. Errors should identify operation, collection and actionable cause.

### Known Risks / Gotchas

| Risk | Required mitigation |
|---|---|
| Async/native FTS API drift | Verify selected release before implementation; use async `create_index` with native FTS configuration, not the synchronous `create_fts_index` or removed legacy Tantivy options |
| Eager base embedding construction | Subclass-local lazy initialization and a test whose provider factory raises if touched by FTS |
| Parent-filter divergence across stores | Follow the explicit abstract documentation and test missing/contradictory markers; do not copy PostgreSQL filtering blindly |
| Fixed schema versus flexible metadata | Preserve JSON separately, filter only declared typed projections, reject incompatible reopen without migration |
| FTS index freshness after writes | Real post-index ingestion/upsert/delete tests; do not equate index maintenance with correctness or silently omit unindexed rows |
| Cancellation after a native write starts | Track in-flight mutation outcome and lock ownership; no promise of rollback on timeout |
| RRF followed by toolkit BM25 | Preserve native grouped results and explain separate merged ranking; no cross-origin comparison of raw scores |
| Default `StoreConfig.index_type` is not FLAT | Explicit config example and actionable rejection; do not globally alter other backends' defaults |
| Cross-process commit conflicts | Establish the pinned SDK's concurrent-commit behavior in the I1 gate before implementing writes; bounded retry with jitter plus a distinguishable conflict error, or a documented file lock over the specific unsafe operation. An asyncio lock is not a cross-process lock and must never be presented as one |
| "Offline" claimed from storage locality alone | A local directory makes *storage* offline; the agent is offline only if the embedding provider is local and provisioned. Gate the claim on I8 with sockets denied across the whole path, and document the provisioning step separately from the storage story |
| Version/platform compatibility | Resolve the optional dependency and test workspace-supported Python/Arrow combinations; no claim of universal wheel availability |

### External Dependencies and API Evidence

| Package | Version position | Purpose / evidence |
|---|---|---|
| `lancedb` | Candidate exact pin `==0.38.0`; compatibility gate required before committing the implementation lockfile | New optional `lancedb` extra in embeddings and inclusion in its existing `all` extra. This release is published; resolution and runtime behavior were not tested during specification. [PyPI release](https://pypi.org/project/lancedb/0.38.0/) |
| `pyarrow` | Retain existing core `>=25.0` constraint | Explicit schema/conversion; declaration verified at `packages/ai-parrot/pyproject.toml:157`; do not downgrade it merely to force SDK resolution |
| Existing local/remote embedding extras | Existing versions | Keep provider choice; embeddings manifest declares provider extras and backend extras at `packages/ai-parrot-embeddings/pyproject.toml:34` and 62 |
| Existing graph and ranking dependencies | Existing versions | No new graph or reranking service; core declares rustworkx/aiosqlite at 169/172 and embeddings declares rank_bm25 at 44 |

The official Python API documents `connect_async`, read-consistency configuration, async query builders and merge-insert operations. Treat these as release-sensitive SDK APIs, not repository-provided wrappers. The initial gate must prove persistent schema metadata and exact result columns as well as method availability. [Official Python API](https://lancedb.github.io/lancedb/python/python/). Native FTS preparation uses the current index configuration surface. [Official FTS index documentation](https://docs.lancedb.com/indexing/fts-index).

If the candidate fails resolution or required behavior, stop that implementation gate with the exact conflict and propose a revised pin/spec; do not silently switch to cloud storage, an older FTS engine, a mock-only test, or a global dependency downgrade.

---

## 8. Open Questions

The five original brainstorm questions are preserved verbatim and are all answered. Their answers are binding on sections 1–5; where older draft text assumed otherwise it has been corrected (see the Revision History). Q6 is new — raised by the design-research cross-check in section 9 and not yet decided.

- [x] Include vector, FTS and native hybrid with optional graph federation in v1, or ship only vector and standalone FTS first? — *Owner: Jesus Lara*: Yes
- [x] Does local-only require embedded storage with existing model providers, or a fully offline agent after provisioning? — *Owner: Jesus Lara*: fully offline agent
- [x] Can one process own writes initially, or must independent processes write the same dataset concurrently? — *Owner: Jesus Lara*: write concurrently
- [x] Is federation with existing GraphIndex sufficient, or must LanceDB also replace its internal seed index? — *Owner: Jesus Lara*: only federation
- [x] Should a failing hybrid leg fail that origin while other origins continue, or return explicitly marked partial results? — *Owner: Jesus Lara*: fail
- [ ] Q6: Must `LanceDBHybridHit` carry the per-leg vector and lexical component scores/ranks alongside the fused RRF relevance, or is the single fusion score plus `score_kind`/`higher_is_better` sufficient for v1? — *Owner: Jesus Lara* — *Raised by design research S2 (§9)*. Carrying components would let a caller explain why a hybrid hit ranked where it did and would let the toolkit rerank on a component rather than the fused score; it also widens a result contract that M1 freezes for every downstream module. Feasibility is unproven: whether the pinned SDK exposes pre-fusion `_distance`/`_score` columns on a hybrid query is exactly the kind of release-sensitive behavior the I1 gate exists to establish. **If undecided when TASK-3057 runs, that gate should record whether the columns are available, and v1 ships the single fused score.**

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-542/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).
>
> Deviation from the `/sdd-spec` §3b precondition, recorded for audit: neither exploration
> document is literally marked `accepted` (brainstorm `Status: exploration`, proposal
> `status: discussion`). The pass was run anyway, at the user's explicit request, because the
> design intent *was* accepted downstream — this spec is `Status: approved` and already
> decomposed into 14 tasks. The brief carried the brainstorm's Problem Statement, Constraints,
> Recommendation and Option A body, the paths (only) from its Code Context, and the user's five
> §8 answers as constraints. No text from this spec was shown to the reviewer.
>
> All 12 suggestions passed path containment and `test -e` verification — the reviewer cited
> only files that exist.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define an explicit LanceDB capability contract (architecture) | REJECT | Already specified: §2 New Public Interfaces gives `fulltext_search`/`hybrid_search` full signatures and `LanceDBOrigin(mode=...)` selects the retrieval mode. No kwargs-driven or generic-hybrid path was ever proposed. | — |
| S2 | Preserve hybrid component scores and conventions (api) | ESCALATE | Direction and kind are already carried (`LanceDBHybridHit.score_kind`/`higher_is_better`, `_lancedb` metadata, and §7's "no cross-origin comparison of raw scores"). Per-leg component scores are genuinely absent, would widen a contract M1 freezes, and depend on unverified SDK column exposure. | §8 Q6 |
| S3 | One filter and parent-visibility policy for every Lance mode (api) | REJECT | Already specified: §2 Filters mandates one shared compiler producing a single conjunctive prefilter applied to vector, FTS and **both** hybrid legs before candidate limits, and §7 explicitly warns against copying PostgreSQL's stricter marker handling — the divergence the reviewer found in `arango.py`. U2/I3 cover the named cases. | — |
| S4 | Prove the SDK async boundary before selecting the implementation (risk) | REJECT | Already specified: §2 Lifecycle requires native async operations with unavoidable blocking work moved off the loop, §2 items 2/8 define connection ownership and shutdown, and I1/TASK-3057 is a hard gate before dependent implementation. U3's event-loop heartbeat is the falsifying test. | — |
| S5 | Design and test true cross-process write behavior (risk) | CONFIRM | The spec directly contradicted the settled requirement — §2 read "Independent writer processes … are unsupported" while §8 requires concurrent independent writers. Correctness now rests on the SDK's commit semantics (established by the I1 gate) with bounded retry, a distinguishable conflict error, or a scoped file lock; the asyncio lock is demoted to a local optimization. | §1 Non-Goals, §1 Baseline, §2 Lifecycle, §4 I9, §5 AC8, §7 |
| S6 | Make collection, FTS-index and freshness lifecycle explicit (architecture) | CONFIRM | Mostly covered already (§2 item 3 for FTS creation and its failure mode, `read_consistency_interval_seconds` for freshness, §7 for post-index write freshness). The one uncovered case — reads while *another process* rebuilds the index — was real and is now required to yield pre- or post-write state, never a partial one. | §2 Lifecycle, §4 I9 |
| S7 | Define stable IDs independently of generated row keys (api) | REJECT | Already specified in full: §2 Data Models fixes ID precedence (explicit `ids` → `metadata["id"]` → SHA-256 of original text plus canonical metadata), upsert-on-same-ID, conflict/duplicate errors, and namespaced `lancedb:<collection_uuid>:<id>` output preventing cross-collection collisions. The concurrent-writer half of the concern is handled by S5. | — |
| S8 | Complete optional-backend registration without eager imports (architecture) | CONFIRM | Lazy imports and the extra were already specified, but the reviewer surfaced a concrete breakage the spec had softened into "existing map entries unchanged": `test_store_backends_present.py::test_supported_stores_unchanged` asserts **exact dict equality** on `supported_stores`, and `STORE_BACKENDS` drives a parametrized test. Both must be edited; neither passes unmodified. | §3 M5, §4 U7 |
| S9 | Enforce whole-origin failure for hybrid errors (risk) | REJECT | Already specified: §2 requires "no silent fallback on a failed leg", propagation of errors and cancellation to the toolkit, and hybrid failure failing that origin while the toolkit retains successful graph/other sections. I6 tests exactly that. | — |
| S10 | Keep LanceDB federation outside GraphExpandedRetriever (architecture) | REJECT | Already a stated Non-Goal ("Replacing GraphIndex's internal semantic seed index") with `GraphIndexOrigin` reused unmodified and I6 exercising the two as sibling origins. A negative test asserting non-substitution would guard a code path this feature never writes. | — |
| S11 | Separate embedded storage from the fully-offline guarantee (risk) | CONFIRM | The sharpest finding. The spec's Non-Goals excluded "certifying an entirely offline agent" while §8 requires exactly that, and I8/AC6 proved only that *storage* needs no network. A local directory does not make an agent offline — the embedding provider must be local and provisioned. I8 now denies sockets across the whole ingest/vector/FTS/hybrid path. | §1 Non-Goals, §2 Baseline, §4 I8, §5 AC6, §7 |
| S12 | Build an acceptance matrix before performance claims (testing) | CONFIRM | §4/§5 already covered restart, stable IDs, parent exclusion, filters, score provenance, index freshness and hybrid-leg failure, and §4 already forbids an SLO claim on the 1,000-row baseline. Two items on the reviewer's list were genuinely missing — multiprocess writes and whole-agent offline execution — and are added as I9 and the widened I8. | §4 I8/I9, §5 AC6/AC8 |

Summary: **4** confirmed · **7** rejected · **1** escalated.

---

## Worktree Strategy

**Isolation: per-spec.** One implementation feature worktree based on `dev`; do not implement on this authoring checkout. M1 freezes the schema/filter/hybrid payload contract before dependent work. M2 and M3 share the backend file and must be sequenced. M4 can be developed against the frozen contract; real federation integration waits for M3. One owner handles packaging, dispatch, exports and final integration to avoid shared-file conflicts.

No implementation worktree or task artifacts are created by this spec. After approval, run `$sdd-task sdd/specs/lancedb-vector-store.spec.md` to reserve task IDs and establish the feature worktree. Do not use FEAT-563 for this feature's task state.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-10 | Codex | Initial FEAT-542 draft from Option A; verified current contracts, defined storage/search behavior and preserved all five unanswered scope questions |
| 0.2 | 2026-09-10 | Claude Opus 5 | FEAT-545 design-research cross-check (§9, `gpt-5.6-luna`, 12 suggestions, all paths verified). Folded 4 CONFIRMs: cross-process concurrent writes are now in scope and rest on SDK commit semantics rather than an asyncio lock (§1/§2/§4 I9/§5 AC8/§7); "fully offline" now means the whole agent path with sockets denied, not just storage (§1/§2/§4 I8/§5 AC6/§7); the exact-equality `supported_stores` test is named as one that must be edited (§3 M5/§4 U7); cross-process FTS-index rebuild reads defined (§2). Escalated one question to §8 Q6 (per-leg hybrid component scores). Also corrected the stale §1 Draft Decision Baseline and §8 preamble, which still claimed the five scope questions were unanswered. |
| 0.3 | 2026-09-10 | Claude Opus 5 | Decomposition re-check against the 14 existing FEAT-542 tasks: no new tasks needed — TASK-3061/3067/3068/3069 already implement the v0.2 scope. Corrected §3 M5 / §4 U7, which named only one exact-equality `supported_stores` assertion; TASK-3067 had already found a second in `test_namespace_imports.py:126`. Propagated §8 Q6 into TASK-3059/3065 and marked TASK-3057's reconciliation half as done-by-v0.2. |
