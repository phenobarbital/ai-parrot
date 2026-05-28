---
id: F012
query_id: Q016
type: grep
intent: Enumerate downstream consumers of parrot.{embeddings,stores,rerankers}.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 130
parent_id: null
depth: 0
---

# F012 — ~25+ consumer sites of `parrot.{embeddings,stores,rerankers}` across core

## Summary

A grep for `from parrot.(embeddings|stores|rerankers)` returned 60+ hits
across 20+ files in ai-parrot core: bots, handlers, knowledge, manager,
memory, registry routing, tools, and the three subsystems internally
cross-importing. Under the user's chosen strategy (PEP 420 namespace
extension), **all of these import sites stay byte-identical** — that is
the whole point of the chosen approach. Under the existing
sibling-package precedent (parrot_<name>.* + redirector), each one would
have stayed working via the meta_path finder.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 82-85
  symbol: lazy backend imports in AbstractBot
  excerpt: |
    from parrot.stores.postgres import PgVectorStore as _PgVectorStore
    from parrot.stores.arango import ArangoDBStore as _ArangoDBStore
    ...
    from parrot.stores.faiss_store import FAISSStore as _FAISSStore

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 1436
  symbol: lazy EmbeddingRegistry import
  excerpt: |
    from parrot.embeddings import EmbeddingRegistry  # local import — avoids circular

- path: `packages/ai-parrot/src/parrot/handlers/stores/helpers.py`
  lines: 4-6
  symbol: handlers consume the dispatch maps
  excerpt: |
    from parrot.stores import supported_stores
    from parrot.stores.models import DistanceStrategy
    from parrot.embeddings import supported_embeddings, get_embedding_models, get_use_cases

- path: `packages/ai-parrot/src/parrot/handlers/stores/handler.py`
  lines: 17-18
  symbol: handlers consume AbstractStore + shared types
  excerpt: |
    from parrot.stores import AbstractStore, supported_stores
    from parrot.stores.models import StoreConfig, SearchResult, Document

- path: `packages/ai-parrot/src/parrot/registry/routing/store_router.py`
  lines: 32-33
  symbol: routing depends on AbstractStore + MultiStoreSearchTool
  excerpt: |
    from parrot.stores.abstract import AbstractStore
    from parrot.tools.multistoresearch import MultiStoreSearchTool, StoreType

- path: `packages/ai-parrot/src/parrot/manager/ephemeral.py`
  lines: 384-385
  symbol: ephemeral agents use FAISSStore lazily
  excerpt: |
    from parrot.stores.faiss_store import FAISSStore  # noqa: PLC0415
    from parrot.stores.models import Document  # noqa: PLC0415

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py`
  lines: 16
  symbol: graphindex consumes EmbeddingRegistry
  excerpt: |
    from parrot.embeddings.registry import EmbeddingRegistry

- path: `packages/ai-parrot/src/parrot/rerankers/llm.py`
  lines: 29-31
  symbol: rerankers cross-import stores.models
  excerpt: |
    from parrot.rerankers.abstract import AbstractReranker
    from parrot.rerankers.models import RerankedDocument
    from parrot.stores.models import SearchResult

- path: `packages/ai-parrot/src/parrot/stores/kb/store.py`
  lines: 76
  symbol: KB store consumes EmbeddingRegistry lazily
  excerpt: |
    from parrot.embeddings import EmbeddingRegistry  # local import — avoids circular

- path: `packages/ai-parrot/src/parrot/tools/__init__.py`
  lines: 243-244
  symbol: tool registry references vectorstoresearch + multistoresearch
  excerpt: |
    "VectorStoreSearchTool": ".vectorstoresearch",
    "MultiStoreSearchTool": ".multistoresearch",

## Notes

- **`parrot.stores.models`** (Document, SearchResult, StoreConfig,
  DistanceStrategy) is consumed by rerankers, bots, handlers, manager,
  knowledge, scraper. It is a **shared types module** — must stay in
  core regardless of whether the per-backend stores move.
- **`parrot.embeddings.matryoshka`** is consumed by `handlers/bots.py`
  (lines 958+). Matryoshka config is a base concern — stays in core.
- The lazy / circular-import comments on multiple sites
  (`# local import — avoids circular`, `# noqa: PLC0415`) signal that
  the codebase already defers backend imports; the split doesn't
  introduce new circularity risk.
