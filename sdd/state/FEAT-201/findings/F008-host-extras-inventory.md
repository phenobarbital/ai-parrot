---
id: F008
query_id: Q006
type: read
intent: Enumerate every extra in the host pyproject tied to embeddings/stores/rerankers.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 200
parent_id: null
depth: 0
---

# F008 — Host pyproject extras inventory: what moves vs stays

## Summary

The host pyproject has **8 extras** tied to embeddings/stores/rerankers
that will move (or have deps redistributed) to `ai-parrot-embeddings`.
Two of them — `embeddings` and `images` — are entangled (pgvector is
currently inside `images`, not its own extra). Core dependencies include
`faiss-cpu>=1.9.0` (line 98), so episodic-memory FAISS is in scope too.
Reranker dependencies (`sentence-transformers`, etc.) are NOT isolated —
they currently piggyback on `embeddings` and `agents`.

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 96-99
  symbol: core dep — `faiss-cpu`
  excerpt: |
    # Episodic memory default backend (FAISS) — required whenever an agent
    # enables episodic memory without an explicit pgvector DSN.
    "faiss-cpu>=1.9.0",

- path: `packages/ai-parrot/pyproject.toml`
  lines: 116-121
  symbol: `db` extra
  excerpt: |
    db = [
        "querysource>=4.1.11", "psycopg-binary==3.2.6", "jq==1.7.0",
        "asyncdb[bigquery,mongodb,arangodb,influxdb,boto3,sqlalchemy]>=2.12.0",
    ]

- path: `packages/ai-parrot/pyproject.toml`
  lines: 124-126
  symbol: `bigquery` extra
  excerpt: |
    bigquery = [
        "google-cloud-bigquery>=3.30.0",
    ]

- path: `packages/ai-parrot/pyproject.toml`
  lines: 172-174
  symbol: `arango` extra
  excerpt: |
    arango = [
        "python-arango-async==1.2.0",
    ]

- path: `packages/ai-parrot/pyproject.toml`
  lines: 287-308
  symbol: `embeddings` extra
  excerpt: |
    embeddings = [
        "sentence-transformers>=5.0.0",
        "faiss-cpu>=1.9.0",
        "rank_bm25==0.2.2",
        "sentencepiece==0.2.1",
        "tiktoken==0.9.0",
        "chromadb==0.6.3",
        "bm25s[full]==0.2.14",
        "simsimd>=4.3.1",
        "tokenizers>=0.20.0,<=0.22.2",
        "safetensors>=0.4.3",
        "einops>=0.7.0",
        "accelerate>=0.30.0",
        "peft>=0.10.0",
        "xformers>=0.0.27",
    ]

- path: `packages/ai-parrot/pyproject.toml`
  lines: 345-367
  symbol: `images` extra (contains pgvector!)
  excerpt: |
    images = [
        "torchvision>=0.23.0,<0.24",
        ...
        "pgvector==0.4.1",
        ...
    ]

- path: `packages/ai-parrot/pyproject.toml`
  lines: 408-411
  symbol: `milvus` extra
  excerpt: |
    milvus = [
        "pymilvus==2.4.8",
        "milvus-lite>=2.4.0",
    ]

- path: `packages/ai-parrot/pyproject.toml`
  lines: 413-415
  symbol: `chroma` extra
  excerpt: |
    chroma = [
        "chroma==0.2.0",
    ]

- path: `packages/ai-parrot/pyproject.toml`
  lines: 503-510
  symbol: meta-extras (`all`, `all-fast`)
  excerpt: |
    all = [
        "ai-parrot[agents,images,llms,integrations,db,bigquery,pdf,ocr,audio,finance,flowtask,scheduler,arango,reddit,embeddings,mcp,charts,docling]"
    ]
    all-fast = [
        "ai-parrot[agents-lite,llms,embeddings,integrations]"
    ]

## Notes

- **Migration tangle**: `pgvector==0.4.1` is buried in the `images`
  extra (line 352) because PgVector is used for image embeddings. The
  new `ai-parrot-embeddings[pgvector]` extra must carry pgvector, and
  the host's `images` extra must stop including it (or depend on
  `ai-parrot-embeddings[pgvector]`).
- **Core-dep gotcha**: `faiss-cpu>=1.9.0` is a **core dependency**
  (line 98), not behind any extra, because episodic memory needs it as
  a fallback. Moving the FAISS store backend out is fine, but the FAISS
  Python package itself stays in core deps.
- **Meta-extras to update**: `all` (line 505) and `all-fast` (line 509)
  reference `embeddings`. After the split, these must be rewritten to
  pull from `ai-parrot-embeddings[...]`.
- **No reranker extra exists today** — adding `[reranker-local]` and
  `[reranker-llm]` is a net-new isolation.
