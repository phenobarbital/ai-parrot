---
id: F014
query_id: Q017/Q027
type: grep
intent: Identify coupling sites that stay in core but consume the satellite.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 60
parent_id: null
depth: 0
---

# F014 — Coupling sites: handlers/stores, tools/{vectorstoresearch,multistoresearch}, registry/routing

## Summary

Three coupling sites stay in core but consume backends that move to
ai-parrot-embeddings: (1) `parrot/handlers/stores/` — HTTP handlers that
manage vector-store CRUD/search; (2) `parrot/tools/vectorstoresearch.py`
and `parrot/tools/multistoresearch.py` — generic search tools used by
agents (declared as core tools in the FEAT-057 spec); (3)
`parrot/registry/routing/store_router.py` — request routing layer that
uses `StoreType` from `multistoresearch`. None of these need to move;
all keep working under the namespace-extension model because their
imports (`from parrot.stores.abstract import AbstractStore`,
`from parrot.stores.models import SearchResult`) target symbols that
stay in core.

## Citations

- path: `packages/ai-parrot/src/parrot/handlers/stores/`
  lines: null
  symbol: tree (3 files)
  excerpt: |
    handlers/stores/
    ├── __init__.py
    ├── handler.py     ← HTTP handler class for /stores/* routes
    └── helpers.py     ← shared helpers (uses supported_stores + supported_embeddings)

- path: `packages/ai-parrot/src/parrot/tools/__init__.py`
  lines: 243-244
  symbol: core tools that wrap stores
  excerpt: |
    "VectorStoreSearchTool": ".vectorstoresearch",
    "MultiStoreSearchTool": ".multistoresearch",

- path: `packages/ai-parrot/src/parrot/registry/routing/store_router.py`
  lines: 32-33
  symbol: store routing wires AbstractStore + StoreType
  excerpt: |
    from parrot.stores.abstract import AbstractStore
    from parrot.tools.multistoresearch import MultiStoreSearchTool, StoreType

- path: `sdd/specs/monorepo-migration.spec.md`
  lines: 131-132
  symbol: FEAT-057 declared these as core
  excerpt: |
    | `parrot/tools/vectorstore_search.py` | stays in core | `VectorStoreSearchTool` — core RAG primitive |
    | `parrot/tools/multi_store_search.py` | stays in core | `MultiStoreSearchTool` — core RAG primitive |

## Notes

- `MultiStoreSearchTool.StoreType` is the **source of truth for store
  identifiers** (per the docstring at
  `packages/ai-parrot/src/parrot/registry/routing/models.py:24`). It
  enumerates the backend keys. After FEAT-201, this enum stays in core
  but its members map to backends shipped from ai-parrot-embeddings.
- The "thin-client" pattern used by FEAT-079 (Form Creation tools stay
  in core as thin clients of heavy methods in the new package) is
  **already exhibited here**: `VectorStoreSearchTool` and
  `MultiStoreSearchTool` are RAG-primitive thin wrappers; the heavy
  vector-store I/O lives in the concrete backends that will move.
