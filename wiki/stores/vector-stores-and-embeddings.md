---
title: "Vector Stores and Embeddings Reference"
summary: "How AbstractStore, the supported_stores dispatch table, shared models, embedding models and registry, and rerankers fit together, and which concrete backends ship from ai-parrot-embeddings."
---

# Vector Stores and Embeddings Reference

## Purpose

This page is the map of AI-Parrot's retrieval storage layer: the abstract store contract, the
registry that dispatches store names to classes, the shared data models, the embedding model
layer, and the optional rerankers that sit after retrieval.

The code is split across two distributions that share the `parrot.*` namespace through PEP 420
namespace merging (each `__init__.py` calls `extend_path`):

- **ai-parrot (core)** keeps the base machinery: `parrot/stores/abstract.py`,
  `parrot/stores/models.py`, `parrot/embeddings/{base,registry,catalog,matryoshka}.py`,
  `parrot/rerankers/{abstract,factory,models}.py`.
- **ai-parrot-embeddings** ships the concrete backends under
  `packages/ai-parrot-embeddings/src/parrot/`: stores (`postgres.py`, `milvus.py`,
  `faiss_store.py`, `arango.py`, `bigquery.py`, `lancedb.py`), embedding providers
  (`huggingface.py`, `google.py`, `openai.py`) and rerankers (`local.py`, `llm.py`).

Import paths do not change because of the split: `from parrot.stores.postgres import PgVectorStore`
works whether the module comes from core or from the satellite.

## Public API

Store layer:

- [`parrot.stores`](ref:parrot.stores) — package `__init__`: the `supported_stores` dict and a lazy
  `AbstractStore` export (resolved through module `__getattr__` to avoid importing `navconfig` early).
- [`parrot.stores.abstract`](ref:parrot.stores.abstract) — `AbstractStore`, the ABC every backend subclasses.
- [`parrot.stores.models`](ref:parrot.stores.models) — `Document`, `DistanceStrategy`, and re-exports of `SearchResult` and `StoreConfig`.
- [`parrot.models.stores`](ref:parrot.models.stores) — canonical home of `SearchResult`, `StoreConfig`, `StoreType`, and the multi search models, kept dependency free.

Concrete backends (ai-parrot-embeddings):

- [`parrot.stores.postgres`](ref:parrot.stores.postgres) — `PgVectorStore` (the primary store). `parrot/stores/pgvector.py` is only a shim that re-exports it.
- [`parrot.stores.milvus`](ref:parrot.stores.milvus) — `MilvusStore`.
- [`parrot.stores.faiss_store`](ref:parrot.stores.faiss_store) — `FAISSStore`.
- [`parrot.stores.arango`](ref:parrot.stores.arango) — `ArangoDBStore`.
- [`parrot.stores.bigquery`](ref:parrot.stores.bigquery) — `BigQueryStore`.
- [`parrot.stores.lancedb`](ref:parrot.stores.lancedb) — `LanceDBStore` (see the LanceDB pages linked below).

Embedding layer:

- [`parrot.embeddings`](ref:parrot.embeddings) — `supported_embeddings`, `EmbeddingRegistry`, catalog helpers, `MatryoshkaConfig`.
- [`parrot.embeddings.base`](ref:parrot.embeddings.base) — `EmbeddingModel` ABC.
- [`parrot.embeddings.registry`](ref:parrot.embeddings.registry) — `EmbeddingRegistry`, a process wide cache of loaded models.
- [`parrot.embeddings.catalog`](ref:parrot.embeddings.catalog) — `EMBEDDING_MODELS`, `get_embedding_models()`, `get_use_cases()`, `get_model_recommendations()`.
- [`parrot.embeddings.matryoshka`](ref:parrot.embeddings.matryoshka) — `MatryoshkaConfig` and `validate_against_catalog()`.
- [`parrot.embeddings.huggingface`](ref:parrot.embeddings.huggingface) — `SentenceTransformerModel`.
- [`parrot.embeddings.google`](ref:parrot.embeddings.google) — `GoogleEmbeddingModel`.
- [`parrot.embeddings.openai`](ref:parrot.embeddings.openai) — `OpenAIEmbeddingModel`.
- [`parrot.embeddings.multimodal`](ref:parrot.embeddings.multimodal) — text and image embeddings (`MultimodalEmbedding`, `UFormEmbedding`).

Rerankers:

- [`parrot.rerankers`](ref:parrot.rerankers) — package exports; `LocalCrossEncoderReranker` and `LLMReranker` are lazy.
- [`parrot.rerankers.abstract`](ref:parrot.rerankers.abstract) — `AbstractReranker`.
- [`parrot.rerankers.models`](ref:parrot.rerankers.models) — `RerankedDocument`, `RerankerConfig`.
- [`parrot.rerankers.factory`](ref:parrot.rerankers.factory) — `create_reranker()` and the `RERANKER_TYPES` registry.
- [`parrot.rerankers.local`](ref:parrot.rerankers.local) — `LocalCrossEncoderReranker`.
- [`parrot.rerankers.llm`](ref:parrot.rerankers.llm) — `LLMReranker`.

### The dispatch table

`parrot.stores.supported_stores` maps a store slug to a class name:

| Slug | Class name in the table |
|---|---|
| `postgres` | `PgVectorStore` |
| `milvus` | `MilvusStore` |
| `kb` | `KnowledgeBaseStore` |
| `faiss_store` | `FaissStore` |
| `arango` | `ArangoStore` |
| `bigquery` | `BigQueryStore` |
| `lancedb` | `LanceDBStore` |

The HTTP store handler (`parrot/handlers/stores/handler.py`) resolves a store as
`importlib.import_module(f"parrot.stores.{slug}")` followed by `getattr(module, supported_stores[slug])`.
See Gotchas for two names in this table that do not match the shipped classes.

### AbstractStore contract

Abstract methods a backend must implement: `connection()`, `disconnect()`, `get_vector()`,
`similarity_search()`, `from_documents()`, `create_collection()`, `add_documents()`,
`prepare_embedding_table()`, `delete_documents()` and `delete_documents_by_filter()`.

Concrete behaviour inherited for free: `async with` support (connects on enter, frees the embedding
model and disconnects on the outermost exit), `create_embedding()`, `get_default_embedding()`,
`generate_embedding()`, and the opt in contextual header step `_apply_contextual_augmentation()`.

`similarity_search` has this signature in the base class:

```python
async def similarity_search(
    self,
    query: str,
    collection: Union[str, None] = None,
    limit: int = 2,
    similarity_threshold: float = 0.0,
    search_strategy: str = "auto",
    metadata_filters: Union[dict, None] = None,
    include_parents: bool = False,
    **kwargs
) -> list
```

### Shared models

- `Document(page_content: str, metadata: Dict[str, Any])` — a Pydantic model used to feed `add_documents()` / `from_documents()`.
- `SearchResult` — fields `id`, `content`, `metadata`, `score`, `ensemble_score`, `search_source`, `similarity_rank`, `mmr_rank`, plus a computed `distance` that mirrors `score`. For distance metrics lower means closer.
- `DistanceStrategy` (a `str` Enum) — `EUCLIDEAN_DISTANCE`, `MAX_INNER_PRODUCT`, `DOT_PRODUCT`, `JACCARD`, `COSINE`.
- `StoreConfig` — a dataclass, see the next section.

## Configuration & Parameters

### AbstractStore constructor

`AbstractStore.__init__(embedding_model=None, embedding=None, **kwargs)` reads these keys from `kwargs`
(defaults in parentheses): `use_database` (`True`), `collection_name` (`"my_collection"`),
`dimension` (`768`), `metric_type` (`"COSINE"`), `index_type` (`"IVF_FLAT"`), `database` (`""`),
`index_name` (`"my_index"`), `contextual_embedding` (`False`), `contextual_template`,
`contextual_max_header_tokens`.

`embedding_model` may be a dict, a JSON string holding a dict, or a bare model name. It is normalised by
`_normalize_embedding_config()`: `model` is aliased to `model_name`, and `model_type` defaults to
`"huggingface"`. `embedding` may be a config or a ready callable; a callable replaces the model and the
default HuggingFace config is stored for bookkeeping.

### StoreConfig defaults

`vector_store='postgres'`, `table=None`, `schema='public'`,
`embedding_model={"model_name": "sentence-transformers/all-mpnet-base-v2", "model_type": "huggingface"}`,
`dimension=768`, `dsn=None`, `distance_strategy='COSINE'`, `metric_type='COSINE'`,
`index_type='IVF_FLAT'`, `auto_create=False`, `extra={}`.

### PgVectorStore constructor

```python
PgVectorStore(
    table=None, schema='public', id_column='id', embedding_column='embedding',
    document_column='document', text_column='text',
    embedding_model="sentence-transformers/all-mpnet-base-v2", embedding=None,
    distance_strategy=DistanceStrategy.COSINE, use_uuid=False, pool_size=50,
    auto_initialize=True, enable_colbert=False, **kwargs,
)
```

`PgVectorStore` additionally exposes `mmr_search()` (also present on `FAISSStore`, `BigQueryStore` and `LanceDBStore`).

### Embedding models

`supported_embeddings` maps `model_type` to a class name: `huggingface` to `SentenceTransformerModel`,
`google` to `GoogleEmbeddingModel`, `openai` to `OpenAIEmbeddingModel`, `multimodal` to `UFormEmbedding`.
`AbstractStore.create_embedding()` raises `ConfigError` for any other type, and forwards the
`matryoshka` sub dict of the `embedding_model` config to the model constructor.

`SentenceTransformerModel(model_name, matryoshka=None, backend=None, file_name=None, **kwargs)`;
`backend` is `"torch"`, `"onnx"` or `"openvino"`. `GoogleEmbeddingModel` accepts `output_dimensionality`,
`OpenAIEmbeddingModel` accepts `dimensions`.

`EmbeddingModel` provides `embed_documents(texts, batch_size=None)`, `embed_query(text, as_nparray=False)`,
`initialize_model()`, `free()`, and requires subclasses to implement `_create_embedding()` and `encode()`.
Both `embed_*` methods normalise embeddings.

`EmbeddingRegistry` is a singleton obtained with `EmbeddingRegistry.instance(max_models=None)`. Key methods:
`get_or_create(model_name, model_type="huggingface", **kwargs)` (async, per key lock, loads once),
`get_or_create_sync(...)`, `preload(models)`, `unload(model_name, model_type)`, `loaded_models()`,
`stats()` and `clear()`. The Matryoshka dimension is part of the cache key.

Catalog helpers: `get_embedding_models(provider, use_case, metric, max_dims, hnsw_compatible, requires_prefix)`
(all filters AND together), `get_use_cases()`, `get_model_recommendations(model_name)`.

`MatryoshkaConfig(enabled=False, dimension=None)` requires a `dimension` when `enabled` is true;
`validate_against_catalog(cfg, model_name)` raises `ConfigError` unless the catalog entry declares that dimension
in `matryoshka_dimensions`.

### Rerankers

`create_reranker(config: dict, *, bot_llm_client=None)` returns `None` for an empty dict, and otherwise pops
`type` from a shallow copy. Valid types are `local_cross_encoder` and `llm`; a missing or unknown type raises
`ConfigError`. For `llm`, `client_ref` defaults to `"bot"` (reuse `bot_llm_client`); anything else raises `ConfigError`.

`RerankerConfig` defaults: `model_name="BAAI/bge-reranker-v2-m3"`, `device="auto"`, `precision="auto"`,
`max_length=512`, `batch_size=32`, `trust_remote_code=False`, `warmup=True`.
`LocalCrossEncoderReranker(config=None, **kwargs)` builds a `RerankerConfig` from kwargs when no config is given.
`LLMReranker(client, model_name="llm-reranker", **kwargs)`.

## Usage Examples

Open a store with an embedding model and search it:

```python
import asyncio

from parrot.stores.models import Document, DistanceStrategy
from parrot.stores.postgres import PgVectorStore


async def main() -> None:
    store = PgVectorStore(
        table="docs",
        schema="public",
        embedding_model={
            "model_name": "sentence-transformers/all-mpnet-base-v2",
            "model_type": "huggingface",
        },
        distance_strategy=DistanceStrategy.COSINE,
    )
    async with store:  # connects on enter, disconnects on exit
        await store.add_documents(
            [Document(page_content="Parrots can mimic speech.", metadata={"source": "demo"})]
        )
        results = await store.similarity_search("Can parrots talk?", limit=3)
        for hit in results:
            print(hit.score, hit.content)


asyncio.run(main())
```

Share one embedding model between callers through the registry:

```python
from parrot.embeddings import EmbeddingRegistry


async def warm() -> None:
    registry = EmbeddingRegistry.instance()
    model = await registry.get_or_create(
        "sentence-transformers/all-mpnet-base-v2", "huggingface"
    )
    vector = await model.embed_query("hello")
    print(len(vector))
```

Validate a Matryoshka configuration before wiring it into a store config:

```python
from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog

cfg = MatryoshkaConfig(enabled=True, dimension=512)
validate_against_catalog(cfg, "nomic-ai/nomic-embed-text-v1.5")  # ConfigError if unsupported
```

Rerank retrieved hits with a factory built reranker:

```python
from parrot.rerankers.factory import create_reranker


async def rerank(query: str, hits: list) -> list:
    reranker = create_reranker(
        {"type": "local_cross_encoder", "model_name": "cross-encoder/ms-marco-MiniLM-L-12-v2", "device": "cpu"}
    )
    if reranker is None:
        return hits
    await reranker.load()
    try:
        ranked = await reranker.rerank(query, hits, top_n=5)
    finally:
        await reranker.cleanup()
    return [r.document for r in ranked]
```

## Gotchas

- **Dispatch name mismatch.** `supported_stores` lists `FaissStore` and `ArangoStore`, but the shipped
  classes are `FAISSStore` (`faiss_store.py`) and `ArangoDBStore` (`arango.py`), and no alias with the
  table's names exists in those modules. A `getattr(module, supported_stores[slug])` lookup for these two
  slugs fails; import the real class directly until the table is aligned. The `kb` slug points at
  `parrot.stores.kb`, which is a knowledge base package rather than an `AbstractStore` subclass.
- **Two homes for the models.** `SearchResult` and `StoreConfig` live in `parrot.models.stores`; `parrot.stores.models`
  only re-exports them. Import from `parrot.models.stores` when you must avoid importing the `parrot.stores`
  package, whose `__init__` pulls in more than the models.
- **Store contexts nest.** `__aenter__`/`__aexit__` count depth: the embedding model is freed and the connection
  closed only when the outermost `async with` exits.
- **Parents are hidden by default.** `similarity_search` excludes parent rows unless `include_parents=True`;
  legacy rows without markers are still returned. See the parent child page below.
- **Scores are raw metric values.** `SearchResult.score` is the backend metric (lower is closer for distance metrics);
  `distance` is only an alias.
- **Rerankers never raise.** By contract `rerank()` returns the input order with `rerank_score=float('nan')`
  on internal failure, so check for NaN before trusting scores. An `LLMReranker` with `client=None` falls back
  the same way.
- **Lazy heavy imports.** `LocalCrossEncoderReranker` and `LLMReranker` are loaded on first access to keep
  `import parrot` cheap; the factory does the same.
- **Registry caching.** Matryoshka dimension is part of the cache key, so the same model with different
  truncation dimensions loads as separate entries.

## Related

- [Matryoshka embeddings](matryoshka-embeddings.md) — truncation configuration in depth.
- [Contextual embedding](contextual-embedding.md) — the `contextual_embedding` header step on `AbstractStore`.
- [Parent child retrieval](parent-child-retrieval.md) — parent rows, `include_parents`, small to big search.
- [LanceDB vector store](lancedb-vector-store.md) — the `LanceDBStore` backend.
- [Storage backends](storage-backends.md) — conversation storage, a separate concern from vector stores.
- [Vector store handler API](vectorstore_handler_api.md) — HTTP handler that uses `supported_stores`.
