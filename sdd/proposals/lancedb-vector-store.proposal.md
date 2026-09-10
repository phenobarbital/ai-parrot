---
id: FEAT-563
title: Embedded LanceDB vector and full-text retrieval for local agents
slug: lancedb-vector-store
type: feature
mode: enrichment
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-10
  summary_oneline: Optional LanceDB vector/FTS storage with local graph federation.
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-563/
created: 2026-09-10
updated: 2026-09-10
---

# FEAT-563 — Embedded LanceDB vector and full-text retrieval for local agents

> Mode: enrichment · Confidence: medium · Source: inline
>
> Audit: [FEAT-563 research state](../state/FEAT-563/)
>
> FEAT-563 is a provisional proposal identity; formal feature allocation occurs at specification time.

## 0. Origin

> $dd-proposal lancedb-vector-store -- for a vector-store search or combined with graph and FTS (multi-store search) for local (autonomous) operations, adopting LanceDB instead postgres+pgvector is useful for local-only agents without deploying an docker for postgres

The exact input is preserved in [source.md](../state/FEAT-563/source.md). The installed workflow is `sdd-proposal`; `dd-proposal` was interpreted as that invocation.

Initial signals: add a local vector backend; support graph/FTS combinations; reduce deployment overhead for autonomous agents. No explicit performance targets, writer-concurrency requirement, migration requirement, or acceptance criteria were supplied.

## 1. Synthesis Summary

Add an optional LanceDB backend for local vector and full-text retrieval, implemented against `AbstractStore` in the embeddings satellite and registered through `supported_stores` (F001–F002). Reuse `VectorStoreOrigin` for semantic and lexical federation, and `GraphIndexOrigin` for a separately configured local graph (F003–F004). An explicit hybrid origin is recommended when one multi-store call must include LanceDB vector-plus-FTS candidates: `MultiStoreSearchToolkit` currently selects semantic or FTS methods per call and reranks merged candidates with BM25 (F005). Official LanceDB documentation supports embedded local persistence, async Python operations, native BM25, and vector/FTS hybrid search (F008). This is an opt-in local deployment choice; existing PostgreSQL deployments need no migration. Confidence is medium until scope choices and a real local integration fixture establish the complete behavior.

## 2. Codebase Findings

### 2.1 Localization

All existing locations below have persisted evidence. Proposed new files are identified separately in §3.

| Path | Symbol / role | Lines | Evidence |
|---|---|---|---|
| `packages/ai-parrot/src/parrot/stores/__init__.py` | supported_stores — Core dispatch | 1-13 | F001 |
| `packages/ai-parrot-embeddings/pyproject.toml` | project.optional-dependencies — Optional backend packaging | 28-30,62-99 | F001 |
| `packages/ai-parrot/src/parrot/interfaces/vector.py` | VectorInterface._get_database_store — Agent configuration | 42-65 | F001 |
| `packages/ai-parrot/src/parrot/stores/abstract.py` | AbstractStore — Abstract store contract | 117-174,201-325,383-454,454-542 | F002 |
| `packages/ai-parrot/src/parrot/stores/models.py` | Document / DistanceStrategy — Document and metrics | 19-36 | F002 |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py` | VectorStoreOrigin — Vector/FTS origin | 16-105 | F003 |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py` | SearchOrigin — Origin extension contract | 18-72 | F003 |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/graphindex.py` | GraphIndexOrigin — Graph federation | 23-83,109-159 | F004 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` | GraphExpandedRetriever — Local graph retrieval and seed dependencies | 168-211,218-242 | F004 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py` | SQLiteGraphReader / search_symbols — Local FTS graph reader | 1-12,47-57,75-85,320-358 | F004 |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py` | MultiStoreSearchToolkit / _run_origins / _rerank_with_bm25 / _deduplicate_hits — Federation ranking and isolation | 245-320,359-420 | F005 |
| `packages/ai-parrot/src/parrot/models/stores.py` | StoreType / SearchOriginKind / SearchResult / OriginHit — Scores and store identifiers | 23-43,46-103 | F005 |
| `packages/ai-parrot/src/parrot/registry/routing/store_router.py` | StoreRouter.execute — Optional router integration | 181-221 | F005 |
| `packages/ai-parrot-embeddings/tests/test_store_backends_present.py` | test_supported_stores_unchanged — Dispatch regression expectations | 7-37,49-55 | F006 |
| `packages/ai-parrot-embeddings/tests/test_namespace_imports.py` | test_supported_stores_unchanged — Namespace regression expectations | 126-139 | F006 |
| `packages/ai-parrot-tools/tests/multistoresearch/test_vector_origin.py` | test_fts_capability_detection — Adapter test precedent | 1-68 | F006 |
| `packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py` | test_timeout_isolated / test_error_isolated / test_fts_skips_non_capable — Toolkit test precedent | 60-145 | F006 |
| `packages/ai-parrot-embeddings/src/parrot/stores/faiss_store.py` | FAISSStore — Local vector precedent | 21-47,89-92 | F006 |

### 2.2 Constraints Discovered

- **Backend packaging and dispatch:** add the implementation to the embeddings satellite and a matching core dispatch entry. The module name must match the configured store key. Optional imports must not make unrelated backend imports require LanceDB. Two existing tests assert the entire dispatch map. Evidence: F001, F006.
- **Full store contract:** implement required lifecycle, collection creation, preparation, ingestion, search and deletion behavior. Preserve metadata filters, parent exclusion and contextual embedding preparation. SQL-shaped compatibility parameters require documented mappings or explicit errors. Evidence: F002.
- **FTS detection:** the vector adapter treats any callable `fulltext_search` as capability. Recommended v1 policy: FTS is available on every LanceDB store instance; create its index as part of collection preparation, including collections reopened without an index. An optional FTS-disable flag would require additional capability handling. Evidence: F003.
- **Score semantics:** preserve raw vector distance in vector `SearchResult` results. Lexical results must label BM25 and its direction through metadata because the shared result model also serializes a `distance` alias. Hybrid fusion scores should be exposed as origin-native relevance through `OriginHit`, with score convention and retrieval mode recorded. Do not reuse vector thresholds for BM25 or RRF. Evidence: F005, F008.
- **Graph composition:** graph topology and SQLite FTS can remain local, but the graph retriever requires a separately configured seed source. Merely supplying a SQLite reader does not produce semantic graph retrieval. Evidence: F004.
- **Cross-store identity:** existing deduplication uses exact IDs and content hashes. Use stable collection-aware IDs; share canonical identities deliberately for the same chunk across sources. Graph associations belong in explicit metadata, not accidental ID collisions. Evidence: F005.

### 2.3 Recent History

No commits touched the multi-store implementation in the last 30 days. Its latest inspected changes are:

| Commit | Date | Author | Change | Evidence |
|---|---|---|---|---|
| `ba5e6fa4ea` | 2026-07-27 | Jesus | Registry swap and migration cleanup | F007 |
| `a1842f60e7` | 2026-07-27 | Jesus | Clean-break migration to toolkit | F007 |
| `f04772da5e` | 2026-07-27 | Jesus | Toolkit with grouped/merged output and isolation | F007 |

The satellite dependency manifest changed on August 20 (`770ae94943`) and August 17 (`f1dda8ffd7`). No LanceDB-specific implementation was found in the searched package Python files and manifests. Evidence: F001, F007.

## 3. Probable Scope

### What's New

**Optional backend.** Proposed new file: `packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py`; proposed class: `LanceDBStore`. These do not exist yet. Use a local directory URI, one table per collection, explicit vector dimensions, stable IDs, original document text, and round-trippable metadata. Build query/document vectors using the existing embedding abstraction. Use the SDK's async surface and explicitly offload any unavoidable blocking conversion or model work. Evidence motivating this design: F001–F002, F008.

**Native FTS.** Provide the adapter-compatible `fulltext_search(query, limit=...)` interface with no query embedding call. Apply the same document visibility and supported metadata filters across vector, lexical and hybrid retrieval. Prefer mandatory native FTS support in v1 to match current capability detection. Evidence: F002–F003, F008.

**Explicit hybrid origin.** Proposed new file: `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/lancedb.py`; proposed class: `LanceDBOrigin`, implementing the existing `SearchOrigin` contract. In hybrid mode, its `search` combines vector and lexical retrieval inside LanceDB and returns native-ranked `OriginHit` values. Its `fts_search` delegates lexical retrieval. Keep the SDK behind the store boundary so importing this adapter does not require the optional SDK. This is a recommended design, not an implemented API. Evidence: F003, F005, F008.

| Requested operation | Proposed composition | Ranking |
|---|---|---|
| Vector only | LanceDB store directly, or existing vector origin | Native vector distance |
| FTS only | Store full-text method, directly or through toolkit FTS | Native BM25; merged toolkit output uses BM25 over candidate content |
| Vector + FTS in one local corpus | Explicit LanceDB hybrid origin | Native hybrid RRF by default |
| Vector + FTS + graph in one call | Hybrid origin plus existing graph origin | Native ranks in sections; current toolkit BM25 in merged output |

The merged toolkit ranking is a second ranking stage. It will not preserve the hybrid origin's RRF ordering globally. Keep that behavior explicit; changing the global fusion algorithm is a separate design decision. Evidence: F005, F008.

**Local operation example.** Demonstrate both a minimal standalone vector/FTS store and federation with prebuilt local graph artifacts. Recommend cached local embeddings and local reranking, with provisioning documented separately. A remote LLM may still be chosen by an application, but a fully offline acceptance profile must neither require credentials nor make network calls. Graph ingestion/extraction has its own model requirements and is not automatically made offline by this backend. Evidence: F002, F004; design inference, medium confidence.

### What Changes

- Add `lancedb` to `supported_stores`, resolving the proposed module/class through existing loaders. Evidence: F001.
- Add an optional `lancedb` dependency extra to `packages/ai-parrot-embeddings/pyproject.toml` and include it in the satellite aggregator if consistent with release policy. Select a tested SDK version and resolve compatibility during implementation; no package is added by this proposal. Evidence: F001.
- Extend dispatch/namespace tests and the existing adapter/toolkit test families to cover the new backend. Evidence: F006.
- Document vector, lexical, hybrid and graph composition with explicit ownership of models, data paths, table lifecycle and maintenance. Evidence: F002–F005, F008–F009.

Automatic adaptive-router selection is deferred: `StoreType` currently lists three backends, and `StoreRouter.execute` consumes enum-keyed stores. Direct configuration and toolkit federation do not require that expansion. Evidence: F005.

### Non-Goals

Global default replacement; automatic PostgreSQL migration; removing PostgreSQL Python dependencies; implementing graph traversal in LanceDB; replacing GraphIndex's FAISS seed index; cloud storage/deployment; distributed transactions; multi-writer or network-filesystem guarantees; new global fusion algorithms; broad store-interface refactoring.

### Integration Risks and Required Decisions

1. **Async API differences.** Current docs distinguish synchronous FTS setup from async index creation and describe Lance-native FTS. Verify the selected release rather than copying older Tantivy examples. Evidence: F008.
2. **Filters and heterogeneous metadata.** Define an explicit supported filter grammar and storage representation; reject unsupported operators. Escape values or use the SDK's supported expression facilities. Preserve parent flags and legacy missing-marker behavior. Never silently ignore filtering. Evidence: F002.
3. **Persistence and freshness.** Specify create/open behavior, reject incompatible dimension/model metadata, and make repeated ingestion idempotent by stable identity. Verify append/update/delete visibility before and after reopen and maintenance. Avoid destructive table recreation during startup. Evidence: F002, F009.
4. **Index maintenance and small collections.** Start with exact vector search for small datasets and make ANN creation explicit. FTS needs an index before lexical queries. Define maintenance separately from every query; verify unindexed additions remain visible in the selected SDK. Evidence: F008–F009.
5. **Concurrency and resource ownership.** Recommend one process owning mutations for v1, with concurrent async reads. Define connection cleanup and cancellation behavior. If independent processes read the dataset, configure and test refresh policy; the documented default does not check for external updates. Evidence: F009.
6. **Ranking and identity.** Preserve provenance, lexical score direction and native distance independently. Prevent unrelated equal IDs across collections from collapsing in merged results. Evidence: F005.
7. **Installation and offline assets.** Resolve the optional SDK against current Arrow/Python constraints and test supported platform wheels. Pre-download local models for offline acceptance. Embedded storage alone provides no proof of offline inference. Evidence: F001–F002, F008–F009.

### Candidate Acceptance Criteria for the Spec

These are proposed checks, not test results.

- A local temporary directory supports create, ingest, query, disconnect and reopen without a PostgreSQL service, Docker or remote credentials.
- With deterministic local embeddings and network access denied, vector search returns expected neighbors and FTS finds an exact identifier; an FTS query makes zero embedding calls.
- Vector, FTS and hybrid modes consistently honor supported filters, parent exclusion, limits, and collection boundaries. Malformed filters fail explicitly.
- Repeated ingestion preserves stable IDs; updates and deletions are reflected across all search modes and after restart. Dimension/model mismatches fail before mutation.
- A hybrid-plus-graph fixture produces provenance-tagged sections and deduplicated merged results; a failed/timed-out origin leaves successful origins usable.
- Scores and rank metadata distinguish vector distance, BM25 and hybrid relevance; vector thresholds are not applied to other scales.
- Real tiny and empty collections work without ANN-training requirements; index preparation is idempotent and new records remain searchable.
- Imports without the optional SDK succeed for unrelated backends; selecting LanceDB reports the required extra clearly. Dispatch/namespace expectations are updated.
- Async searches allow an event-loop heartbeat to progress. The declared writer policy, reader refresh behavior and cleanup are exercised.
- A documented offline example works after provisioning its local model and graph artifacts.

Test design follows the inspected adapter/isolation coverage; real SDK behavior remains to be verified. Evidence: F006, F008–F009.

### External Capability References

- Embedded local connections and platform guidance: [LanceDB quickstart](https://docs.lancedb.com/quickstart).
- Async connection/table APIs and reader consistency: [Python API reference](https://lancedb.github.io/lancedb/python/python/).
- Async native FTS index setup: [FTS indexes](https://docs.lancedb.com/indexing/fts-index).
- Vector/text candidate fusion: [Hybrid search](https://docs.lancedb.com/search/hybrid-search).
- Index freshness and scan fallback: [Reindexing](https://docs.lancedb.com/indexing/reindexing).

References were inspected on 2026-09-10; they establish documented capabilities, not compatibility with a pinned release. See F008–F009.

## 4. Confidence Map

| ID | Claim | Evidence | Confidence |
|---|---|---|---|
| C1 | Concrete backends belong in the embeddings satellite and are selected through core dispatch. | F001 | high |
| C2 | The store API requires lifecycle, ingestion, search and deletion, with default parent exclusion. | F002 | high |
| C3 | The current vector origin can federate a store exposing similarity_search and fulltext_search. | F003 | high |
| C4 | GraphIndex offers a local graph/SQLite FTS path; its semantic seeds still require separate configuration. | F004 | high |
| C5 | The toolkit does not automatically combine an origin's semantic and FTS methods; merged ranking is BM25. | F005 | high |
| C6 | Current LanceDB documentation provides embedded async vector, BM25 and hybrid capabilities. | F008 | high |
| C7 | An optional LanceDB backend with an explicit hybrid origin is a suitable local retrieval design. | F001, F003, F004, F005, F008 | medium |
| C8 | A fully offline configuration is plausible with cached local models and prebuilt graph artifacts. | F002, F004, F008 | medium |
| C9 | Index maintenance, reader freshness, score metadata and document identity need explicit contracts. | F005, F009 | medium |

Distribution: 6 high, 3 medium, 0 low. Overall confidence is medium because scope and end-to-end compatibility are unverified. No benchmark or dependency-resolution experiment was performed.

## 5. Open Questions

### Resolved by Research

- The existing vector adapter supports an optional full-text method. Evidence: F003.
- Local graph/SQLite FTS components exist, with a separate graph seed requirement. Evidence: F004.
- Multi-store search does not automatically issue both semantic and FTS queries to each origin. Evidence: F005.

### Unresolved

- **U1:** Include native hybrid retrieval in a single multi-store call in v1, or initially ship vector and standalone FTS? Recommended: include hybrid. Resolves C7.
- **U2:** Must inference also run offline after provisioning, or only storage? Recommended: provide and validate the fully offline profile. Resolves C8.
- **U3:** Must independent agent processes write the same dataset in v1? Recommended: one process owns writes initially. Resolves C9.

These recommendations are assumptions for discussion, not recorded user acceptance. Owner: user during scope review.

## 6. Recommended Next Step

`$sdd-brainstorm lancedb-vector-store` to settle the three scope choices, followed by `$sdd-spec lancedb-vector-store`. If the proposed defaults are accepted, proceed directly to the specification and its compatibility spike. Implementation tasks are premature until the SDK, filters, score contract and local graph fixture are specified.

## 7. Research Audit

| Artifact | Path |
|---|---|
| Source | [source.md](../state/FEAT-563/source.md) |
| Research plan | [research_plan.json](../state/FEAT-563/research_plan.json) |
| Findings | [findings/](../state/FEAT-563/findings/) |
| Synthesis | [synthesis.json](../state/FEAT-563/synthesis.json) |
| Checkpoint | [state.json](../state/FEAT-563/state.json) |

Budget: 20 unique repository files read / 40; 11 scoped grep/discovery calls / 25; 3 history queries / 10; maximum follow-up depth 2 / 2; 261 seconds / 300. Research was not budget-truncated. Wiki calls and workflow preparation are excluded. Some broad command outputs were clipped; conclusions use visible excerpts and focused follow-up reads.

Wiki orientation succeeded after retrying outside the sandbox; initial logging initialization could not open a socket. The wiki reported 20 stale sources, so exact contracts were confirmed in current files. Mode is enrichment because the source requests a new capability.

## 8. Provenance

Generated through the installed `sdd-proposal` workflow with `parrot-wiki` orientation. Templates: proposal, research-plan prompt/schema, finding, synthesis prompt and state schema (v1.0). Authoring branch: `feat-contracts-demo-agent`; future feature base: `dev`. Only proposal and research state are intended for the scoped commit. No implementation or dependency changes.
