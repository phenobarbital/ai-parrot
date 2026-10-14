# TASK-4304: Retype builder, retriever and signals against the Protocols

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4302, TASK-4303
**Assigned-to**: unassigned

---

## Context

Spec §3 M2. `builder.py:34,55` import the concrete embedder and `PageIndexToolkit`; `builder.py:505` probes `hasattr(self.persistence, "is_stale")`; `signals.py` and `retriever.py` annotate with `GraphIndexEmbedder`.

---

## Scope

- `builder.py`: remove the module-level `GraphIndexEmbedder`/`PageIndexToolkit` imports; type `embedder: Embedder`, `pageindex_toolkit: PageIndexer | None`; replace the `hasattr(..., "is_stale")` probe with `isinstance(self.persistence, IncrementalPersistence)`; after embedding, call `upsert_embeddings` when the persistence is an `EmbeddingPersistence` and the embedder exposes `vectors()`.
- `signals.py`, `retriever.py`: annotations to `Embedder` (TYPE_CHECKING import), no runtime change.
- Test: builder runs with a typed `Embedder` double and a fake persistence without `is_stale`; with an `EmbeddingPersistence` fake it receives vectors.

**NOT in scope**: `persistence: GraphIndexPersistence` annotation/import at builder.py:43 (TASK-4320 renames it); extractor Document typing (TASK-4317).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` | MODIFY | Protocol types, capability isinstance, embedding persistence |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` | MODIFY | Embedder annotation |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py` | MODIFY | Embedder annotations |
| `packages/ai-parrot/tests/knowledge/graphindex/test_builder_protocols.py` | CREATE | builder with doubles |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.graphindex.protocols import Embedder, EmbeddingPersistence, IncrementalPersistence, PageIndexer  # TASK-4302
```

### Existing Signatures to Use
```python
# builder.py: :34 GraphIndexEmbedder import; :55 PageIndexToolkit import; class GraphIndexBuilder :60; __init__ :116-136 (persistence :118, embedder :119, pageindex_toolkit :123); is_stale probe :505
# retriever.py:321 raw = await self.embedder.search_similar(
# signals.py: embedder: Optional["GraphIndexEmbedder"] at :395, :466, :528, :557; get_embedding calls :404-405
```

### Does NOT Exist
- ~~`IncrementalPersistence` in dev today (TASK-4302 creates it)~~
- ~~a builder-level pgvector writer~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_builder_protocols.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py#GraphIndexBuilder"
  ]
}
```

---

## Implementation Notes

Annotation-only imports go under `TYPE_CHECKING`. The `isinstance` swap must keep behaviour for backends without staleness (skip the check).

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Swap imports for Protocols (TYPE_CHECKING where annotation-only) — *why*: G2, no framework import at module level.
2. Replace the hasattr probe — *why*: G7, capabilities are explicit.
3. Add the EmbeddingPersistence hand-off after embedding — *why*: S8, durable vectors live in the backend.
4. Retype signals/retriever — *why*: consistency; no runtime change.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.pageindex.toolkit import PageIndexToolkit' parrot/knowledge/graphindex/builder.py)
# AFTER/AT — anchor `from parrot.knowledge.pageindex.toolkit import PageIndexToolkit` (verified: builder.py:55)
# REMOVE this import and `from parrot.knowledge.graphindex.embed import GraphIndexEmbedder` (:34); ADD:
from parrot.knowledge.graphindex.protocols import EmbeddingPersistence, IncrementalPersistence
if TYPE_CHECKING:
    from parrot.knowledge.graphindex.protocols import Embedder, PageIndexer
# In __init__ (:116-123): embedder: "Embedder", pageindex_toolkit: "PageIndexer | None" = None
# FILL IN: after embedding, `if isinstance(self.persistence, EmbeddingPersistence) and hasattr(self.embedder, 'vectors'):`
#           `await self.persistence.upsert_embeddings(ctx, self.embedder.vectors())`
```
**Why**: Builder depends on contracts only; the concrete classes are injected by factory/loader.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'if hasattr(self.persistence, "is_stale"):' parrot/knowledge/graphindex/builder.py)
# AFTER/AT — anchor `if hasattr(self.persistence, "is_stale"):` (verified: builder.py:505)
# REPLACE with:
                        if isinstance(self.persistence, IncrementalPersistence):
```
**Why**: Capability check replaces duck-typing (G7).

### `packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'embedder: Optional["GraphIndexEmbedder"],' parrot/knowledge/graphindex/signals.py)
# AFTER/AT — anchor `embedder: Optional["GraphIndexEmbedder"],` (verified: signals.py:395)
# REPLACE `Optional["GraphIndexEmbedder"]` with `Optional["Embedder"]` at all four sites (:395, :466, :528, :557)
# and add under TYPE_CHECKING: from parrot.knowledge.graphindex.protocols import Embedder
```
**Why**: Annotations only; `get_embedding` is part of `Embedder`.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'raw: list[tuple[str, float]] = await self.embedder.search_similar(' parrot/knowledge/graphindex/retriever.py)
# AFTER/AT — anchor `raw: list[tuple[str, float]] = await self.embedder.search_similar(` (verified: retriever.py:321)
# The call is unchanged; FILL IN: retype the `embedder` attribute/parameter that this method reads to "Embedder" (TYPE_CHECKING import)
```
**Why**: `search_similar` is positional-only in the Protocol so both `query_text` and `query` implementations match.

### `packages/ai-parrot/tests/knowledge/graphindex/test_builder_protocols.py` (CREATE)
```python
"""GraphIndexBuilder against Protocol doubles (FEAT-540 M2)."""
import pytest


class _Embedder:
    async def embed_nodes(self, nodes, batch_size=64): return nodes
    def get_embedding(self, node_id): return None
    async def search_similar(self, query, /, top_k=10): return []
    def vectors(self): return {}


@pytest.mark.asyncio
async def test_builder_runs_with_protocol_doubles(tmp_path) -> None:
    # FILL IN: build a tiny source tree; fake persistence without is_stale; assert build() completes
    ...


@pytest.mark.asyncio
async def test_embedding_persistence_receives_vectors(tmp_path) -> None:
    # FILL IN: fake persistence implementing upsert_embeddings records the call
    ...
```
**Why**: Typed doubles, not attribute presence (spec §7).

### FILL IN checklist
- [ ] EmbeddingPersistence hand-off placement in `build()`
- [ ] retriever attribute annotation
- [ ] both builder tests

---

## Acceptance Criteria

- [ ] `builder.py` imports neither `GraphIndexEmbedder` nor `PageIndexToolkit` at module level
- [ ] no `hasattr(self.persistence, "is_stale")` left
- [ ] existing builder/retriever/signals tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_builder_protocols.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_builder.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_signals.py -q`

---

## Test Specification

```python
# see test_builder_protocols.py block
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
9. **Close** with `scripts/sdd/close_task.sh TASK-4304 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
