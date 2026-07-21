---
type: Wiki Overview
title: 'Feature Specification: PageIndex Embedding Router'
id: doc:sdd-specs-pageindex-embedding-router-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: PageIndex retrieval today combines BM25 lexical ranking over flattened node
  text
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
- concept: mod:parrot.embeddings.matryoshka
  rel: mentions
- concept: mod:parrot.embeddings.registry
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.embedding_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.hybrid_search
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.retriever
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.toolkit
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.tree_ops
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.vector_walk
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: PageIndex Embedding Router

**Feature ID**: FEAT-237
**Jira**: NAV-8351 _(pending — ticket to be created manually; API token lacks project access)_
**Date**: 2026-06-15
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor
**Brainstorm**: `sdd/proposals/pageindex-embedding-router.brainstorm.md`
**Proposal**: `sdd/proposals/pageindex-embedding-router.proposal.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

PageIndex retrieval today combines BM25 lexical ranking over flattened node text
and an LLM tree-walk (`PageIndexRetriever`) that serializes the entire tree
structure to JSON and asks the model to return relevant `node_id`s, fused via
Reciprocal Rank Fusion.

Two gaps follow:

1. **No dense semantic signal.** Synonymy / paraphrase queries that BM25 misses
   depend entirely on the LLM walk. There is no embedding-based ranking
   anywhere in the PageIndex path.
2. **The LLM walk does not scale.** One large LLM call per query, with a prompt
   that grows with the tree. As trees grow the JSON approaches context limits
   and reasoning quality degrades; latency and token cost are unbounded in tree
   size.

### Goals

- **G1**: Add a dense embedding ranking signal fused into the existing RRF
  (Phase A — immediate recall improvement for synonymy/paraphrase queries).
- **G2**: Add an embedding-guided beam walk that proposes candidate branches
  with O(depth) local matmuls, so the LLM is consulted only at ambiguous
  branch points (Phase B — scaling improvement, flag-gated).
- **G3**: Build a real, reproducible compliance corpus (SOC 2 + HIPAA) that
  serves as the benchmark fixture AND the first knowledge bank for the
  `ComplianceEvidenceAgent`.
- **G4**: Ship a CPU latency micro-benchmark that measures model x backend x
  dim on the compliance corpus and outputs a recommendation gate.
- **G5**: Support ONNX/OpenVINO backends in `SentenceTransformerModel` for
  CPU-optimized inference.

### Non-Goals (explicitly out of scope)

- **Not** replacing chunk-level conversational RAG (`PgVectorStore` / FAISS).
- **Not** introducing a global ANN index or vector-DB server for PageIndex.
  The tree shards the corpus; brute-force matmul is exact and faster than ANN
  in this regime.
- **Not** GPU-mandatory. CPU is the target; GPU is an opportunistic speedup.
- **Not** changing the reranker contract (`AbstractReranker`) or the RRF
  constant (`_RRF_K = 60`).
- **Not** removing the LLM walk. Per the platform invariant, the deterministic
  matmul *proposes*; the probabilistic LLM *decides*.
- Runtime fallback-on-failure was not explored — see brainstorm for option
  analysis.

---

## 2. Architectural Design

### Overview

**Phased approach (brainstorm Option C)**:

- **Phase A — Dense-as-third-RRF-input.** Embed `title+summary` per node into
  a per-tree `(N, d)` numpy matrix. One matmul produces a dense ranking. Add as
  a third list to `_rrf_fuse`. LLM walk untouched. Smallest change; purely
  additive; closes the synonymy gap.

- **Phase B — Embedding-guided beam walk (flag-gated).** Beam search down the
  tree using local `(n_children, d) @ (d,)` matmuls. LLM never reads the whole
  ToC. Cuts LLM tokens/latency drastically; scales with tree depth not size.
  Invoked only when the `use_embedding_walk` flag is enabled.

Both phases share a `NodeEmbeddingStore` that content-addresses node embeddings
and materializes a contiguous per-tree matrix for BLAS matmul.

Node embeddings use `title + summary` as the text target (resolved in proposal
Q&A). The embedding model is selected by a CPU latency benchmark (resolved:
benchmark-first strategy with Qwen3 and Octen in the matrix).

### Component Diagram

```
                    HybridPageIndexSearch.search()
                    ┌─────────────────────────────┐
                    │                             │
              ┌─────┴─────┐  ┌──────┴──────┐  ┌──┴───────────┐
              │ _bm25_rank │  │ _llm_rank   │  │ _vec_rank    │  ← Phase A NEW
              │ (BM25)     │  │ (LLM walk)  │  │ (dense cos)  │
              └─────┬─────┘  └──────┬──────┘  └──┬───────────┘
                    │               │             │
                    └───────┬───────┴─────────────┘
                            │
                     _rrf_fuse([bm25, llm, vec])
                            │
                     Optional reranker
                            │
                      Top-k results

  ┌─────────────────────────────────────────────────┐
  │ NodeEmbeddingStore (NEW)                        │
  │  ├── Global cache: content-addressed .npy       │
  │  │   key = sha1(model_id + title + summary)     │
  │  └── Per-tree matrix: (N, d) contiguous .npy    │
  │      rebuilt on mark_dirty(); mmap for matmul   │
  └─────────────────────────────────────────────────┘

  Phase B (flag-gated):
  ┌─────────────────────────────────────────────────┐
  │ embedding_tree_walk()                           │
  │  beam search: local (n_children, d) @ (d,)     │
  │  O(depth) matmuls → candidate node_ids          │
  │  → feeds _rrf_fuse or replaces _llm_rank        │
  └─────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `HybridPageIndexSearch` | extends | Add `_vec_rank()`, update `search()`, update `_rrf_fuse` call |
| `PageIndexRetriever` | adapts (Phase B) | Beam walk pre-filters or replaces full-tree JSON serialization |
| `PageIndexToolkit` | extends | Construct + inject `NodeEmbeddingStore`, propagate dirty flag |
| `NodeContentStore` | pattern sibling | `NodeEmbeddingStore` mirrors its sidecar + LRU + loader_for pattern |
| `EmbeddingRegistry` | reuses | `get_or_create()` for model loading; kwargs flow through |
| `MatryoshkaConfig` | reuses | FEAT-150 truncation path for dim reduction (e.g. 1024→256) |
| `SentenceTransformerModel` | extends | Add `backend` kwarg (onnx/openvino) to `_create_embedding` |
| `EmbeddingModelEntry` | extends | Add optional `backend` field to catalog schema |
| `EMBEDDING_MODELS` | extends | Add Qwen3-Embedding-0.6B, multilingual-e5-small, potion-multilingual |

### Data Models

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py

import hashlib
import numpy as np
from pathlib import Path
from typing import Optional, Callable
from collections import OrderedDict


class NodeEmbeddingStore:
    """Two-tier content-addressed embedding cache for PageIndex trees.

    Global tier: per-node embedding vectors keyed by
        sha1(model_id + "\\x00" + title + "\\x00" + summary)
    Per-tree tier: materialized (N, d) contiguous numpy matrix,
        rebuilt on mark_dirty().

    Args:
        storage_dir: Directory for .npy sidecar files.
        model_id: Embedding model identifier (for cache key).
        dimension: Embedding dimension (after optional MRL truncation).
        cache_size: LRU cache capacity for global tier.
    """

    def __init__(
        self,
        storage_dir: str | Path,
        model_id: str,
        dimension: int,
        cache_size: int = 512,
    ) -> None: ...

    @staticmethod
    def content_key(model_id: str, title: str, summary: str) -> str:
        """SHA-1 hash for content-addressed global cache."""
        ...

    def get_or_embed(
        self,
        tree_name: str,
        node_id: str,
        title: str,
        summary: str,
    ) -> np.ndarray:
        """Return cached vector or mark node as needing embedding."""
        ...

    def build_tree_matrix(
        self,
        tree_name: str,
        nodes: list[dict],
        embed_fn: Callable[[list[str]], np.ndarray],
    ) -> tuple[np.ndarray, list[str]]:
        """Build/rebuild the (N, d) matrix for a tree.

        Returns (matrix, node_id_order) where matrix[i] is the
        embedding for node_id_order[i].
        """
        ...

    def load_tree_matrix(self, tree_name: str) -> Optional[tuple[np.ndarray, list[str]]]:
        """Load the materialized per-tree matrix (mmap mode)."""
        ...

    def invalidate_tree(self, tree_name: str) -> None:
        """Delete the per-tree matrix; global cache entries survive."""
        ...
```

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/vector_walk.py (Phase B)

async def embedding_tree_walk(
    tree: dict,
    query_vec: np.ndarray,
    store: NodeEmbeddingStore,
    beam_width: int = 3,
    max_depth: int = 10,
) -> list[str]:
    """Beam search over per-node embeddings to propose candidate node_ids.

    At each level, scores children via cosine similarity (matmul),
    keeps top beam_width branches, and descends. Returns leaf + branch
    node_ids ordered by cumulative score.
    """
    ...
```

### New Public Interfaces

```python
# Additions to HybridPageIndexSearch
class HybridPageIndexSearch:
    def __init__(
        self,
        ...,
        embedding_store: Optional[NodeEmbeddingStore] = None,  # NEW
        use_vec_rank: bool = False,  # NEW — Phase A flag
        use_embedding_walk: bool = False,  # NEW — Phase B flag
    ): ...

    def _vec_rank(self, query: str, top_k: int) -> list[str]:
        """Dense cosine ranking over the per-tree embedding matrix."""
        ...

    async def search(
        self,
        query: str,
        top_k: int = 10,
        use_bm25: bool = True,
        use_llm_walk: bool = True,
        use_vec: bool = False,  # NEW — enables dense signal
        rerank: bool = False,
    ) -> list[dict]: ...
```

```python
# Addition to EmbeddingModelEntry (catalog.py)
class EmbeddingModelEntry(BaseModel):
    ...
    backend: Optional[Literal["torch", "onnx", "openvino"]] = None  # NEW
```

```python
# Addition to SentenceTransformerModel (huggingface.py)
class SentenceTransformerModel(EmbeddingModel):
    def __init__(
        self,
        model_name: str,
        matryoshka: Optional[dict] = None,
        backend: Optional[str] = None,  # NEW — "torch"|"onnx"|"openvino"
        file_name: Optional[str] = None,  # NEW — quantized model filename
        **kwargs,
    ): ...
```

---

## 3. Module Breakdown

### Module 1: Catalog + Backend Field

- **Path**: `packages/ai-parrot/src/parrot/embeddings/catalog.py`
- **Responsibility**: Add optional `backend` field to `EmbeddingModelEntry`.
  Add catalog entries for Qwen3-Embedding-0.6B, multilingual-e5-small,
  potion-multilingual (model2vec/static).
- **Depends on**: none

### Module 2: SentenceTransformerModel Backend Support

- **Path**: `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py`
- **Responsibility**: Accept `backend` and `file_name` kwargs in `__init__`,
  forward to `SentenceTransformer()` in `_create_embedding()`.
- **Depends on**: Module 1 (catalog entries reference backends)

### Module 3: NodeEmbeddingStore

- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py` (NEW)
- **Responsibility**: Two-tier content-addressed embedding cache. Global tier
  keyed by `sha1(model_id + title + summary)`. Per-tree materialized `(N, d)`
  `.npy` matrix. LRU cache. `build_tree_matrix()` re-embeds only changed
  nodes. `invalidate_tree()` deletes per-tree matrix without touching global
  cache.
- **Depends on**: none (pure numpy + stdlib)

### Module 4: Dense RRF Fusion (Phase A)

- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py`
- **Responsibility**: Add `_vec_rank()` method. Wire `NodeEmbeddingStore` via
  constructor. Embed query via `encode()`, matmul against per-tree matrix.
  Add `use_vec` parameter to `search()`. Fuse via `_rrf_fuse([bm25, llm, vec])`.
  Wire dirty flag to `NodeEmbeddingStore.invalidate_tree()`.
- **Depends on**: Module 3

### Module 5: Embedding Beam Walk (Phase B)

- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/vector_walk.py` (NEW)
- **Responsibility**: `embedding_tree_walk()` beam search function.
  `FlatMatrixSearch` helper for brute-force cosine over child submatrices.
  Flag-gated via `use_embedding_walk` on `HybridPageIndexSearch`.
- **Depends on**: Module 3, Module 4

### Module 6: Toolkit Wiring

- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py`
- **Responsibility**: Construct `NodeEmbeddingStore` in `__init__`. Pass it to
  `HybridPageIndexSearch` in `_search_for()`. Propagate dirty flag on tree
  mutations. Add embedding model config parameters.
- **Depends on**: Module 3, Module 4

### Module 7: Compliance Corpus

- **Path**: `corpus/compliance_soc2_hipaa/` (NEW directory)
- **Responsibility**: `manifest.yaml` with source URLs + SHA-256 checksums +
  per-source `redistributable` flag. `fetch.py` manifest-driven downloader.
  `build_tree.py` orchestrates `PageIndexToolkit.import_pdf`. AICPA TSC
  sources marked `redistributable: false`; public-domain NIST sources
  marked `redistributable: true`.
- **Depends on**: PageIndexToolkit (existing)

### Module 8: CPU Latency Benchmark

- **Path**: `benchmarks/pageindex_embedding_latency/` (NEW directory)
- **Responsibility**: `harness.py` matrix runner (models x backends x dims).
  `metrics.py` latency percentiles, RSS, recall@k. `report.py` markdown +
  JSON output. `conftest_tree.py` loads the compliance tree as fixture.
  Pin BLAS/OMP threads, warmup runs, N>=30 repeats, median+p95.
- **Depends on**: Module 7 (compliance corpus as fixture)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_content_key_deterministic` | Module 3 | Same inputs produce same hash |
| `test_content_key_varies_on_model` | Module 3 | Different model_id changes hash |
| `test_build_tree_matrix_shape` | Module 3 | Output matrix has shape `(N, d)` |
| `test_build_tree_matrix_cache_hit` | Module 3 | Unchanged nodes not re-embedded |
| `test_invalidate_tree_preserves_global` | Module 3 | Global cache survives per-tree invalidation |
| `test_vec_rank_returns_node_ids` | Module 4 | `_vec_rank` returns ranked node_id list |
| `test_vec_rank_disabled_no_effect` | Module 4 | `use_vec=False` produces identical results |
| `test_rrf_fuse_three_lists` | Module 4 | `_rrf_fuse` handles 3 input lists correctly |
| `test_dirty_rebuilds_embedding_matrix` | Module 4 | `mark_dirty` triggers matrix rebuild on next query |
| `test_beam_walk_returns_candidates` | Module 5 | Beam walk returns `node_id` list for a test tree |
| `test_beam_walk_respects_depth` | Module 5 | Stops at `max_depth` |
| `test_backend_kwarg_forwarded` | Module 2 | `_create_embedding` passes `backend` to `SentenceTransformer` |
| `test_catalog_backend_field_optional` | Module 1 | Existing entries validate without `backend` |

### Integration Tests

| Test | Description |
|---|---|
| `test_hybrid_search_with_vec_signal` | Full `search()` with `use_vec=True`: BM25 + LLM + dense produces fused results |
| `test_hybrid_search_vec_only` | `search()` with `use_bm25=False, use_llm_walk=False, use_vec=True` returns dense-only results |
| `test_embedding_survives_reindex` | After `splice_subtree` + `reindex_node_ids`, unchanged nodes hit global cache |
| `test_embedding_survives_delete_node` | After `delete_node`, remaining embeddings still valid |
| `test_flag_gated_byte_identical` | With embedding signal disabled, `search()` output is byte-identical to baseline |

### Test Data / Fixtures

```python
@pytest.fixture
def small_tree():
    """A 20-node tree with known titles/summaries for deterministic testing."""
    return {
        "doc_name": "test-doc",
        "structure": [
            {"node_id": "0001", "title": "Root", "summary": "Root summary", "nodes": [
                {"node_id": "0002", "title": "Section A", "summary": "About topic A", "nodes": []},
                {"node_id": "0003", "title": "Section B", "summary": "About topic B", "nodes": [
                    {"node_id": "0004", "title": "Sub B1", "summary": "Detail on B1", "nodes": []},
                ]},
            ]},
        ],
    }

@pytest.fixture
def mock_embed_fn():
    """Deterministic embedding function for unit tests."""
    def embed(texts: list[str]) -> np.ndarray:
        rng = np.random.default_rng(seed=42)
        return rng.standard_normal((len(texts), 256)).astype(np.float32)
    return embed
```

---

## 5. Acceptance Criteria

- [ ] **AC1**: With the embedding signal disabled (`use_vec=False`),
  `HybridPageIndexSearch.search()` output is byte-identical to baseline.
- [ ] **AC2**: No new network/server dependency introduced for PageIndex
  retrieval.
- [ ] **AC3**: `NodeEmbeddingStore` is content-addressed and survives
  `reindex_node_ids`, `splice_subtree`, `delete_node` (covered by mutation
  tests).
- [ ] **AC4**: Per-tree matrix is materialized as contiguous `.npy`; rebuild
  triggered by existing dirty flag; re-embeds only changed nodes.
- [ ] **AC5**: MRL truncation goes through FEAT-150 `MatryoshkaConfig` path;
  switching model or dim invalidates cache via filename slug.
- [ ] **AC6**: Benchmark runs end-to-end on the compliance tree and emits
  results table + JSON + recommendation gate.
- [ ] **AC7**: Embedding walk (Phase B) is flag-gated; when on, acts as
  proposer — LLM walk / reranker remains arbiter.
- [ ] **AC8**: Compliance corpus is reproducible from `manifest.yaml` (pinned
  URLs + SHA-256). AICPA TSC sources are `redistributable: false`.
- [ ] **AC9**: `SentenceTransformerModel` accepts `backend` kwarg and
  correctly forwards to `SentenceTransformer` constructor.
- [ ] **AC10**: All unit tests pass; all integration tests pass.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# PageIndex modules
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # verified: __init__.py
from parrot.knowledge.pageindex.content_store import NodeContentStore  # verified: __init__.py
from parrot.knowledge.pageindex.store import JSONTreeStore  # verified: __init__.py
from parrot.knowledge.pageindex.retriever import PageIndexRetriever  # verified: __init__.py
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # verified: __init__.py
from parrot.knowledge.pageindex.tree_ops import reindex_node_ids, splice_subtree, delete_node  # verified: toolkit.py:36-40
from parrot.knowledge.pageindex.utils import find_node_by_id, get_nodes  # verified: hybrid_search.py:25

# Embedding modules
from parrot.embeddings.registry import EmbeddingRegistry  # verified: registry.py:51
from parrot.embeddings.catalog import EMBEDDING_MODELS, EmbeddingModelEntry  # verified: catalog.py
from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog  # verified: matryoshka.py
from parrot.embeddings.huggingface import SentenceTransformerModel  # verified: huggingface.py:111
from parrot.embeddings.base import EmbeddingModel  # verified: base.py

# Config
from parrot.conf import EMBEDDING_DEVICE, EMBEDDING_DEFAULT_MODEL, HUGGINGFACE_EMBEDDING_CACHE_DIR  # verified: conf.py:342-367
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py
class HybridPageIndexSearch:
    _RRF_K = 60  # module-level constant, line 38
    def __init__(self, tree, adapter, reranker=None, model=None,
                 default_bm25_k=20, content_loader=None)  # line 54
    def mark_dirty(self) -> None  # line 92
    def replace_tree(self, tree: dict) -> None  # line 96
    def _bm25_rank(self, query: str, top_k: int) -> list[str]  # line 140
    async def _llm_rank(self, query: str) -> list[str]  # line 162
    @staticmethod
    def _rrf_fuse(rankings: list[list[str]], k=60) -> list[tuple[str, float]]  # line 174
    async def search(self, query, top_k=10, use_bm25=True,
                     use_llm_walk=True, rerank=False) -> list[dict]  # line 185

# packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py
class NodeContentStore:
    def __init__(self, storage_dir, cache_size=256)  # line 54
    def save(self, tree_name, node_id, markdown) -> None  # line 116
    def load(self, tree_name, node_id) -> Optional[str]  # line 123
    def loader_for(self, tree_name) -> Callable[[str], Optional[str]]  # line 197

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):
    def __init__(self, adapter, storage_dir, reranker=None,
                 lightweight_model=None, model=None,
                 default_bm25_k=20, folder_concurrency=4,
                 content_cache_size=256, **kwargs)  # line 76
    def _search_for(self, tree_name) -> HybridPageIndexSearch  # line 126
    def _persist(self, tree_name) -> None  # line 141 — calls engine.mark_dirty()

# packages/ai-parrot/src/parrot/knowledge/pageindex/tree_ops.py
def reindex_node_ids(tree: dict) -> None  # line 16 — rewrites ALL node_ids
def splice_subtree(target, subtree, parent_node_id=None) -> list[str]  # line 45 — calls reindex_node_ids
def delete_node(tree, node_id) -> bool  # line 81 — calls reindex_node_ids

# packages/ai-parrot/src/parrot/knowledge/pageindex/retriever.py
class PageIndexRetriever:
    def __init__(self, tree, adapter, expert_knowledge=None,
                 model="gemini-3.1-flash-lite-preview")  # line 19
    async def search(self, query: str) -> TreeSearchResult  # line 38
    # search() does: json.dumps(self.structure, indent=2) at line 40

# packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py
class TreeSearchResult(BaseModel):
    thinking: str  # line 110
    node_list: list[str]  # line 111

# packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py
class SentenceTransformerModel(EmbeddingModel):
    def __init__(self, model_name, matryoshka=None, **kwargs)  # line 131
    async def encode(self, texts: List[str], **kwargs) -> np.ndarray  # line 383
    def _create_embedding(self, model_name=None, **kwargs) -> Any  # line 322
    # _create_embedding builds SentenceTransformer(model_name, **st_kwargs)
    # st_kwargs currently: device, cache_folder, [trust_remote_code]
    # Does NOT pass backend or file_name — GAP to fix

# packages/ai-parrot/src/parrot/embeddings/base.py
class EmbeddingModel(ABC):
    async def embed_documents(self, texts, batch_size=None) -> List[List[float]]  # line 169
    async def embed_query(self, text, as_nparray=False) -> Any  # line 188
    @abstractmethod
    async def encode(self, texts: List[str], **kwargs) -> np.ndarray  # line 226

# packages/ai-parrot/src/parrot/embeddings/registry.py
class EmbeddingRegistry:
    CacheKey = Tuple[str, str, Optional[int]]  # line 37 — (name, type, matryoshka_dim)
    @classmethod
    def instance(cls, max_models=None) -> "EmbeddingRegistry"  # line 100
    async def get_or_create(self, model_name, model_type="huggingface", **kwargs)  # line 218
    def get_or_create_sync(self, model_name, model_type="huggingface", **kwargs)  # line 345

# packages/ai-parrot/src/parrot/embeddings/catalog.py
class EmbeddingModelEntry(BaseModel):
    model: str; provider: Provider; name: str; dimension: int  # line 77-79
    matryoshka_dimensions: Optional[list[int]] = None  # line 96
    # NO backend field — must be added

# packages/ai-parrot/src/parrot/embeddings/matryoshka.py
class MatryoshkaConfig(BaseModel):
    enabled: bool = False  # line 47
    dimension: Optional[int] = None  # line 49
def validate_against_catalog(cfg, model_name) -> None  # line 75
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `NodeEmbeddingStore` | `NodeContentStore` | Sibling pattern (same storage_dir) | `content_store.py:37` |
| `NodeEmbeddingStore` | `HybridPageIndexSearch` | Constructor param + `_vec_rank()` | `hybrid_search.py:54` |
| `_vec_rank()` | `EmbeddingRegistry.get_or_create()` | Model loading for query embedding | `registry.py:218` |
| `_vec_rank()` | `_rrf_fuse()` | Third ranking list | `hybrid_search.py:174` |

…(truncated)…
