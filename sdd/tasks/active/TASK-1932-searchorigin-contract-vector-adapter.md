# TASK-1932: `SearchOrigin` adapter contract + `VectorStoreOrigin` adapter

**Feature**: FEAT-379 — MultiStoreSearch Toolkit with PageIndex, GraphIndex & ParrotWiki Origins
**Spec**: `sdd/specs/multistoresearchtool-parrotwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1930
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3: the adapter contract every origin implements,
plus the first concrete adapter wrapping duck-typed vector stores (pgvector /
FAISS / Arango). Creates the new package skeleton
`parrot_tools/multistoresearch/` that TASK-1933..1936 build on. The OLD
module `parrot_tools/multistoresearch.py` still exists at this point — the
new code lives in a package DIRECTORY of the same import name, so this task
must handle the module→package transition carefully (see Implementation Notes).

---

## Scope

- Create package `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/`
  with subpackage `origins/`.
- Implement `SearchOrigin` ABC in `origins/base.py` per spec §2:
  `name: str`, `kind: SearchOriginKind`, `description: str`,
  `supports_fts: bool`, `timeout: Optional[float]` (None → toolkit default),
  `async search(query, k) -> list[OriginHit]`,
  `async fts_search(query, k) -> list[OriginHit]` (default raises
  `NotImplementedError`; only meaningful when `supports_fts=True`).
- Implement `VectorStoreOrigin` in `origins/vector.py`: wraps ONE duck-typed
  store instance (`await store.similarity_search(query, limit=k)` →
  `list[SearchResult]`); constructor takes `store`, `name` (e.g. "pgvector"),
  `description` (default per-store explanation), optional `timeout`.
  FTS leg: `supports_fts=True` only when the wrapped store has a callable
  `fulltext_search` attribute (ArangoDB case), delegating to it.
- Normalize `SearchResult` → `OriginHit` (origin tag, 1-based `native_rank`,
  float score, metadata pass-through). Errors inside the store call are NOT
  swallowed here — isolation lives in the toolkit (TASK-1936); adapters raise.
- Unit tests with fake stores.

**NOT in scope**: PageIndex/GraphIndex/wiki adapters (TASK-1933/34/35);
toolkit (TASK-1936); deleting the old module (TASK-1937).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/__init__.py` | CREATE | Package init (exports contract + adapters as they land) |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py` | CREATE | Subpackage init |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py` | CREATE | `SearchOrigin` ABC |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py` | CREATE | `VectorStoreOrigin` |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch.py` | MOVE | `git mv` into the package as `multistoresearch/_legacy_tool.py` (see module→package collision note) |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/_legacy_tool.py` | CREATE (via move) | Unchanged old tool; `MultiStoreSearchTool` re-exported from package `__init__.py` until TASK-1937 |
| `packages/ai-parrot-tools/tests/multistoresearch/test_origins_base.py` | CREATE | Contract tests |
| `packages/ai-parrot-tools/tests/multistoresearch/test_vector_origin.py` | CREATE | Vector adapter tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import SearchOriginKind, OriginHit  # created by TASK-1930 — verify first
from parrot.models.stores import SearchResult           # packages/ai-parrot/src/parrot/models/stores.py:31
```

### Existing Signatures to Use
```python
# Duck-typed vector store surface (NO concrete imports — spec convention):
#   await store.similarity_search(query=..., limit=k) -> List[SearchResult]
# reference pattern: packages/ai-parrot-tools/src/parrot_tools/multistoresearch.py:105,134,163 (old tool)

# packages/ai-parrot-embeddings/src/parrot/stores/arango.py
class ArangoDBStore:
    async def fulltext_search(self, ...)   # line 754 — presence detected via getattr/callable, NEVER imported

# packages/ai-parrot/src/parrot/models/stores.py
class SearchResult(BaseModel):             # line 31
    id: str; content: str; metadata: Dict[str, Any]; score: float  # lower = closer for distance metrics
```

### Does NOT Exist
- ~~`PgVectorStore.fts_search`~~ / any Postgres FTS method — does not exist; Postgres FTS is out of scope (spec Non-Goal).
- ~~FAISS FTS~~ — impossible.
- ~~`parrot_tools.multistoresearch.MultiStoreSearchToolkit`~~ — created later by TASK-1936, not here.
- ~~`SearchOrigin` / `VectorStoreOrigin`~~ — do not exist yet; THIS task creates them.

---

## Implementation Notes

### Module→Package collision (IMPORTANT)
The old file `parrot_tools/multistoresearch.py` and the new directory
`parrot_tools/multistoresearch/` cannot coexist on the same import name.
**In this task, git-move the old file INTO the new package as
`_legacy_tool.py` (unchanged content, imports fixed if needed) and re-export
`MultiStoreSearchTool` + `MultiStoreSearchSchema` from the package
`__init__.py`** so the existing registry entry
(`"parrot_tools.multistoresearch.MultiStoreSearchTool"`, `__init__.py:119`)
and `StoreRouter` integration keep resolving until TASK-1937 deletes it.
Verify with: `python -c "from parrot_tools.multistoresearch import MultiStoreSearchTool"`.

### Key Constraints
- Async-first; Pydantic where structured; Google-style docstrings.
- Adapters RAISE on backend failure; the toolkit isolates (spec §2).
- No `parrot.stores.*` concrete imports at load time (duck-typing convention
  of the old tool is preserved).
- `OriginHit.native_rank` is the 1-based enumeration of the store's own order.

### References in Codebase
- Old tool `_search_pgvector/_search_faiss/_search_arango` (multistoresearch.py:94-179) — normalization/tagging reference (being replaced, do not copy error-swallowing).
- Spec §2 adapter table + "New Public Interfaces".

---

## Acceptance Criteria

- [ ] `from parrot_tools.multistoresearch.origins import SearchOrigin, VectorStoreOrigin` works.
- [ ] `from parrot_tools.multistoresearch import MultiStoreSearchTool` STILL works (legacy re-export until TASK-1937).
- [ ] `VectorStoreOrigin.search` returns `list[OriginHit]` with correct origin tag + native_rank; `supports_fts` True iff store exposes callable `fulltext_search`.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/multistoresearch/ -v`
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/multistoresearch/` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/multistoresearch/test_vector_origin.py
import pytest
from parrot.models import SearchOriginKind
from parrot.models.stores import SearchResult
from parrot_tools.multistoresearch.origins import VectorStoreOrigin

class FakeStore:
    async def similarity_search(self, query, limit=10):
        return [SearchResult(id=str(i), content=f"doc {i}", metadata={}, score=0.1 * i)
                for i in range(3)]

class FakeArango(FakeStore):
    async def fulltext_search(self, query, limit=10):
        return [SearchResult(id="f1", content="fts doc", metadata={}, score=1.0)]

async def test_search_normalizes_to_origin_hits():
    origin = VectorStoreOrigin(store=FakeStore(), name="pgvector")
    hits = await origin.search("q", k=3)
    assert [h.native_rank for h in hits] == [1, 2, 3]
    assert all(h.origin == "pgvector" and h.origin_kind == SearchOriginKind.VECTOR for h in hits)

async def test_fts_capability_detection():
    assert VectorStoreOrigin(store=FakeArango(), name="arango").supports_fts is True
    assert VectorStoreOrigin(store=FakeStore(), name="faiss").supports_fts is False

async def test_backend_error_propagates():
    class Boom:
        async def similarity_search(self, query, limit=10):
            raise RuntimeError("db down")
    with pytest.raises(RuntimeError):
        await VectorStoreOrigin(store=Boom(), name="pgvector").search("q", k=1)
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1930 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/multistoresearchtool-parrotwiki.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
