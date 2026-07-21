---
type: Wiki Overview
title: Matryoshka Embedding Truncation
id: doc:docs-matryoshka-embeddings-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Matryoshka Representation Learning (MRL) trains embedding models so that
  a
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
---

# Matryoshka Embedding Truncation

> Feature: FEAT-150 — available from the `dev` branch onwards.

## What and why

Matryoshka Representation Learning (MRL) trains embedding models so that a
vector of dimension `D` encodes strictly more information than any prefix of
length `d < D` of the same vector — yet the shorter prefix is still a
high-quality embedding on its own.

For operators this means: ingest once at 512 dims instead of 768 dims, store
vectors that are ~33 % smaller, run HNSW queries ~33 % faster — with only a
small quality trade-off.  On CPU-only deployments or memory-constrained
databases the trade-off is usually worth it.

---

## Configuration

Add a `matryoshka` sub-object inside `vector_store_config.embedding_model`:

```yaml
# Example: bot vector_store_config (YAML / Python dict equivalent)
vector_store_config:
  name: postgres
  table: my_bot_vectors
  schema: public
  dimension: 512          # MUST match matryoshka.dimension exactly
  embedding_model:
    model_name: "nomic-ai/nomic-embed-text-v1.5"
    model_type: huggingface
    matryoshka:
      enabled: true
      dimension: 512      # must be in the model's allowed list (see table below)
```

The two `dimension` values (`vector_store_config.dimension` and
`embedding_model.matryoshka.dimension`) **must be equal**.  If they differ,
`_provision_vector_store` raises a `ConfigError` at configure time before any
pgvector table is created.

---

## Supported models

| HuggingFace model ID | Allowed `matryoshka.dimension` values |
|---|---|
| `nomic-ai/nomic-embed-text-v1.5` | 64, 128, 256, 512, **768** (native) |
| `mixedbread-ai/mxbai-embed-large-v1` | 128, 256, 512, 768, **1024** (native) |
| `google/embeddinggemma-300m` | 128, 256, 512, **768** (native) |
| `Snowflake/snowflake-arctic-embed-m-v1.5` | 128, 256, 384, 512, **768** (native) |

Bold entries are each model's native dimension — using the native dim with
`matryoshka.enabled: true` is valid but adds no benefit (no truncation
occurs).

Models not in the table do **not** support MRL truncation.  Specifying
`matryoshka.enabled: true` with an unknown model raises `ConfigError`.

---

## Validation rules

The following `ConfigError` conditions are enforced at **configure time**
(inside `_provision_vector_store`), not at first embedding call:

| Condition | Error |
|---|---|
| `matryoshka` key absent or `enabled: false` | No error — disabled path unchanged |
| `dimension` missing when `enabled: true` | `ConfigError` — dimension required |
| `model_name` not in catalog | `ConfigError` — unsupported model |
| Model in catalog but no `matryoshka_dimensions` list | `ConfigError` — model does not support MRL |
| `matryoshka.dimension` not in the model's allowed list | `ConfigError` — invalid dimension for this model |
| `vector_store_config.dimension != matryoshka.dimension` | `ConfigError` — both values listed in the message |

The same checks run again inside `SentenceTransformerModel.__init__` as a
belt-and-suspenders guard for callers that bypass the handler.

---

## Operational caveat

**The pgvector column shape is fixed at table creation time.**

If you ingest at 512 dims and later change `matryoshka.dimension` to 256, the
insert will fail with a pgvector dimension mismatch error.  To change the
truncation dimension you must:

1. Drop the existing pgvector collection / table.
2. Update both `vector_store_config.dimension` and
   `embedding_model.matryoshka.dimension` to the new value.
3. Re-provision the store (the handler will create a new `vector(256)` column).
4. Re-ingest all documents.

There is no in-place migration path.

---

## Performance hint

Smaller Matryoshka dimensions reduce HNSW index size proportionally.  For
reference, with `nomic-ai/nomic-embed-text-v1.5`:

| Dimension | Relative index size | Typical quality trade-off |
|---|---|---|
| 768 (native) | 100 % | Baseline |
| 512 | ~67 % | Negligible loss on most benchmarks |
| 256 | ~33 % | Small loss; good for high-speed recall tasks |
| 128 | ~17 % | Noticeable loss; use only when storage is the bottleneck |
| 64  | ~8 %  | Use only for coarse pre-filtering before a reranker |

---

## Worked example — nomic-embed-text-v1.5 at 512 dims

```python
# Python dict equivalent of the YAML above
vector_store_config = {
    "name": "postgres",
    "table": "hr_policy_vectors",
    "schema": "public",
    "dimension": 512,
    "connection_string": "postgresql://user:pass@localhost/mydb",
    "embedding_model": {
        "model_name": "nomic-ai/nomic-embed-text-v1.5",
        "model_type": "huggingface",
        "matryoshka": {
            "enabled": True,
            "dimension": 512,
        },
    },
}

# The handler validates and provisions the pgvector table with vector(512).
# Subsequent embed_documents / embed_query calls produce 512-dim unit vectors.
```

After provisioning, the `parrot.embeddings` public API:

```python
from parrot.embeddings import MatryoshkaConfig, validate_against_catalog

# Validate a config against the catalog programmatically:
cfg = MatryoshkaConfig(enabled=True, dimension=512)
validate_against_catalog(cfg, "nomic-ai/nomic-embed-text-v1.5")  # no error

# Invalid dimension raises ConfigError:
bad_cfg = MatryoshkaConfig(enabled=True, dimension=300)
validate_against_catalog(bad_cfg, "nomic-ai/nomic-embed-text-v1.5")
# → ConfigError: dimension 300 is not in matryoshka_dimensions …
```

---

## See also

- `sdd/specs/matryoshka-embedding-truncation.spec.md` — full design spec (FEAT-150)
- `docs/contextual-embedding.md` — contextual chunking and late-chunking embeddings
- `parrot/embeddings/matryoshka.py` — `MatryoshkaConfig`, `validate_against_catalog`
- `parrot/embeddings/huggingface.py` — `SentenceTransformerModel` with MRL truncation
