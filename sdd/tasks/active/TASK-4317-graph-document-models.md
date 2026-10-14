# TASK-4317: GraphDocument / DocumentLoader shapes; extractors stop importing parrot.stores

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 M6. `graphindex/extractors/loader.py:38` imports `parrot.stores.models.Document`; the extractor only reads `page_content` and `metadata`.

---

## Scope

- Create `graphindex/models.py` with `GraphDocument` and the `DocumentLoader` Protocol (spec §2 Data Models).
- `extractors/loader.py`: type against `GraphDocument`/`DocumentLoader`; drop the stores import (keep the ebook helper's local lazy import at :198).
- Tests: extractor runs on a plain `DocumentLoader` double returning `GraphDocument`s.

**NOT in scope**: Framework ↔ GraphDocument conversion and loader relocation (TASK-4318).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/models.py` | CREATE | GraphDocument + DocumentLoader |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py` | MODIFY | retype |
| `packages/ai-parrot/tests/knowledge/graphindex/test_graph_document.py` | CREATE | extractor with plain loader |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.graphindex.schema import UniversalNode, UniversalEdge  # extractors/loader.py:31
```

### Existing Signatures to Use
```python
# extractors/loader.py: :38 from parrot.stores.models import Document; :42 TYPE_CHECKING EbookSection; :198 local `from parrot.loaders.ebook import ebook_sections`
# stores/models.py:19 class Document(BaseModel): page_content: str; metadata: Dict[str, Any]
```

### Does NOT Exist
- ~~`parrot.knowledge.graphindex.models` (created here; distinct from `wiki/models.py`)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_graph_document.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

Existing callers passing framework `Document`s keep working structurally (same two fields); typing is the change.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Create models — *why*: framework-free shape.
2. Retype extractor — *why*: G2.
3. Test with a plain loader.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/models.py` (CREATE)
```python
"""Framework-free document shapes for graphindex loaders (FEAT-540 M6)."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class GraphDocument(BaseModel):
    """page_content + metadata — the two fields graphindex reads from a loader document."""

    page_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class DocumentLoader(Protocol):
    """What the loader extractor needs: an async load() returning documents."""

    async def load(self) -> list[GraphDocument]: ...
```
**Why**: Verbatim from spec §2.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.stores.models import Document' parrot/knowledge/graphindex/extractors/loader.py)
# AFTER/AT — anchor `from parrot.stores.models import Document` (verified: loader.py:38)
# REPLACE with:
from parrot.knowledge.graphindex.models import DocumentLoader, GraphDocument
# FILL IN: retype every `Document` annotation to `GraphDocument` and loader params to `DocumentLoader`
```
**Why**: Structural typing keeps framework Documents compatible.

### `packages/ai-parrot/tests/knowledge/graphindex/test_graph_document.py` (CREATE)
```python
"""Extractor with a plain DocumentLoader (FEAT-540 M6)."""
import pytest

from parrot.knowledge.graphindex.models import GraphDocument


class _Loader:
    async def load(self):
        return [GraphDocument(page_content="# Title\nbody", metadata={"source": "x.md"})]


@pytest.mark.asyncio
async def test_extract_with_plain_loader() -> None:
    # FILL IN: call the extractor entry point with _Loader(); assert nodes produced
    ...
```
**Why**: Proves framework independence.

### FILL IN checklist
- [ ] annotation retyping
- [ ] extractor test body

---

## Acceptance Criteria

- [ ] `extractors/loader.py` no longer imports `parrot.stores`
- [ ] existing loader-extractor tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_graph_document.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py -q`

---

## Test Specification

```python
# see block
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
9. **Close** with `scripts/sdd/close_task.sh TASK-4317 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
