---
type: Wiki Overview
title: FEAT-237 — PageIndex Embedding Router
id: doc:sdd-proposals-pageindex-embedding-router-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Rich brainstorm document proposing a dense embedding signal for PageIndex
---

---
id: FEAT-237
title: "PageIndex Embedding Router — dense semantic signal + CPU latency micro-benchmark"
slug: pageindex-embedding-router
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-15
  summary_oneline: "Add embedding-based dense ranking + beam walk router to PageIndex retrieval, with CPU benchmark on compliance corpus"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-237/
related: [FEAT-150]
created: 2026-06-15
updated: 2026-06-15
---

# FEAT-237 — PageIndex Embedding Router

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `file: sdd/proposals/pageindex-embedding-router.brainstorm.md`
> **Audit**: [`sdd/state/FEAT-237/`](../state/FEAT-237/)

---

## 0. Origin

Rich brainstorm document proposing a dense embedding signal for PageIndex
retrieval, in two complementary forms: (A) dense ranking fused into existing
RRF, and (B) embedding-guided beam walk replacing the LLM tree-walk. Includes
a compliance corpus deliverable (SOC 2 + HIPAA) and a CPU latency
micro-benchmark.

Full source: `sdd/proposals/pageindex-embedding-router.brainstorm.md`

**Initial signals**:
- Feature type: new capability (embedding signal) + benchmark infrastructure
- Scope: PageIndex retrieval path, embedding catalog/registry, new benchmark harness
- Related: FEAT-150 (Matryoshka truncation path)
- Phased delivery: A (low risk) then B (behind flag)

---

## 1. Synthesis Summary

PageIndex retrieval today combines BM25 lexical ranking and an LLM tree-walk
via Reciprocal Rank Fusion, but lacks a dense semantic signal — synonymy and
paraphrase queries depend entirely on the LLM walk, which serializes the entire
tree to JSON and scales poorly with tree size. This proposal adds a cheap,
exact, per-tree embedding signal: node `title+summary` texts are embedded into
a contiguous `(N, d)` numpy matrix via the existing `EmbeddingRegistry` and
FEAT-150 Matryoshka truncation path, cached in a content-addressed
`NodeEmbeddingStore` that mirrors the existing `NodeContentStore` sidecar
pattern. Phase A fuses dense cosine ranking as a third input to `_rrf_fuse`;
Phase B (flag-gated) replaces the full-tree LLM walk with O(depth) local
matmuls. All required embedding infrastructure (registry, Matryoshka, model
catalog) is production-proven. The only net-new code is the store sidecar,
the `_vec_rank` signal, the beam walk, and the benchmark harness.

---

## 2. Codebase Findings

> All entries grounded in `sdd/state/FEAT-237/findings/`. No fabricated paths.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | `HybridPageIndexSearch` | 43-291 | Add `_vec_rank` dense signal, fuse into `_rrf_fuse`, wire dirty flag | F003, F008 |
| 2 | `packages/ai-parrot/src/parrot/knowledge/pageindex/retriever.py` | `PageIndexRetriever.search` | 38-79 | Phase B: beam walk pre-filters/replaces full-tree JSON serialization | F008 |
| 3 | `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | `PageIndexToolkit._search_for` | 126-139 | Construct + inject NodeEmbeddingStore into search engine | F010 |
| 4 | `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` | `NodeContentStore` | 37-213 | Sibling pattern for NodeEmbeddingStore (LRU cache, loader_for closure) | F010 |
| 5 | `packages/ai-parrot/src/parrot/knowledge/pageindex/tree_ops.py` | `reindex_node_ids` | 16-104 | Confirms content-addressing requirement: all node_ids rewritten on mutation | F007 |
| 6 | `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py` | `SentenceTransformerModel` | 111-393 | Add `backend` kwarg (onnx/openvino) to `_create_embedding`; `encode()` returns `np.ndarray` | F001, F002 |
| 7 | `packages/ai-parrot/src/parrot/embeddings/catalog.py` | `EmbeddingModelEntry` | 36-1352 | Add `backend` field to schema; add Qwen3-Embedding-0.6B + benchmark candidate entries | F005 |
| 8 | `packages/ai-parrot/src/parrot/embeddings/registry.py` | `EmbeddingRegistry` | 51-447 | Reuse `get_or_create` path; `backend` kwarg flows through `_build_model **kwargs` | F006 |
| 9 | `packages/ai-parrot/src/parrot/embeddings/matryoshka.py` | `MatryoshkaConfig` | 1-128 | Reuse FEAT-150 truncation for dim reduction (e.g. 1024 to 256) | F009 |

### 2.2 Constraints Discovered

- **`encode()` returns `np.ndarray`; `embed_documents()` returns `List[List[float]]`.**
  For the per-tree matmul use case, use `encode()` directly to avoid
  list-to-array round-trips. The `_apply_matryoshka` truncation works on both
  numpy arrays and lists.
  *Evidence*: F001

- **`_create_embedding()` does not forward a `backend` kwarg.**
  `sentence-transformers>=5.0.0` supports `backend="onnx"|"openvino"` in the
  `SentenceTransformer` constructor, but the current wrapper only passes
  `device`, `cache_folder`, and optionally `trust_remote_code`. Adding backend
  support is a targeted change (accept param, forward to constructor).
  *Evidence*: F002

- **Node IDs are rewritten on every tree mutation.**
  `reindex_node_ids` is called by both `splice_subtree` and `delete_node`.
  The embedding cache MUST NOT key on `node_id`. Content-addressing via
  `sha1(model_id + "\x00" + title + "\x00" + summary)` is correct.
  *Evidence*: F007

- **`mark_dirty()` is the public invalidation method.**
  Used by `set_content_loader()` and `replace_tree()`. The new embedding
  signal should call `mark_dirty()` on the same trigger points.
  *Evidence*: F003

- **FEAT-150 Matryoshka path is production-proven.**
  `MatryoshkaConfig` + `validate_against_catalog()` + `_apply_matryoshka()`
  slice+L2-renorm. Registry cache key includes dim as 3rd element. No new
  truncation mechanism needed.
  *Evidence*: F009

- **`EmbeddingModelEntry` schema lacks a `backend` field.**
  Must be added (optional `Literal["torch", "onnx", "openvino"]` defaulting to
  `None`) to support ONNX/OpenVINO model entries in the catalog.
  *Evidence*: F005

- **`multilingual-e5-small` is NOT in the catalog** (only e5-base and
  e5-large). The brainstorm claims it's "already used by the intent router" —
  either the intent router uses e5-base, or e5-small needs a new catalog entry.
  *Evidence*: F005

### 2.3 Recent History

| Commits (last 3 months) | Summary |
|---|---|
| `53cceaa64` | re-organize imports |
| `a9f456d26` | feat(knowledge): add PageIndexLoader and GraphIndexLoader |
| `732ea8e65` | refactor(move-pageindex-kb): per-module logger names |
| `d90af5567` | feat(move-pageindex-kb): TASK-1328 — Move pageindex package directory |

No recent changes to `hybrid_search.py` or `retriever.py` logic. The module was
recently reorganized but its search/retrieval code is stable.

---

## 3. Probable Scope

### What's New

- **`embedding_store.py`** — `NodeEmbeddingStore`: two-tier content-addressed
  cache (global hash-keyed tier + per-tree materialized `(N, d)` `.npy` matrix).
  Mirrors `NodeContentStore` sidecar pattern.
- **`vector_walk.py`** — `embedding_tree_walk()` beam search +
  `FlatMatrixSearch` brute-force cosine over child submatrices. Phase B,
  flag-gated.
- **`benchmarks/pageindex_embedding_latency/`** — CPU latency micro-benchmark
  harness (models x backends x dims), metrics, report generator.
- **`corpus/compliance_soc2_hipaa/`** — Manifest-driven compliance corpus
  (SOC 2 + HIPAA, public-domain NIST + internal-only AICPA TSC).

### What Changes

- **`hybrid_search.py::HybridPageIndexSearch`** — Add `_vec_rank()` dense
  ranking method, pass as third list to `_rrf_fuse()`, wire dirty flag for
  embedding matrix rebuild. *Evidence*: F003
- **`retriever.py::PageIndexRetriever`** — Phase B: beam walk pre-filters or
  replaces LLM walk. *Evidence*: F008
- **`toolkit.py::PageIndexToolkit._search_for`** — Construct + inject
  `NodeEmbeddingStore` into the search engine. *Evidence*: F010
- **`huggingface.py::SentenceTransformerModel._create_embedding`** — Accept +
  forward `backend` kwarg to `SentenceTransformer()`. *Evidence*: F002
- **`catalog.py::EmbeddingModelEntry`** — Add optional `backend` field; add
  Qwen3-Embedding-0.6B, multilingual-e5-small, potion-multilingual entries.
  *Evidence*: F005

### What's Untouched (Non-Goals)

- Chunk-level conversational RAG (`PgVectorStore` / FAISS) — untouched.
- Global ANN index — not introduced; PageIndex stays vectorless at corpus level.
- `AbstractReranker` contract and RRF constant — unchanged.
- GPU-mandatory paths — CPU is the target; GPU opportunistic.
- The LLM walk itself — Phase A is purely additive; Phase B gates behind flag.

### Patterns to Follow

- **`NodeContentStore` sidecar** — LRU-cached per-node store with
  `loader_for()` closure. *Evidence*: F010
- **`EpisodeEmbeddingProvider`** — lazy model load + `asyncio.to_thread`
  encode pattern. *Evidence*: F001 (cross-reference)
- **`HybridBM25Strategy._cosine_sim`** — score normalization conventions
  (use numpy matmul instead of per-pair Python cosine). *Evidence*: F001

### Integration Risks

- **Model download on first use.** Embedding models are downloaded from
  HuggingFace on first access. In airgapped or restricted network envs, the
  model must be pre-cached in `HUGGINGFACE_EMBEDDING_CACHE_DIR`. Mitigation:
  document cache-warming in the benchmark README.
- **Memory footprint.** A 1000-node tree at 256d float32 = ~1 MB. At 1024d =
  ~4 MB. For large multi-tree deployments, the per-tree matrix memory adds up.
  Mitigation: MRL truncation to 256d (~2-3% quality loss); mmap for read-only
  access.
- **Dirty rebuild cost.** Re-embedding all nodes on content change is O(N)
  model calls. Mitigation: content-addressed cache means only changed nodes
  are re-embedded; unchanged nodes hit the global cache.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `encode()` returns `np.ndarray` — use for matmul | F001 | **high** | direct read of method signature and return type |
| C2 | `sentence-transformers>=5.0` supports ONNX/OpenVINO backends | F002 | **high** | version confirmed in pyproject.toml; feature documented in ST 3.2+ changelog |
| C3 | `_create_embedding()` does NOT yet forward `backend` kwarg | F002 | **high** | direct read of method body |
| C4 | `mark_dirty()` is the public dirty-flag method | F003 | **high** | direct read |
| C5 | Leaf body via NodeContentStore sidecar or inline `text` | F004 | **high** | direct read of both access paths |
| C6 | `EmbeddingModelEntry` lacks `backend` field | F005 | **high** | direct read of Pydantic schema |
| C7 | Node IDs rewritten on every mutation; content-address required | F007 | **high** | direct read of reindex_node_ids call sites |
| C8 | LLM walk serializes full tree to JSON | F008 | **high** | direct read of `json.dumps(self.structure)` |
| C9 | FEAT-150 Matryoshka path production-proven | F009 | **high** | direct read + test coverage confirmed |
| C10 | NodeContentStore is the template for NodeEmbeddingStore | F010 | **high** | direct read of class and wiring |
| C11 | Phase B beam walk can address scaling | F008 | **medium** | inferred from LLM walk limitations; beam walk not yet validated |

Distribution: **10** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Default model selection strategy** — *Resolved*: Benchmark-first.
  Add both Qwen3-Embedding-0.6B and Octen-Embedding-0.6B to the benchmark
  matrix; pick the winner based on CPU latency + recall@k results.
  *Resolves claims*: C6 (catalog entries)

- [x] **Compliance corpus licensing scope** — *Resolved*: Internal + NIST.
  Include AICPA TSC sources with `redistributable: false` for richer SOC 2
  grounding (internal-only, never published). Public-domain NIST sources are
  fully redistributable.

- [x] **Embedding text target** — *Resolved*: `title + summary` only.
  Consistent across all nodes, fast to compute, matches existing BM25 corpus
  text composition. No leaf-body inclusion at this stage.

### Unresolved (defer to spec / implementation)

- [ ] **Walk integration mode (Q1 from brainstorm)** — Does the embedding beam
  walk *replace* the LLM walk, run as a *pre-filter*, or only *fuse* via RRF?
  Phase B decision; affects the router/arbiter boundary.
  *Owner*: spec phase

- [ ] **Global cache substrate (Q2 from brainstorm)** — Single `.npz`,
  prefix-sharded `.npy`, or sqlite/LMDB? Concurrency behavior under
  `folder_concurrency` parallel ingests.
  *Owner*: spec phase

- [ ] **Recall ground truth (Q3 from brainstorm)** — LLM-walk-as-oracle, large
  reference embedding model, or hand-labeled query-to-node set?
  *Owner*: benchmark design

- [ ] **License gate (Q4 from brainstorm)** — Is Gemma license acceptable for
  "full open-source" stance, or hard-restrict to Apache/MIT?
  *Owner*: policy decision

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-237`** — All brainstorm codebase anchors are verified (high
confidence). Architecture options are well-grounded. Phase A is low-risk and
well-scoped. The spec should formalize the phased approach (A first, B behind
flag) and resolve the 4 remaining open questions from the brainstorm.

### Alternatives

- **`/sdd-brainstorm FEAT-237`** — If you want to explore alternative
  architectures beyond the recommended phased C (e.g., skip Phase A entirely
  and go straight to beam walk).
- **`/sdd-task FEAT-237`** — Only if the spec is considered trivially derivable
  from this proposal + the brainstorm (the scope is non-trivial, so spec is
  recommended).
- **Manual review** — Research was complete (not truncated), but the 4
  unresolved questions are architectural choices best made in the spec phase.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-237/state.json` |
| Source (raw) | `sdd/state/FEAT-237/source.md` |
| Research plan | `sdd/state/FEAT-237/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-237/findings/F001.md` through `F010.md` |
| Synthesis (JSON) | `sdd/state/FEAT-237/synthesis.json` |

**Budget consumed**:
- Files read: 12 / 40
- Grep calls: 10 / 25
- Git calls: 1 / 10
- Truncated: **no**

**Mode determination**: `auto` -> resolved to `enrichment` (rich brainstorm
with detailed codebase anchors requiring verification, not a bug investigation).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | inline (enrichment mode) |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | jlara@trocglobal.com |
