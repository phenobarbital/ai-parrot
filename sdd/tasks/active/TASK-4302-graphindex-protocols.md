# TASK-4302: graphindex/protocols.py — provider + persistence Protocols, edge_key, errors

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 'New Public Interfaces' and §3 M2/M7. One stdlib-only module declares every structural contract the graph tree consumes: providers (`Embedder`, `LLMCaller`, `PageIndexer`), persistence (`GraphPersistence` + `Incremental`, `Temporal`, `Embedding`, `HybridRetrieval`, `SourceCoherence` capabilities), the canonical `edge_key()` and the `ProviderNotAvailable` / `CapabilityUnavailable` errors.

---

## Scope

- Create `graphindex/protocols.py` with the exact signatures of spec §2 (runtime_checkable Protocols; framework classes never inherit).
- `edge_key(source_id, target_id, kind) -> str` returning the format the three backends' `_edge_key` helpers use today.
- `ProviderNotAvailable(role, distribution, extra=None)` with an actionable message; `CapabilityUnavailable(backend, capability)`.
- Tests: concrete classes satisfy their Protocols (`HashingGraphEmbedder`, `PageIndexLLMAdapter`, `PageIndexToolkit`, `SQLitePersistence` for `GraphPersistence` minus `close`, Postgres for Temporal/Hybrid via class attribute checks), doubles missing a method do not; module imports only stdlib.

**NOT in scope**: Retyping consumers (TASK-4304/4305/4321); adding `close()`/`file_hashes()` to backends (TASK-4319).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py` | CREATE | all Protocols + edge_key + errors |
| `packages/ai-parrot/tests/knowledge/graphindex/test_protocols.py` | CREATE | structural conformance tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.graphindex.factory import HashingGraphEmbedder  # factory.py:116 (tests only)
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter  # llm_adapter.py:42 (tests only)
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # toolkit.py:54 (tests only)
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence  # persist_sqlite.py:138 (tests only)
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence  # persist_postgres.py:207 (tests only; asyncpg importorskip)
```

### Existing Signatures to Use
```python
# persist.py:65 / persist_sqlite.py:133 / persist_postgres.py:162 — def _edge_key(source_id: str, target_id: str, kind: str) -> str
# llm_adapter.py: ask :61, ask_structured :99, ask_json :201
# toolkit.py: list_trees :404, create_tree :408, delete_tree :430, get_tree :550, insert_markdown :819, insert_ebook :857
# factory.py HashingGraphEmbedder: embed_nodes(nodes, batch_size=64) :142; get_embedding(node_id) :172; search_similar(query, top_k=10) :176
# persist_sqlite.py: persist_graph :263, replace_document_slice :341, is_stale :464, load_graph :574, apply_update :608, get_commit :785, list_commits :817, revert_commit :856
# persist_postgres.py: close :256, as_of :1175, history :1228, diff :1254, upsert_embeddings :1331, hybrid_retrieve :1484
```

### Does NOT Exist
- ~~any existing persistence base class or Protocol — `GraphPublisher.__init__(persistence: Any)` (publish.py:47)~~
- ~~`ask_with_finish_info` in `LLMCaller` (not used by graph consumers)~~
- ~~`_content_store` as a required `PageIndexer` member (optional capability)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_protocols.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py#HashingGraphEmbedder",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py#SQLitePersistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py#PostgresPersistence"
  ]
}
```

---

## Implementation Notes

Copy the signatures verbatim from spec §2 (they are fixed). The module must import only `typing`/`collections.abc` at runtime so it is free for every consumer. `edge_key` must return exactly what `_edge_key` returns today — read one of them and mirror it; the backends switch to it in TASK-4319/4320.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Read one `_edge_key` implementation — *why*: the canonical helper must not change any stored key.
2. Write the module from spec §2 — *why*: signatures are fixed by the spec skeleton.
3. Write tests with typed doubles — *why*: `runtime_checkable` only checks attribute presence (spec §7).

### `packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py` (CREATE)
```python
"""Structural contracts the GraphIndex / wiki graph tree consumes (FEAT-540 M2 + M7).

Runtime imports are stdlib-only. Framework classes satisfy these Protocols structurally; they never inherit.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


def edge_key(source_id: str, target_id: str, kind: str) -> str:
    """Canonical edge identity shared by every backend (spec §2 GraphPersistence semantics)."""
    # FILL IN: return exactly what persist_sqlite.py:133 `_edge_key` returns today
    raise NotImplementedError


class ProviderNotAvailable(RuntimeError):
    """A required provider was never injected; the CLI maps it to exit code 2."""

    def __init__(self, role: str, distribution: str, extra: str | None = None) -> None:
        self.role, self.distribution, self.extra = role, distribution, extra
        hint = f"pip install {distribution}[{extra}]" if extra else f"pip install {distribution}"
        super().__init__(f"No {role} provider is configured. Install or configure one ({hint}).")


class CapabilityUnavailable(RuntimeError):
    """The selected graph backend does not implement an optional capability."""

    def __init__(self, backend: str, capability: str) -> None:
        self.backend, self.capability = backend, capability
        super().__init__(f"Graph backend {backend!r} does not support {capability!r}.")


@runtime_checkable
class Embedder(Protocol):
    """Vector provider for graph nodes."""

    async def embed_nodes(self, nodes: list[Any], batch_size: int = 64) -> list[Any]: ...
    def get_embedding(self, node_id: str) -> Any | None: ...
    async def search_similar(self, query: str, /, top_k: int = 10) -> list[tuple[str, float]]: ...


# FILL IN: LLMCaller, PageIndexer, GraphPersistence (+ its semantics docstring), IncrementalPersistence,
# TemporalGraphPersistence, EmbeddingPersistence, HybridRetrievalPersistence, SourceCoherencePersistence —
# copy signatures and docstrings verbatim from spec §2 'New Public Interfaces'
```
**Why**: Single home for every contract so consumers import one cheap module; the semantics docstring on `GraphPersistence` is what the conformance suite (TASK-4319) asserts.

### `packages/ai-parrot/tests/knowledge/graphindex/test_protocols.py` (CREATE)
```python
"""Structural conformance of concrete providers/backends (FEAT-540 M2/M7)."""
import pytest

from parrot.knowledge.graphindex.protocols import (
    Embedder, GraphPersistence, IncrementalPersistence, PageIndexer, ProviderNotAvailable, edge_key,
)


def test_hashing_embedder_is_embedder() -> None:
    from parrot.knowledge.graphindex.factory import HashingGraphEmbedder

    assert isinstance(HashingGraphEmbedder(), Embedder)


def test_double_missing_search_is_not_embedder() -> None:
    class _D:
        async def embed_nodes(self, nodes, batch_size=64): return nodes
        def get_embedding(self, node_id): return None

    assert not isinstance(_D(), Embedder)


def test_provider_not_available_message() -> None:
    err = ProviderNotAvailable("llm", "ai-parrot", "clients")
    assert "llm" in str(err) and "ai-parrot[clients]" in str(err)


def test_edge_key_matches_sqlite_helper() -> None:
    from parrot.knowledge.graphindex.persist_sqlite import _edge_key

    assert edge_key("a", "b", "calls") == _edge_key("a", "b", "calls")


# FILL IN: PageIndexLLMAdapter/LLMCaller, PageIndexToolkit/PageIndexer (class-level hasattr is enough — no instantiation),
# SQLitePersistence methods vs GraphPersistence/IncrementalPersistence, Postgres temporal/hybrid via importorskip('asyncpg'),
# and a probe that importing protocols loads no parrot.* framework module
```
**Why**: Typed doubles prove the Protocol shapes; the probe proves the module stays free.

### FILL IN checklist
- [ ] `protocols.py` — remaining Protocols verbatim from spec §2
- [ ] `edge_key` body mirroring `_edge_key`
- [ ] remaining conformance tests

---

## Acceptance Criteria

- [ ] `graphindex/protocols.py` exists with every symbol of spec §2's protocols block
- [ ] `edge_key` equals the SQLite helper output
- [ ] importing the module loads no `parrot.tools`/`parrot.clients`/`parrot.embeddings`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_protocols.py -q`

---

## Test Specification

```python
# see test_protocols.py block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4302 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
