# TASK-1930: Core models — `SearchOriginKind`, payload models & `MultiSearch` protocol

**Feature**: FEAT-379 — MultiStoreSearch Toolkit with PageIndex, GraphIndex & ParrotWiki Origins
**Spec**: `sdd/specs/multistoresearchtool-parrotwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1 and the protocol half of Module 2. All FEAT-379
core types live in ONE module — `parrot/models/stores.py` — so that both core
consumers (`StoreRouter`, `AbstractBot`) and the `ai-parrot-tools` package
import only from `parrot.models` (resolved decision: `parrot/interfaces/` is
external-service interfaces and is NOT the protocol home).

---

## Scope

- Add `SearchOriginKind` enum (`VECTOR`, `PAGEINDEX`, `GRAPHINDEX`, `WIKI`) to
  `parrot/models/stores.py`. Do NOT touch `StoreType`.
- Add Pydantic models `OriginHit`, `OriginSection`, `MultiSearchResponse`
  exactly as designed in spec §2 Data Models (field names/semantics are
  contractual; `score` is origin-native and NOT cross-origin comparable —
  document that in the field description).
- Add the runtime-checkable `MultiSearch` protocol
  (`async def search(self, query: str, k: Optional[int] = None, **kwargs) -> Any`)
  in the same module, decorated with `@runtime_checkable`.
- Export all new names from `parrot/models/__init__.py` (follow how
  `StoreType` / `SearchResult` are currently exported).
- Write unit tests.

**NOT in scope**: StoreRouter/AbstractBot changes (TASK-1931); any code in
`packages/ai-parrot-tools/` (TASK-1932+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/stores.py` | MODIFY | Add enum, 3 payload models, `MultiSearch` protocol |
| `packages/ai-parrot/src/parrot/models/__init__.py` | MODIFY | Export new names |
| `packages/ai-parrot/tests/unit/models/test_search_origin_models.py` | CREATE | Unit tests (create dir if missing; check existing test layout first) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import StoreType           # verified: used at parrot_tools/multistoresearch.py:29
from parrot.models.stores import SearchResult # verified: used at parrot_tools/multistoresearch.py:30
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/stores.py
class StoreType(Enum):        # line 23 — PGVECTOR="pgvector", FAISS="faiss", ARANGO="arango". DO NOT EXTEND.
class SearchResult(BaseModel):  # line 31
    id: str; content: str; metadata: Dict[str, Any]; score: float
    # score: lower = closer for distance metrics (see docstring in file)
```

### New models to add (from spec §2 — names are contractual)
```python
class SearchOriginKind(Enum):
    VECTOR = "vector"; PAGEINDEX = "pageindex"; GRAPHINDEX = "graphindex"; WIKI = "wiki"

class OriginHit(BaseModel):
    id: Optional[str]; content: str; score: Optional[float]
    metadata: dict[str, Any]; origin: str
    origin_kind: SearchOriginKind; native_rank: int  # 1-based

class OriginSection(BaseModel):
    origin: str; origin_kind: SearchOriginKind; description: str
    status: str  # "ok" | "error" | "timeout" | "skipped"
    note: Optional[str]; hits: list[OriginHit]

class MultiSearchResponse(BaseModel):
    query: str; sections: list[OriginSection]
    merged_top_k: list[OriginHit]; notes: list[str]

@runtime_checkable
class MultiSearch(Protocol):
    async def search(self, query: str, k: Optional[int] = None, **kwargs) -> Any: ...
```

### Does NOT Exist
- ~~`StoreType.PAGEINDEX` / `StoreType.GRAPHINDEX` / `StoreType.WIKI`~~ — must NOT be added; the new enum `SearchOriginKind` covers origin kinds.
- ~~`parrot/interfaces/search.py`~~ — must NOT be created (decision: protocol lives in `parrot/models/stores.py`).
- ~~`SearchOriginKind` / `OriginHit` / `OriginSection` / `MultiSearchResponse` / `MultiSearch`~~ — do not exist yet; THIS task creates them.

---

## Implementation Notes

### Key Constraints
- Pydantic v2 style consistent with `SearchResult` in the same file (read the
  file's existing conventions — computed alias on `SearchResult.score` is a
  reference pattern).
- `typing.Protocol` + `typing.runtime_checkable` from stdlib `typing`.
- Google-style docstrings on everything; the model docstrings state the
  score-comparability caveat.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/stores.py` — the ONLY implementation file (plus `__init__` export).
- Spec §2 "Data Models" and "New Public Interfaces" — authoritative shapes.

---

## Acceptance Criteria

- [ ] `from parrot.models import SearchOriginKind, OriginHit, OriginSection, MultiSearchResponse, MultiSearch` works.
- [ ] `StoreType` members unchanged (test asserts exactly {PGVECTOR, FAISS, ARANGO}).
- [ ] `isinstance(obj, MultiSearch)` is True for any object with an async `search` method, False otherwise (runtime_checkable test).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/models/test_search_origin_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/stores.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/models/test_search_origin_models.py
import pytest
from parrot.models import (
    SearchOriginKind, OriginHit, OriginSection, MultiSearchResponse, MultiSearch, StoreType,
)

def test_store_type_unchanged():
    assert {m.name for m in StoreType} == {"PGVECTOR", "FAISS", "ARANGO"}

def test_origin_kind_values():
    assert {k.value for k in SearchOriginKind} == {"vector", "pageindex", "graphindex", "wiki"}

def test_origin_hit_validation():
    hit = OriginHit(id="1", content="x", score=0.5, metadata={},
                    origin="pgvector", origin_kind=SearchOriginKind.VECTOR, native_rank=1)
    assert hit.native_rank == 1

def test_multisearch_protocol_runtime_check():
    class Ok:
        async def search(self, query, k=None, **kw): ...
    class NotOk: ...
    assert isinstance(Ok(), MultiSearch)
    assert not isinstance(NotOk(), MultiSearch)
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/multistoresearchtool-parrotwiki.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-07-27
**Notes**: Added `SearchOriginKind`, `OriginHit`, `OriginSection`,
`MultiSearchResponse`, and the `@runtime_checkable` `MultiSearch` protocol
to `parrot/models/stores.py`, exported from `parrot/models/__init__.py`.
`StoreType` left untouched. 7 unit tests added in
`packages/ai-parrot/tests/unit/models/test_search_origin_models.py`, all
passing; `ruff check` clean.

Note: before starting this task, 9 stale/bogus task-file stubs for this
same feature (unedited templates, no implementation) were found
misplaced under `sdd/tasks/completed/` — an artifact of an unrelated
devloop-enhancement (FEAT-378) test-fixture merge that collided on this
feature's name. They were moved back to `sdd/tasks/active/` (commit
"sdd: repair FEAT-379 task-file placement") before any real work began.

**Deviations from spec**: none
