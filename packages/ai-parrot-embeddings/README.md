# ai-parrot-embeddings

Concrete backend implementations for the AI-Parrot retrieval stack:
embedding models, vector stores, and rerankers.

## What's in this package

This satellite contributes modules to three subsystems of the
`parrot.*` namespace:

- `parrot.embeddings.{google, huggingface, openai}` — embedding backends
- `parrot.stores.{postgres, pgvector, milvus, arango, bigquery, faiss_store}` — vector stores
- `parrot.rerankers.{local, llm}` — rerankers

The abstract base classes (`EmbeddingModel`, `AbstractStore`, `AbstractReranker`),
the registries (`EmbeddingRegistry`), the dispatch maps (`supported_embeddings`,
`supported_stores`), and all shared types (`parrot.stores.models.Document`,
`SearchResult`, etc.) remain in the `ai-parrot` core package.

## Import contract

This package uses **PEP 420 implicit namespace packages**. Its modules ship
directly under the existing `parrot.*` namespace — no separate top-level.
Existing imports continue to work unchanged once installed:

```python
from parrot.embeddings.huggingface import SentenceTransformerModel  # from satellite
from parrot.stores.pgvector import PgVectorStore                    # from satellite
from parrot.embeddings import EmbeddingRegistry                     # from core
from parrot.stores import AbstractStore, supported_stores           # from core
```

No code changes are needed in user projects after upgrading from
`ai-parrot[embeddings]` to `ai-parrot-embeddings[...]`.

## Install

| Goal | Command |
|------|---------|
| Core framework only (no backends) | `pip install ai-parrot` |
| One backend | `pip install ai-parrot-embeddings[pgvector]` |
| Multiple backends | `pip install ai-parrot-embeddings[pgvector,milvus,huggingface]` |
| Embeddings + vector stores | `pip install ai-parrot-embeddings[huggingface,pgvector]` |
| Rerankers | `pip install ai-parrot-embeddings[reranker-local]` |
| Everything | `pip install ai-parrot-embeddings[all]` |
| Legacy all-in-one (unchanged) | `pip install ai-parrot[all]` |

## Extras

| Extra | Pulls in | Enables |
|-------|----------|---------|
| `huggingface` | `sentence-transformers`, `tokenizers`, `safetensors`, `einops`, `accelerate`, `peft`, `xformers`, `simsimd`, `bm25s`, `rank_bm25`, `sentencepiece` | `parrot.embeddings.huggingface.SentenceTransformerModel` |
| `google` | `google-genai`, `google-cloud-aiplatform` | `parrot.embeddings.google.GoogleEmbeddingModel` |
| `openai` | `openai`, `tiktoken` | `parrot.embeddings.openai.OpenAIEmbeddingModel` |
| `pgvector` | `pgvector==0.4.1` | `parrot.stores.postgres.PgVectorStore`, `parrot.stores.pgvector.PgVectorStore` |
| `milvus` | `pymilvus`, `milvus-lite` | `parrot.stores.milvus.MilvusStore` |
| `arango` | `python-arango-async` | `parrot.stores.arango.ArangoDBStore` |
| `bigquery` | `google-cloud-bigquery` | `parrot.stores.bigquery.BigQueryStore` |
| `faiss` | (no extra deps; `faiss-cpu` ships with `ai-parrot` core) | `parrot.stores.faiss_store.FAISSStore` |
| `chroma` | `chromadb` | (reserved for future `ChromaStore`) |
| `reranker-local` | `sentence-transformers`, `tokenizers`, `safetensors` | `parrot.rerankers.local.LocalCrossEncoderReranker` |
| `reranker-llm` | (no extra deps; uses existing LLM clients) | `parrot.rerankers.llm.LLMReranker` |
| `all` | All of the above | Full retrieval stack |

## Development

```bash
git clone https://github.com/phenobarbital/ai-parrot
cd ai-parrot
source .venv/bin/activate
uv pip install -e packages/ai-parrot -e packages/ai-parrot-embeddings
uv run pytest packages/ai-parrot-embeddings/tests/
```

Or for the full workspace (if no pre-existing dependency conflicts):

```bash
uv sync --all-packages
```

## Architecture

This package uses **PEP 420 implicit namespace packages** (not the
`parrot_<name>.*` + `sys.meta_path` redirector pattern used by
`ai-parrot-tools`, `-loaders`, `-pipelines`). The satellite ships no
`__init__.py` files at `parrot/`, `parrot/embeddings/`, `parrot/stores/`,
or `parrot/rerankers/`. Python's import machinery merges the satellite's
directory entries with the host's regular packages at import time, because
the host's sub-package `__init__.py` files call `pkgutil.extend_path`.

## Design rationale

- Spec: [`sdd/specs/ai-parrot-embeddings.spec.md`](../../sdd/specs/ai-parrot-embeddings.spec.md)
- Proposal: [`sdd/proposals/ai-parrot-embeddings.proposal.md`](../../sdd/proposals/ai-parrot-embeddings.proposal.md)
- Feature: FEAT-201
