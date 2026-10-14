# TASK-4303: Relocate GraphIndexEmbedder to parrot/embeddings/graphindex.py (framework adapter)

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4302
**Assigned-to**: unassigned

---

## Context

Spec §3 M2 + codex S8. `graphindex/embed.py:15-20` imports `EmbeddingRegistry`, calls `quiet_faiss_loader()` and imports faiss at module level; `_persist_to_pgvector` (:193) is a stub. The class moves to the framework side; durable vectors move to `EmbeddingPersistence` (backend capability). `build_graph_memory_toolkit` reads `embedder.index` / `_node_id_map` (:285-287) — that FAISS wiring moves to `attach_hot_index` in the adapter module.

---

## Scope

- Create `parrot/embeddings/graphindex.py` with `GraphIndexEmbedder` moved verbatim minus `pgvector_dsn` and `_persist_to_pgvector`; add `vectors()`.
- Add `attach_hot_index(toolkit_kwargs, embedder)` helper returning the `faiss_index`/`node_id_list` kwargs for `GraphIndexToolkit`.
- Replace `graphindex/embed.py` with a PEP 562 lazy re-export of `GraphIndexEmbedder` (old import path keeps working, no faiss at import).
- In `factory.py`, build the toolkit kwargs through the helper instead of reading private embedder fields.
- Tests: adapter satisfies `Embedder`; `import parrot.knowledge.graphindex.embed` loads no faiss; old path returns the same class.

**NOT in scope**: Builder coordination of `EmbeddingPersistence` (TASK-4304); factory backend dispatch (TASK-4321).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/graphindex.py` | CREATE | GraphIndexEmbedder adapter + attach_hot_index |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py` | MODIFY | lazy re-export |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` | MODIFY | use attach_hot_index |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` | MODIFY | drop the `pgvector_dsn=` kwarg passed to GraphIndexEmbedder (checklist: fix any caller passing it) |
| `packages/ai-parrot/tests/knowledge/graphindex/test_embedder_adapter.py` | CREATE | adapter tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.embeddings.registry import EmbeddingRegistry  # registry.py:55
from parrot.utils.faiss_logging import quiet_faiss_loader  # faiss_logging.py:34
from parrot.knowledge.graphindex.schema import UniversalNode
from parrot.knowledge.graphindex.protocols import Embedder  # TASK-4302
```

### Existing Signatures to Use
```python
# graphindex/embed.py: :15 EmbeddingRegistry import; :17 quiet_faiss_loader import; :19 call; :20 import faiss
# class GraphIndexEmbedder :25; search_similar :122; get_embedding :160; _persist_to_pgvector :193 (stub)
# factory.py:283-289 — GraphIndexToolkit(graph=..., faiss_index=embedder.index, node_map=..., node_id_list=list(embedder._node_id_map), ...)
```

### Does NOT Exist
- ~~a real pgvector write in `GraphIndexEmbedder` (stub only)~~
- ~~`parrot.embeddings.graphindex` (created here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/embeddings/graphindex.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_embedder_adapter.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py#GraphIndexEmbedder",
    "sym:packages/ai-parrot/src/parrot/embeddings/registry.py#EmbeddingRegistry"
  ]
}
```

---

## Implementation Notes

`HashingGraphEmbedder` also exposes `index`/`_node_id_map` (factory.py:139). `attach_hot_index` must accept both, reading the attributes in exactly one place. Keep FAISS log quieting inside the adapter module (import-time there is fine: it is framework-side).

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Move the class body to the new module, dropping `pgvector_dsn`/`_persist_to_pgvector` — *why*: S8, durable vectors are a backend capability.
2. Add `vectors()` returning `{node_id: np.ndarray}` — *why*: builder hands it to `EmbeddingPersistence.upsert_embeddings`.
3. Write `attach_hot_index` — *why*: the generic graph path must not read private embedder fields (spec §2).
4. Replace `embed.py` with a lazy re-export — *why*: old import path keeps working without faiss at import.
5. Switch factory.py:285-287 to the helper — *why*: one place reads the private fields.

### `packages/ai-parrot/src/parrot/embeddings/graphindex.py` (CREATE)
```python
"""GraphIndexEmbedder — framework-side Embedder adapter (FEAT-540 M2)."""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from parrot.embeddings.registry import EmbeddingRegistry
from parrot.knowledge.graphindex.schema import UniversalNode
from parrot.utils.faiss_logging import quiet_faiss_loader

quiet_faiss_loader()
import faiss  # noqa: E402

logger = logging.getLogger(__name__)


class GraphIndexEmbedder:
    """Batch-embed UniversalNode summaries into an in-memory FAISS index (satisfies Embedder)."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", dimension: int = 384) -> None:
        # FILL IN: move __init__ body from graphindex/embed.py minus pgvector_dsn; keep the default model_name used there
        raise NotImplementedError

    # FILL IN: move embed_nodes / search_similar / get_embedding verbatim (embed.py:58-190); drop the _persist_to_pgvector call

    def vectors(self) -> dict[str, np.ndarray]:
        """Hot vectors keyed by node_id, for EmbeddingPersistence.upsert_embeddings."""
        # FILL IN: build from the internal node-id map + index reconstruction or the stored matrix
        raise NotImplementedError


def attach_hot_index(embedder: Any) -> dict[str, Any]:
    """Return the GraphIndexToolkit kwargs that expose the embedder's FAISS hot index."""
    return {"faiss_index": embedder.index, "node_id_list": list(embedder._node_id_map)}
```
**Why**: Framework side may import faiss; the graph tree may not. The default `model_name` must equal today's default — read it, do not invent.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.embeddings.registry import EmbeddingRegistry' parrot/knowledge/graphindex/embed.py)
# AFTER/AT — anchor `from parrot.embeddings.registry import EmbeddingRegistry` (verified: embed.py:15)
# REPLACE the whole module body with a lazy re-export:
"""Compatibility path for GraphIndexEmbedder — the class lives in parrot.embeddings.graphindex (FEAT-540)."""
from typing import Any

__all__ = ["GraphIndexEmbedder"]


def __getattr__(name: str) -> Any:
    if name == "GraphIndexEmbedder":
        from parrot.embeddings.graphindex import GraphIndexEmbedder

        return GraphIndexEmbedder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```
**Why**: Old public path keeps resolving to the same class; importing it costs nothing until the name is requested.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'faiss_index=embedder.index,' parrot/knowledge/graphindex/factory.py)
# AFTER/AT — anchor `faiss_index=embedder.index,` (verified: factory.py:285)
# REPLACE the two kwargs `faiss_index=embedder.index,` and `node_id_list=list(embedder._node_id_map),` with
#   **attach_hot_index(embedder),
# and import it lazily inside build_graph_memory_toolkit:
#   from parrot.embeddings.graphindex import attach_hot_index
```
**Why**: One reader of private embedder fields, framework-side (spec §2).

### `packages/ai-parrot/tests/knowledge/graphindex/test_embedder_adapter.py` (CREATE)
```python
"""GraphIndexEmbedder adapter (FEAT-540 M2)."""
from parrot.knowledge.graphindex.protocols import Embedder


def test_old_path_is_same_class() -> None:
    from parrot.embeddings.graphindex import GraphIndexEmbedder as new
    from parrot.knowledge.graphindex.embed import GraphIndexEmbedder as old

    assert old is new


def test_adapter_satisfies_embedder() -> None:
    from parrot.embeddings.graphindex import GraphIndexEmbedder

    assert hasattr(GraphIndexEmbedder, 'search_similar') and hasattr(GraphIndexEmbedder, 'get_embedding')


def test_no_pgvector_dsn() -> None:
    import inspect
    from parrot.embeddings.graphindex import GraphIndexEmbedder

    assert 'pgvector_dsn' not in inspect.signature(GraphIndexEmbedder).parameters


# FILL IN: probe that importing parrot.knowledge.graphindex.embed loads no 'faiss' (tests/knowledge/_support/import_probe.py)
```
**Why**: Proves path compatibility and the S8 removal.

### FILL IN checklist
- [ ] adapter `__init__`/method bodies moved verbatim
- [ ] `vectors()` implementation
- [ ] faiss-absence probe test
- [ ] fix any caller passing `pgvector_dsn=` (grep) — bounded by S8 (removed)

---

## Acceptance Criteria

- [ ] `GraphIndexEmbedder` lives in `parrot.embeddings.graphindex`; old path resolves lazily
- [ ] no `pgvector_dsn` / `_persist_to_pgvector`
- [ ] `factory.py` no longer reads `embedder._node_id_map` directly
- [ ] existing `test_embed.py` passes

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_embedder_adapter.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_embed.py -q`

---

## Test Specification

```python
# see test_embedder_adapter.py block
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
9. **Close** with `scripts/sdd/close_task.sh TASK-4303 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
