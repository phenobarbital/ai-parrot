---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: LanceDB for Local Vector, Full-Text and Graph-Federated Retrieval

**Date**: 2026-09-10
**Author**: Codex, with scope decisions pending from Jesus Lara
**Status**: exploration
**Recommended Option**: A
**Source Proposal**: [lancedb-vector-store.proposal.md](lancedb-vector-store.proposal.md)
**Research Identity**: FEAT-563, provisional proposal identity; reserve the formal feature ID during specification.

## Problem Statement

An autonomous agent running on a developer machine should be able to persist and search its knowledge without provisioning a PostgreSQL server or container. The requested alternative is LanceDB, usable for vector search alone and for combined vector, full-text and graph retrieval.

The intended users are developers assembling local agents and their retrieval tools. Success means opening a local data directory, ingesting documents, retrieving relevant material, and reopening the same data after restart using existing AI-Parrot configuration and embedding providers. Whether the entire agent must run offline remains a separate user decision.

The existing multi-store toolkit already federates vector and graph origins, but a call selects either each origin's normal search or its FTS method. A dedicated hybrid origin can place LanceDB's vector-plus-FTS results alongside graph results in one call. See Code Context R3–R5.

## Constraints & Requirements

- Flow: `feature`, based on `dev`, carrying forward the proposal and the brainstorm workflow defaults. The authoring branch is `feat-contracts-demo-agent`; this document creates no implementation branch.
- Add an optional backend in `ai-parrot-embeddings`, using the existing `AbstractStore` abstraction and namespace layout. SDK selection remains explicit; no dependency is installed in this brainstorm. R1–R2.
- Local filesystem persistence must not require a database service, container, cloud account or storage API key. Model providers remain an independent configuration concern.
- Preserve async public operations, stable identities, collection isolation, metadata filtering and default parent-document exclusion. R2.
- Preserve native score semantics and provenance. Vector distance, lexical BM25 and hybrid relevance are different quantities. R4.
- Reuse existing GraphIndex retrieval when graph federation is enabled. Replacing its internal seed backend is a distinct scope choice. R5.
- Keep existing configured PostgreSQL and other backends usable. No automatic migration or global default switch is requested.
- Implement no distributed transactions, cloud deployment or network-filesystem guarantees as part of the proposed baseline.
- No numerical latency, memory, corpus-size or recall target was supplied. Establish a representative corpus during specification before making performance commitments.

### Q&A Record

Two question rounds were presented during this brainstorm. No answers had been received when this exploration draft was written. The following are proposed defaults, not approvals.

| Round | Topic | Proposed interpretation | Status |
|---|---|---|---|
| 1 | Flow settings | Feature based on dev | Workflow default; confirmation unanswered |
| 1 | Users and first-release behavior | Autonomous agents; vector, FTS and native hybrid, with optional graph federation | Pending |
| 1 | Local-only boundary | Embedded storage; retain configured embedding/LLM providers and offer a local-model example | Pending; proposal also considered a mandatory offline profile |
| 2 | Writer concurrency | One process owns mutations; concurrent async reads | Pending |
| 2 | Graph integration | Combine results with existing GraphIndex; retain its seed backend | Pending |
| 2 | Hybrid failure | Report an origin error; other origins continue | Pending |

The local-only boundary is deliberately unresolved. The initial request explicitly removes PostgreSQL deployment; it does not explicitly require replacing model providers. A fully offline acceptance profile remains available if selected.

## Options Explored

All three options add the requested LanceDB backend. They differ in how combined retrieval reaches the existing multi-store toolkit.

### Option A: LanceDB Backend with a Dedicated Hybrid Origin

Implement a full store backend for lifecycle, ingestion, vector search, FTS and native hybrid retrieval. Add a small LanceDB-specific `SearchOrigin` adapter whose normal search uses the selected vector or hybrid mode and whose FTS method performs lexical search. The store owns SDK calls; the origin owns federation payloads. Existing `VectorStoreOrigin` remains usable for vector-only integrations.

**Pros:**

- Covers the requested modes and supports native vector/FTS fusion before graph federation.
- Keeps LanceDB behavior explicit, including score mapping, missing-index errors and query limits.
- Requires no reinterpretation of existing backends' hybrid methods.
- Contains changes mainly within one new backend and one new origin.

**Cons:**

- Adds a backend-specific adapter that may later overlap a generalized capability API.
- Requires a precise store-to-origin hybrid result contract.
- Native hybrid ordering survives in the origin section, but the toolkit's merged list is reranked separately with BM25. R4.

**Effort:** Medium.

**Libraries / Tools:**

| Package | Purpose | Verification |
|---|---|---|
| `lancedb` | Embedded vector, FTS and native hybrid engine | New optional dependency; absent from inspected manifests; version compatibility untested |
| `pyarrow` | Explicit storage schemas and result conversion | Core declares `>=25.0`; R7 |
| Existing embedding backend | Generate vectors through AI-Parrot | Satellite declares local and remote provider extras; R1 |
| `rustworkx`, `aiosqlite` | Existing optional graph composition | Already declared by core; R7 |

**Existing Code to Reuse:**

- `packages/ai-parrot/src/parrot/stores/abstract.py:245` — store search contract and parent visibility.
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:42` — origin interface.
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:90` — provenance normalization pattern.
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/graphindex.py:43` — graph federation configuration.

### Option B: LanceDB Backend with a Generic Hybrid-Origin Contract

Define an explicit backend-neutral hybrid capability with uniform limits, filters, score conventions and result types, then add an opt-in generic origin adapter. Adapt LanceDB first. Existing origins continue using their current methods until explicitly wrapped.

**Pros:**

- Establishes a reusable extension point for other hybrid backends.
- Centralizes mode selection and normalization.
- Could support Arango and other stores through explicit wrappers later.

**Cons:**

- Broadens this feature into shared API design and compatibility work.
- Existing methods named `hybrid_search` differ in meaning and arguments: PostgreSQL uses dense-plus-ColBERT with `top_k`; Arango uses vector-plus-text with `limit`. Method-name detection alone is insufficient. R6.
- Requires regression coverage across consumers of the new capability and careful separation from distance-based results.

**Effort:** High.

**Libraries / Tools:**

| Package | Purpose | Verification |
|---|---|---|
| `lancedb`, `pyarrow` | New backend and schema handling | Same dependency position as Option A |
| Existing Python typing and core models | Explicit capability/result contract | Origin and store models already exist; R3–R4 |
| Existing PostgreSQL/Arango implementations | Contract comparison and potential future wrappers | Inspected, with incompatible hybrid semantics; R6 |

**Existing Code to Reuse:**

- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:42` — shared origin surface.
- `packages/ai-parrot/src/parrot/models/stores.py:79` — native-score payload conventions.
- `packages/ai-parrot-embeddings/src/parrot/stores/postgres.py:1728` and `packages/ai-parrot-embeddings/src/parrot/stores/arango.py:801` — inputs to explicit wrapper design, not interchangeable implementations.

### Option C: Two Origins over One LanceDB Table

Expose the same corpus through two origins: one calls vector search and the other calls FTS as its normal search. The toolkit gathers both, alongside the graph origin, and performs its existing merged ranking. This is the less obvious alternative: multi-mode retrieval can be composed at the origin level without calling LanceDB's native hybrid query.

**Pros:**

- Uses the existing federation control flow and provides separate vector/lexical diagnostic sections.
- Each retrieval leg can fail independently while others continue.
- Stores documents once in LanceDB while offering different query views.

**Cons:**

- Does not provide LanceDB-native hybrid fusion unless that is added separately.
- Repeated candidates enter the toolkit's BM25 corpus before deduplication; duplicate legs can influence merged ranking. R4.
- Shared IDs, timeouts and FTS capability flags need care to avoid duplicate lexical calls or misleading origin listings.
- Requires a new lexical-view adapter; two unchanged `VectorStoreOrigin` instances would both run vector search.

**Effort:** Medium, with less native-hybrid work but more federation configuration.

**Libraries / Tools:**

| Package | Purpose | Verification |
|---|---|---|
| `lancedb`, `pyarrow` | One local document/vector/FTS table | New SDK extra and existing Arrow dependency |
| `rank_bm25` | Existing merged ranking | Already declared; toolkit uses `BM25Okapi`; R4, R7 |
| Existing GraphIndex dependencies | Third search origin | R5, R7 |

**Existing Code to Reuse:**

- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:50` — vector view.
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:42` — new lexical view contract.
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:268` — concurrent origin execution.
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:390` — existing deduplication behavior.

## Recommendation

Recommend **Option A — LanceDB Backend with a Dedicated Hybrid Origin**, subject to the unanswered scope questions. It provides the requested embedded backend and a direct route from native hybrid retrieval to graph federation. The additional adapter is small relative to defining a reusable hybrid API across backends whose semantics already differ.

Choose Option B if a shared hybrid capability for multiple databases is itself a requirement. Choose Option C if separately visible retrieval legs and independent failure handling matter more than native hybrid fusion. If the first release is limited to vector and standalone FTS, Option A can ship its backend first and defer its hybrid origin.

LanceDB's current documentation describes vector-plus-FTS retrieval with default reciprocal-rank fusion and explicit text/vector inputs. This allows retaining AI-Parrot's embedding provider rather than adopting a second embedding registry. The exact async SDK calls and compatible release still require validation. [Official hybrid search documentation](https://docs.lancedb.com/search/hybrid-search).

## Feature Description

### User-Facing Behavior

An agent developer selects the proposed `lancedb` backend, a local directory, a collection and the existing embedding configuration. Opening the store reuses persistent data. Startup does not overwrite tables or require a PostgreSQL process.

Developers can choose vector-only, lexical-only or hybrid retrieval. Graph federation is optional and uses separately configured local graph artifacts. Search responses keep source information and per-origin status so an agent can distinguish a missing result from a failed retrieval origin.

| Operation | Proposed entry point | Result ordering |
|---|---|---|
| Vector search | Store or existing vector origin | Raw vector distance, native order |
| Lexical search | Store full-text method or toolkit FTS | Native BM25 within an origin |
| Hybrid search | Dedicated origin using the store's native hybrid operation | Native fusion order within its section |
| Hybrid plus graph | Dedicated origin plus existing graph origin | Native section order and toolkit BM25 merged order |

This feature guarantees local storage under the proposed baseline. It preserves provider choice. A fully offline agent profile would additionally require cached local embedding/LLM assets and graph preparation appropriate to that profile; that requirement awaits user selection.

### Internal Behavior

1. Resolve the backend through the existing dispatch map and load its optional SDK only when selected. R1.
2. Open a long-lived async connection and an explicit per-collection schema. Record the dimension and embedding identity needed to detect incompatible reopen attempts.
3. Persist stable IDs, original chunk text, vectors and metadata. Define a filterable representation rather than relying on arbitrary schema inference from the first record. Generate contextual embeddings through the existing hook while keeping original text available. R2.
4. Prepare native FTS as part of collection setup. Current async documentation uses `create_index` with `FTS` configuration; `create_fts_index` is synchronous, and legacy Tantivy options are no longer accepted. [Official FTS index documentation](https://docs.lancedb.com/indexing/fts-index).
5. Apply collection, metadata and parent-visibility predicates before candidate limits in each search mode. Unsupported filter operators fail explicitly.
6. Preserve vector `SearchResult.score` as distance. For the adapter-compatible full-text method, document native BM25 metadata and the legacy `distance` alias. Use an explicit typed internal hybrid result carrying score kind/direction; the origin converts it to `OriginHit`. The backend must not import the tools distribution. R4.
7. Let the toolkit isolate origin failures and construct its grouped and merged response. Native hybrid fusion does not replace the toolkit's final BM25 pass. R4.
8. Define separate maintenance and shutdown behavior. Empty and small collections use exact vector search without forcing ANN training. Read freshness and mutation ownership must match the selected concurrency policy.

The internal hybrid record is a proposed contract, not an existing type. Its final shape belongs in the spec; do not invent a pre-existing shared `HybridSearchResult` model.

### Edge Cases & Error Handling

- **Missing SDK:** selecting the backend gives a precise optional-extra installation message; unrelated store imports remain usable.
- **Unwritable path or incompatible schema:** fail during initialization; do not silently create a different database or replace existing data.
- **Empty collection/query:** define consistent empty results and input validation; do not attempt ANN training on insufficient rows.
- **Missing FTS index:** prepare it during setup or report an explicit initialization failure. Never advertise successful FTS while returning vector results.
- **Missing or failing embedder:** vector and hybrid requests fail explicitly; FTS must not generate an embedding. The implementation must avoid an eager model requirement preventing an otherwise valid lexical query.
- **Duplicate/reingested chunks:** preserve stable identity and define upsert behavior. Identical IDs in unrelated collections must not collapse accidentally during federation.
- **Metadata and parent visibility:** verify nulls, absent keys and legacy chunks without markers; reject unsupported filters instead of dropping them.
- **Delete/update:** all modes reflect successful mutations, including after reopening. Empty destructive filters must not imply deleting an entire collection.
- **One origin fails:** use the toolkit's existing error/timeout status; successful origins continue. Partial fallback inside a hybrid origin is an unanswered product choice.
- **Graph unavailable:** standalone LanceDB works. A configured graph origin reports its own failure; no graph is silently fabricated from vector rows.
- **Concurrent processes:** no guarantee is claimed until the writer and reader-freshness policies are chosen and tested. An async lock inside one instance is not cross-process coordination.
- **Cancellation and maintenance:** specify bounded cancellation and resource ownership; do not promise cancellation of already committed writes or prune recovery data automatically.

### Proposed Success Checks

Use a real temporary LanceDB directory and deterministic local embeddings for storage tests. Verify persistence after reopen; vector neighbors; lexical identifiers without embedding calls; hybrid candidates; metadata/parent filtering; stable IDs and mutations; dimension/model mismatch rejection; and provenance across a hybrid-plus-graph query. Exercise isolated origin errors and an event-loop heartbeat. Add a configured provider example, with a network-disabled profile only if the offline requirement is selected.

These are acceptance candidates, not completed tests. No implementation, dependency resolution, SDK execution or performance benchmark was performed in this brainstorm.

## Capabilities

### New Capabilities

- `lancedb-local-store`: persistent local collections with the complete required store lifecycle and document operations.
- `lancedb-vector-fts-search`: semantic and lexical retrieval with explicit filters and score conventions.
- `lancedb-hybrid-origin`: native vector/FTS fusion exposed through the existing origin contract.
- `lancedb-graph-federation`: composition with a separately configured existing GraphIndex origin.

These are candidate capabilities for one feature spec; they do not require separate feature IDs or independent worktrees.

### Modified Capabilities

- `multistoresearchtool-parrotwiki`: extend the available origin set; preserve the established grouped/merged payload and failure isolation. Existing spec: `sdd/specs/multistoresearchtool-parrotwiki.spec.md`.
- `ai-parrot-embeddings`: add an optional backend extra and namespace module. Existing spec: `sdd/specs/ai-parrot-embeddings.spec.md`.

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| Embeddings satellite store namespace | extends | Proposed new `packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py`; proposed `LanceDBStore` |
| Satellite dependency manifest | modifies | New optional SDK extra; resolve a supported release against Arrow/Python constraints |
| Core `supported_stores` | modifies | Add a matching module/class entry; retain existing keys |
| Origin adapters | extends | Proposed new `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/lancedb.py`; proposed `LanceDBOrigin`; export through existing origins package |
| Core store/embedding contracts | depends on | Existing lifecycle, contextual embedding and document visibility behavior |
| GraphIndex | depends on | Existing graph, seed source and optional SQLite reader; no seed replacement in recommended baseline |
| Store/namespace and toolkit tests | extends | Update dispatch expectations and add real SDK integration coverage |
| Adaptive store router | deferred | Direct backend configuration and toolkit composition first; enum expansion is additional integration work |

New paths and symbols in this table are design proposals. Existing references are grounded below and in the linked proposal findings.

## Code Context

### User-Provided Code

No code snippets were supplied. The originating request is preserved verbatim:

> $dd-proposal lancedb-vector-store -- for a vector-store search or combined with graph and FTS (multi-store search) for local (autonomous) operations, adopting LanceDB instead postgres+pgvector is useful for local-only agents without deploying an docker for postgres

### Verified Codebase References

References were read in the current checkout. The original evidence remains at `sdd/state/FEAT-563/findings/`; this brainstorm additionally inspected existing hybrid method contracts to compare Option B.

#### Classes & Signatures

| Ref | Existing location | Verified contract |
|---|---|---|
| R1 | `packages/ai-parrot/src/parrot/stores/__init__.py:6` | `supported_stores` maps configuration keys to class names |
| R1 | `packages/ai-parrot/src/parrot/interfaces/vector.py:42` | `_get_database_store(self, store: dict) -> AbstractStore`; imports `parrot.stores.{name}` |
| R1 | `packages/ai-parrot-embeddings/pyproject.toml:62` | Per-backend optional dependency extras; aggregator at line 97 |
| R2 | `packages/ai-parrot/src/parrot/stores/abstract.py:245` | `similarity_search(self, query: str, collection: Union[str, None] = None, limit: int = 2, similarity_threshold: float = 0.0, search_strategy: str = "auto", metadata_filters: Union[dict, None] = None, include_parents: bool = False, **kwargs) -> list` |
| R2 | `packages/ai-parrot/src/parrot/stores/abstract.py:202` | Required `connection`; `disconnect` at 212; `get_vector` at 238; `from_documents` at 276; `create_collection` at 295; `add_documents` at 308 |
| R2 | `packages/ai-parrot/src/parrot/stores/abstract.py:383` | `generate_embedding(self, documents: List[Any]) -> List[Any]`; contextual augmentation at 391 |
| R2 | `packages/ai-parrot/src/parrot/stores/abstract.py:455` | Required `prepare_embedding_table`; deletion methods at 494 and 520 |
| R3 | `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:42` | `search(self, query: str, k: int) -> List[OriginHit]`; optional `fts_search` at 54 |
| R3 | `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:50` | `search(self, query: str, k: int) -> List[OriginHit]` delegates to `similarity_search(query, limit=k)` |
| R3 | `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:66` | `fts_search(self, query: str, k: int) -> List[OriginHit]` delegates to `fulltext_search(query, limit=k)` |
| R4 | `packages/ai-parrot/src/parrot/models/stores.py:46` | `SearchResult` carries metric-native `score` and a computed `distance` alias at 74 |
| R4 | `packages/ai-parrot/src/parrot/models/stores.py:79` | `OriginHit` carries native score, origin and native rank |
| R4 | `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:246` | `_build_response` reranks before deduplicating; dispatch at 268; BM25 at 359; deduplication at 390 |
| R5 | `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/graphindex.py:43` | Constructor requires a retriever; reader is optional and controls FTS support |
| R5 | `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py:186` | `GraphExpandedRetriever` takes graph/nodes and at least one of `embedder` or `hybrid_search` |
| R5 | `packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py:320` | `search_symbols(self, query: str, *, limit: int = 20) -> list[dict]`; SQLite FTS5 BM25 is negative, ascending best |
| R6 | `packages/ai-parrot-embeddings/src/parrot/stores/postgres.py:1728` | `hybrid_search` takes `top_k=10`, optional `query_tokens`, dense/ColBERT weights; not lexical BM25 hybrid |
| R6 | `packages/ai-parrot-embeddings/src/parrot/stores/arango.py:801` | `hybrid_search` takes `limit=10`, text/vector weights and analyzer; vector-plus-text semantics |
| R7 | `packages/ai-parrot/pyproject.toml:157` | `pyarrow>=25.0`; `faiss-cpu>=1.9.0` at 163, `rustworkx>=0.15` at 169, `aiosqlite>=0.17` at 172; `rank_bm25==0.2.2` at 358 |

#### Verified Imports

These import statements were inspected in existing source; no runtime-import verification is claimed.

- `from .abstract import AbstractStore` — `packages/ai-parrot/src/parrot/stores/__init__.py:4`.
- `from parrot.models import OriginHit, SearchOriginKind` — `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:10`.
- `from parrot.models.stores import SearchResult` — same file, line 11.
- `from .base import SearchOrigin` — same file, line 13.
- Origin package exports `SearchOrigin`, `VectorStoreOrigin` and `GraphIndexOrigin` — `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py:7` through line 11.
- `import aiosqlite` and `import rustworkx as rx` — `packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py:23` and line 25.

#### Key Attributes & Constants

- `VectorStoreOrigin.supports_fts` is computed from a callable `fulltext_search` attribute — `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:48`.
- `GraphIndexOrigin.supports_fts` is true when a reader is supplied — `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/graphindex.py:67`.
- `SearchResult.distance` returns `score` unchanged — `packages/ai-parrot/src/parrot/models/stores.py:74`.
- `OriginHit.native_rank` is one-based — `packages/ai-parrot/src/parrot/models/stores.py:101`.
- `MultiStoreSearchToolkit._run_origins` chooses one method for each origin per call — `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:285`.

### Does NOT Exist (Anti-Hallucination)

- No `LanceDBStore`, `LanceDBOrigin`, `HybridStoreOrigin`, `FullTextStoreOrigin` or `lancedb` declaration was found in the searched package Python files and manifests. The proposed backend and adapters must be created.
- The current vector origin has no mode parameter and does not call native hybrid search automatically. R3.
- A uniform hybrid method contract cannot be inferred from the existing method name; R6 demonstrates incompatible meanings and limit parameters.
- The SQLite graph reader is not a semantic seed provider. R5.
- No universal comparable score exists across vector, FTS and graph origins; the current models explicitly distinguish native scores. R4.

## Parallelism Assessment

- **Internal parallelism:** after agreeing on the store-to-origin result contract, backend work and origin-adapter work can be developed independently. Real integration tests depend on both. Packaging, dispatch and final integration should have one owner.
- **Cross-feature independence:** new backend/origin files are narrow additions. Shared conflict points are the satellite manifest, core dispatch and origin exports. The inspected task indexes for `multistoresearchtool-parrotwiki`, `ai-parrot-embeddings` and `graphindex-retriever` contain only done tasks (9, 9 and 15 respectively); this is not a repo-wide concurrency audit.
- **Recommended isolation:** per-spec.
- **Rationale:** one feature worktree keeps schema, payload and SDK-version choices consistent while avoiding separate branches editing shared dispatch and packaging files. No parallel agents were launched for this documentation task.

## Open Questions

- [ ] Include vector, FTS and native hybrid with optional graph federation in v1, or ship only vector and standalone FTS first? — *Owner: Jesus Lara*
- [ ] Does local-only require embedded storage with existing model providers, or a fully offline agent after provisioning? — *Owner: Jesus Lara*
- [ ] Can one process own writes initially, or must independent processes write the same dataset concurrently? — *Owner: Jesus Lara*
- [ ] Is federation with existing GraphIndex sufficient, or must LanceDB also replace its internal seed index? — *Owner: Jesus Lara*
- [ ] Should a failing hybrid leg fail that origin while other origins continue, or return explicitly marked partial results? — *Owner: Jesus Lara*

Spec-stage technical work: resolve and test an SDK release, finalize filter/metadata representation and hybrid result types, define index/read-freshness lifecycle, and choose a representative acceptance corpus. These are engineering tasks rather than additional user questions.

Next: resolve the five scope questions and run `$sdd-spec lancedb-vector-store`. This exploration document is not user acceptance of Option A or its defaults.
