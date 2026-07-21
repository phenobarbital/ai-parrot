---
type: Wiki Overview
title: PageIndex Embedding Router + CPU Latency Micro-Benchmark
id: doc:sdd-proposals-pageindex-embedding-router-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'PageIndex retrieval today combines two signals (`HybridPageIndexSearch`):
  BM25 lexical'
---

---
feature: pageindex-embedding-router
type: brainstorm
base_branch: dev
proposed_feat: FEAT-199   # ⚠️ VERIFY — last confirmed was FEAT-198; confirm next free number against the tracker
status: brainstorm
related: [FEAT-150]        # Matryoshka truncation path in the embedding registry
# The compliance corpus (§7.A) doubles as the benchmark fixture AND the first
# knowledge bank for the ComplianceEvidenceAgent (SOC 2 = first framework target).
---

# PageIndex Embedding Router + CPU Latency Micro-Benchmark

## 1. Problem statement

PageIndex retrieval today combines two signals (`HybridPageIndexSearch`): BM25 lexical
ranking over flattened node text, and an LLM tree-walk (`PageIndexRetriever`) that
**serializes the entire tree structure to JSON** and asks the model to return relevant
`node_id`s, fused via Reciprocal Rank Fusion.

Two gaps follow from this:

1. **No dense semantic signal.** Synonymy / paraphrase queries that BM25 misses depend
   entirely on the LLM walk. There is no embedding-based ranking anywhere in the
   PageIndex path.
2. **The LLM walk does not scale.** One large LLM call per query, with a prompt that
   grows with the tree. As trees grow the JSON approaches context limits and reasoning
   quality degrades; latency and token cost are unbounded in tree size.

This brainstorm proposes adding a **cheap, exact, vectorless-at-corpus-level** embedding
signal to PageIndex, in two complementary forms:

- a **dense ranking** fused into the existing RRF, and
- an **embedding-guided local tree-walk** (beam search over per-node summary embeddings)
  that proposes candidate branches with O(depth) tiny matmuls, so the LLM is consulted
  only at ambiguous branch points (or not at all).

Node embeddings are **content-addressed and cached** (a single contiguous `(N, d)` matrix
per tree, mmap-loaded for matmul), and the embedding model is an **open-source, CPU-first,
ONNX/OpenVINO-capable** model selected by a **CPU latency micro-benchmark**. The benchmark
runs on a **real tree built from authoritative SOC 2 + HIPAA compliance documents** — a
corpus that is itself a deliverable (§7.A): it serves both as the benchmark fixture and as
the first production knowledge bank for the `ComplianceEvidenceAgent`.

This keeps the original PageIndex thesis intact: the tree remains the source of truth,
the corpus has **no global ANN index**, and embeddings act as a *local router*, not a
monolithic vector store.

## 2. Non-goals

- **Not** replacing chunk-level conversational RAG (`PgVectorStore` / FAISS stays for that).
- **Not** introducing a global ANN index or a vector-DB server for PageIndex. The tree
  shards the corpus into small child sets; brute-force matmul over those sets is exact
  and faster than ANN in this regime.
- **Not** GPU-mandatory. CPU is the target; GPU is an opportunistic speedup.
- **Not** changing the reranker contract (`AbstractReranker`) or the RRF constant.
- **Not** removing the LLM walk. Per the platform invariant, the deterministic matmul
  *proposes*; the probabilistic LLM *decides* (at ambiguity / for the final cut).

## 3. Constraints & invariants

- **Deterministic proposes, probabilistic decides.** The embedding walk is a router that
  emits candidate `node_id`s. The LLM walk and/or reranker remain the arbiter.
- **Vectorless at corpus level.** No new network dependency; no global index. Per-tree
  matrices only, materialized from a content-addressed cache.
- **Additive & flag-gated.** With the embedding signal disabled, `HybridPageIndexSearch`
  behavior must be byte-identical to today.
- **Reuse existing seams:** the `EmbeddingRegistry` cache, the `EMBEDDING_MODELS` catalog
  (`EmbeddingModelEntry`), and the FEAT-150 Matryoshka truncation path. No parallel
  embedding stack.
- **Survives tree mutation.** `reindex_node_ids` rewrites `node_id`s; the embedding cache
  MUST NOT key on `node_id`. Content-address it (hash of model + title + summary).
- **License posture.** Prefer OSI-permissive (Apache-2.0 / MIT). Gemma-licensed models are
  allowed only if the "full open-source" stance is relaxed (open question Q4).
- **Dirty-flag rebuild.** Reuse the lazy-rebuild pattern already used for the BM25 index
  (`self._dirty` / `mark_dirty`) rather than inventing a new invalidation mechanism.

## 4. Codebase Contract

Grep anchors (symbol strings, never line numbers). `⚠️ VERIFY` marks paths/behaviors not
yet confirmed by reading.

### Files this touches

| File | Anchor | Role |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | `class HybridPageIndexSearch` | Add `_vec_rank`, fuse into RRF, wire dirty flag |
| ″ | `def _bm25_rank` / `async def _llm_rank` / `def _rrf_fuse` | Existing ranking signals; new signal mirrors these |
| ″ | `def set_content_loader` | Reference for dirty-marking on swap |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/retriever.py` | `class PageIndexRetriever` / `async def search` | LLM-walk; embedding walk pre-filters or replaces it (Q1) |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | `class PageIndexToolkit` / `def _search_for` | Constructs the search engine; wire `NodeEmbeddingStore` |
| ″ | `def _strip_keys_in_place` | Confirms vectors MUST stay out of the lean ToC JSON |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py` | `class JSONTreeStore` | Source of the "real tree" for the benchmark |
| ″ | `class NodeContentStore` | Sibling pattern for the new `NodeEmbeddingStore` sidecar |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/tree_ops.py` | `def reindex_node_ids` / `def splice_subtree` / `def delete_node` | Why the cache is content-addressed, not id-keyed |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py` | `def find_node_by_id` / `def get_nodes` | Node lookup / tree flatten helpers |
| `packages/ai-parrot/src/parrot/embeddings/catalog.py` | `EMBEDDING_MODELS` / `class EmbeddingModelEntry` | Add candidate model entries + `backend` field |
| `packages/ai-parrot/src/parrot/embeddings/` | `class EmbeddingRegistry` / `get_or_create_sync` | Reuse cache; `backend` flows through `**kwargs` |
| ″ | `SentenceTransformerModel` ⚠️ VERIFY exact module path | Add `backend="onnx"|"openvino"` kwarg + `file_name` |
| `packages/ai-parrot/src/parrot/conf.py` | `EMBEDDING_DEVICE` / `EMBEDDING_DEFAULT_MODEL` / `HUGGINGFACE_EMBEDDING_CACHE_DIR` | CPU device + cache dir already configured |

### Prior art to mirror (do NOT duplicate)

- `packages/ai-parrot/src/parrot/memory/episodic/recall.py` → `class HybridBM25Strategy`
  already fuses BM25 + semantic cosine (`def _cosine_sim`, pure-Python). The PageIndex
  fusion should match its score-normalization conventions, but use **numpy matmul** rather
  than the per-pair Python cosine.
- `packages/ai-parrot/src/parrot/memory/episodic/embedding.py` → `class EpisodeEmbeddingProvider`
  is the reference for lazy model load + `asyncio.to_thread` encode. ⚠️ VERIFY the exact
  embed method name/return type used by the registry models (`embed_documents` vs `embed`
  vs `encode`; `list[list[float]]` vs `np.ndarray`) before writing the adapter.

### Node schema (observed, treat as authoritative pending re-read)

Nodes carry `node_id`, `title`, `summary` (or `prefix_summary`), and children under
`nodes`. Tree root dict is `{doc_name, structure: [...]}`. ⚠️ VERIFY leaf-node body access
(inline `text` vs `content_ref` via `NodeContentStore` / `pageindex://` scheme).

## 5. Architecture options

### 5.1 Where the embedding signal plugs in

| Option | Description | Pros | Cons |
|---|---|---|---|
| **A. Dense-as-third-RRF-input** | Embed `title+summary` per node into a per-tree matrix; one matmul → dense ranking; add as a third list to `_rrf_fuse`. LLM walk untouched. | Smallest change; purely additive; closes synonymy gap; no LLM-walk risk | Still pays full LLM-walk cost; no scaling win |
| **B. Embedding-guided beam walk** | Beam search down the tree using local `(n_children, d) @ (d,)` matmuls; LLM never reads the whole ToC. | Cuts LLM tokens/latency drastically; scales with tree depth not size; "small note directories" realized | Misses nodes when summary embedding ≠ content; needs fusion/LLM check to be safe |
| **C. B as router + A as fusion + LLM as arbiter** *(recommended, phased)* | Beam walk proposes candidates (B); dense ranking fuses via RRF (A); LLM invoked only at ambiguous branches / for final cut. | Best latency/quality balance; matches "deterministic proposes, probabilistic decides"; degrades gracefully | Most surface area; ship in phases (A → B) |

**Recommendation:** target **C**, land **A** first (low risk, immediate recall win), then
**B** behind a flag once the benchmark validates a model.

### 5.2 Where to cache node embeddings

| Option | Pros | Cons |
|---|---|---|
| Inline vectors in the tree JSON | Single artifact | **Rejected.** Bloats the lean ToC (`_strip_keys_in_place` exists precisely to avoid this); ~10 KB/node as JSON text; slow parse; no contiguous matmul buffer |
| Per-node `.npy` sidecars (like markdown sidecars) | Mirrors `NodeContentStore`; granular | N small reads to assemble a matrix; loses contiguity |
| **Two-tier: content-addressed global cache + per-tree materialized `(N,d)` `.npy`** *(recommended)* | Dedup + memoization across re-ingests; **survives `reindex_node_ids`**; contiguous mmap matrix for BLAS; cheap dirty-rebuild (unchanged nodes hit cache) | Two artifacts to manage; needs `model_id`/`dim` in the filename for clean invalidation |

Key (global tier): `sha1(model_id + "\x00" + title + "\x00" + summary)`. Per-tree artifact:
ordered `node_id → row` map + materialized matrix, rebuilt on `mark_dirty`. Snappy buys
~5–10% on float32 (high entropy), so raw `.npy` mmap beats arrow/parquet here on simplicity
and speed.

### 5.3 Candidate embedding models (final pick deferred to the benchmark)

| Model | Params | Dim (MRL) | Multilingual | License | Backend | Role |
|---|---|---|---|---|---|---|
| **Qwen3-Embedding-0.6B** | 0.6B | 32–1024 | 100+ | Apache-2.0 | ONNX int8 / OpenVINO | **Default** — quality node embeddings + RRF fusion; family already proven (`Octen-Embedding-0.6B` derivative in catalog) |
| **EmbeddingGemma-300M** | 0.3B | 768→512→256→128 | 100+ | Gemma (⚠️ not OSI; Q4) | ONNX | Lighter on-device option (~½ params); on-device-tuned |
| **multilingual-e5-small** | ~118M | 384 | yes | MIT | torch / ONNX | Proven featherweight baseline (already used by the intent router) |
| **potion-multilingual (model2vec / static)** | n/a (lookup) | tunable | yes | MIT | n/a (no forward pass) | **Router-only** for the beam walk; ~100× cheaper on CPU; quality covered by RRF + LLM check |

MRL note: truncating to 256d (~2–3% quality loss) shrinks the matrix and matmul 3–4×,
which is well within tolerance for a routing signal. Use the **FEAT-150** truncation path,
not a new mechanism.

### 5.4 Backend

Ship via the existing `SentenceTransformerModel` with a new `backend` kwarg
(`torch`/`onnx`/`openvino`) + optional quantized `file_name`. ⚠️ VERIFY the installed
`sentence-transformers` version supports the `onnx`/`openvino` backends (3.2+) before
committing to that path; otherwise a thin `optimum`-based provider is the fallback.

## 6. Module layout

```
packages/ai-parrot/src/parrot/knowledge/pageindex/
  embedding_store.py        # NEW: NodeEmbeddingStore (two-tier, content-addressed)
  vector_walk.py            # NEW: embedding_tree_walk() beam search + FlatMatrixSearch
  hybrid_search.py          # EDIT: add _vec_rank, fuse into RRF, dirty wiring
  retriever.py              # EDIT (phase B): pre-filter / replace LLM walk with walk output
  toolkit.py                # EDIT: construct + inject NodeEmbeddingStore into the engine

packages/ai-parrot/src/parrot/embeddings/
  catalog.py                # EDIT: add Qwen3-0.6B, EmbeddingGemma-300M, potion entries; add `backend`
  <st model module>         # EDIT: backend kwarg (onnx/openvino) ⚠️ VERIFY path

benchmarks/pageindex_embedding_latency/   # NEW — deliverable artifact §7.B
  __init__.py
  harness.py                # matrix runner (models × backends × dims)
  metrics.py                # latency percentiles, RSS, recall@k
  report.py                 # emit markdown + JSON results table
  conftest_tree.py          # load the §7.A compliance tree as the fixture
  README.md

corpus/compliance_soc2_hipaa/             # NEW — deliverable artifact §7.A
  manifest.yaml             # source URLs, publisher, license, redistributable, sha256
  fetch.py                  # manifest-driven downloader (runs in AI-Parrot env)
  build_tree.py             # orchestrates PageIndexToolkit.import_pdf / import_folder
  README.md                 # licensing notes; AICPA TSC = internal-only
  # outputs (gitignored): <storage_dir>/soc2_hipaa.json + soc2_hipaa/ sidecars
```

## 7. Deliverable artifacts

### 7.A — Compliance knowledge corpus (real PageIndex tree)

**Goal:** build a real, reproducible PageIndex tree from authoritative SOC 2 + HIPAA
compliance documents. This single artifact serves two purposes: the benchmark fixture
(§7.B, resolving V6) and the first knowledge bank consumed by the `ComplianceEvidenceAgent`.

**Pipeline (no new ingestion code — reuse `PageIndexToolkit`):**
manifest-driven download → `PageIndexToolkit.import_pdf` / `import_folder` (Two-Step CoT
ingest, TOC detection, per-node summaries) → lean ToC JSON + per-node markdown sidecars.
The acquisition step is a small manifest-driven fetcher; everything downstream is the
existing toolkit path. Pin source URLs + SHA-256 checksums so the tree is reproducible.

**License posture (decides what is ingestible vs. redistributable):**
- **HIPAA backbone — public domain (U.S. Government works).** Freely ingestible *and*
  redistributable.
- **SOC 2 Trust Services Criteria — © AICPA.** Free to download, but redistribution is
  restricted (the TSC PDF requires written permission to copy and embeds COSO 2013
  elements). Ingest for **internal LLM grounding only**; mark `redistributable: false`; do
  **not** ship a public tree containing verbatim TSC text. For any shippable/public
  artifact, use the public-domain NIST mappings (800-53 / CSF) as the SOC 2 control
  backbone instead. This is open question Q7.

**Source manifest (verified URLs):**

| Doc | Publisher | License | Redistributable | URL |
|---|---|---|---|---|
| NIST SP 800-66r2 — Implementing the HIPAA Security Rule | NIST | Public domain | ✅ | `nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-66r2.pdf` |
| HIPAA Security Series (Policies/Procedures & Documentation) | HHS/OCR | Public domain | ✅ | `www.hhs.gov/sites/default/files/ocr/privacy/hipaa/administrative/securityrule/pprequirements.pdf` |
| Summary of the HIPAA Security Rule | HHS/OCR | Public domain | ✅ | `www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html` |
| Security Rule Guidance Material (index → more PDFs) | HHS/OCR | Public domain | ✅ | `www.hhs.gov/hipaa/for-professionals/security/guidance/index.html` |
| NIST SP 800-53 Rev. 5 (control backbone, TSC mapping) | NIST | Public domain | ✅ | `nvlpubs.nist.gov` (SP 800-53r5) |
| NIST CSF 2.0 | NIST | Public domain | ✅ | `nvlpubs.nist.gov` (NIST.CSWP.29) |
| 2017 Trust Services Criteria (rev. PoF 2022) | AICPA | © AICPA | ❌ internal only | `www.aicpa-cima.com/resources/download/2017-trust-services-criteria-with-revised-points-of-focus-2022` |
| 2018 SOC 2 Description Criteria (2022 guidance) | AICPA | © AICPA | ❌ internal only | `www.aicpa-cima.com/resources/download/get-description-criteria-for-your-organizations-soc-2-r-report` |

⚠️ Acquisition runs in the AI-Parrot environment (the sandbox network does not allow
`nist.gov` / `hhs.gov` / `aicpa-cima.com`). The manifest fetcher belongs in the corpus
artifact below.

### 7.B — CPU latency micro-benchmark

**Goal:** pick `model × backend × dim` by measuring CPU latency, memory, and retrieval
quality **on the §7.A compliance tree** — a real, multi-document corpus, not a synthetic one.

### 7.B.1 Inputs
- The §7.A compliance tree loaded via `JSONTreeStore.load(<tree_name>)` plus its
  `NodeContentStore` sidecars (report node count, depth, and branching factor in the
  results header).
- A query set: (a) hand-written compliance questions with known target sections
  (e.g. "what are the administrative safeguards under the HIPAA Security Rule?",
  "which TSC is mandatory for every SOC 2 report?"), else (b) the LLM walk's output as a
  proxy oracle (Q3).

### 7.B.2 Test matrix
- **Models:** Qwen3-Embedding-0.6B, EmbeddingGemma-300M, multilingual-e5-small,
  potion-multilingual.
- **Backends:** `torch-cpu`, `onnx-int8`, `openvino-int8` (skip combos a model can't run).
- **Dims (MRL):** full, 512, 256 (where supported).

### 7.B.3 Metrics
- **Ingest:** node-embedding throughput (nodes/s); per-tree matrix build time (cold vs
  warm cache hit).
- **Query path:** single-vector query encode latency p50/p95; full beam-walk latency
  p50/p95 (encode + O(depth) matmuls); flat-matmul latency p50/p95 for the dense-RRF path.
- **Memory:** peak RSS; resident matrix size at each dim.
- **Quality:** recall@k of the embedding-walk candidate set vs the oracle; nDCG of the
  RRF-fused result vs labels if available.

### 7.B.4 Methodology
- Pin BLAS/OMP threads (`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`) and report the value;
  run a fixed thread count so numbers are comparable.
- Warmup runs discarded; N≥30 repeats per cell; report median + p95, not mean.
- Report hardware (CPU model, cores, RAM) and library versions in the results header.
- Separate **cold** (model load + matrix build) from **warm** (cache hit) timings.
- Use `asyncio.to_thread` for encode, matching production execution.

### 7.B.5 Output
- A markdown results table + a machine-readable JSON, written by `report.py`.
- A one-line recommendation gate: the default model/backend/dim that meets a latency
  budget (to be set in `/sdd-spec`) at acceptable recall.

## 8. Acceptance criteria (for the eventual spec/implementation)

1. With the embedding signal disabled, `HybridPageIndexSearch` output is unchanged.
2. No new network/server dependency is introduced for PageIndex retrieval.
3. `NodeEmbeddingStore` is content-addressed and **survives `reindex_node_ids`,
   `splice_subtree`, `delete_node`** (covered by a mutation test).
4. Per-tree matrix is materialized as a contiguous mmap `.npy`; rebuild is triggered by
   the existing dirty flag and re-embeds only changed nodes.
5. MRL truncation goes through the FEAT-150 path; switching model or dim invalidates the
   cache via the filename slug.
6. The benchmark runs end-to-end on the §7.A compliance tree and emits the results table +
   JSON + recommendation gate.
7. Embedding walk is flag-gated and, when on, acts as a *proposer* — the LLM walk /
   reranker remains the final arbiter.
8. The compliance corpus is **reproducible** from `manifest.yaml` (pinned URLs + SHA-256)
   and respects per-source licensing: AICPA TSC sources are `redistributable: false` and
   the built tree containing verbatim TSC text is never published.

## 9. Verification checklist (mechanical, run before `/sdd-spec`)

- **V1** Confirm the registry model embed method/return type (`embed_documents` vs
  `encode`; `list[list[float]]` vs `np.ndarray`) → drives the matmul adapter shape.
- **V2** Confirm `SentenceTransformerModel` module path and that the installed
  `sentence-transformers` supports `backend="onnx"|"openvino"`.
- **V3** Confirm the public dirty-mark method name on `HybridPageIndexSearch`
  (`mark_dirty` vs direct `self._dirty`).
- **V4** Confirm leaf-node body access path (`text` inline vs `content_ref`/`NodeContentStore`).
- **V5** Confirm next free FEAT number (proposed FEAT-199).
- **V6** Build the §7.A compliance corpus and confirm its tree stats (node count, depth,
  branching factor) — this *is* the benchmark fixture.
- **V7** Confirm AICPA TSC download access and licensing handling in the AI-Parrot env;
  confirm the fetcher can reach `nist.gov` / `hhs.gov` / `aicpa-cima.com` there.

## 10. Open questions (resolve in discussion before `/sdd-spec`)

1. **Walk integration mode:** does the embedding beam walk *replace* the LLM walk, run as a
   *pre-filter* feeding a smaller subtree to the LLM, or only *fuse* via RRF? (Phase-B
   decision; affects the router/arbiter boundary.)
2. **Global cache substrate:** single `.npz`, prefix-sharded `.npy` files, or
   sqlite/LMDB — and how does it behave under `folder_concurrency` concurrent ingests?
3. **Recall ground truth:** LLM-walk-as-oracle, a large reference embedding model, or a
   hand-labeled query→node set?
4. **License gate:** is the Gemma license acceptable for the "full open-source" stance, or
   do we hard-restrict to Apache/MIT (which drops EmbeddingGemma)?
5. **Embedding target text:** `title+summary` only, or fold in `prefix_summary` / first-N
   chars of leaf body for better leaf discrimination?
6. **Backend default for packaging:** ship `torch` and let the benchmark pick per-deploy,
   or commit to ONNX/OpenVINO as the shipped default?
7. **Corpus licensing scope:** is the SOC 2 knowledge bank **internal-only** (allows
   ingesting AICPA TSC verbatim for grounding), or must it be **shippable/public** (drop
   AICPA verbatim text, ground SOC 2 controls on the public-domain NIST 800-53 / CSF
   mappings only)? This decides whether the AICPA sources go in the manifest at all.
