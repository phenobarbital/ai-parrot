# TASK-2062: Type Annotation Fixes (WikiStore → BaseWikiStore)

**Feature**: FEAT-400 — WikiToolkit ArangoDB Backend
**Spec**: `sdd/specs/wikitoolkit-arangodb-backend.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`WikiCombinedSearch` and `WikiIngestOrchestrator` use `WikiStore` (alias
for `SQLiteWikiStore`) in their type annotations instead of `BaseWikiStore`.
This causes type-checking issues when passing an `ArangoDBWikiStore` or
`InMemoryWikiStore`. Corresponds to Module 6 in the spec.

---

## Scope

- Change `store: Optional[WikiStore]` to `store: Optional[BaseWikiStore]`
  in `WikiCombinedSearch.__init__` (search.py).
- Change `store: Optional[WikiStore]` to `store: Optional[BaseWikiStore]`
  in `WikiIngestOrchestrator.__init__` (ingest.py).
- Update the imports in both files: replace `from parrot.knowledge.wiki.store import WikiStore`
  with `from parrot.knowledge.wiki.store import BaseWikiStore`.
- Verify no other files use the narrow `WikiStore` type where `BaseWikiStore` is needed.

**NOT in scope**:
- Any behavioral changes — this is annotation-only

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/search.py` | MODIFY | WikiStore → BaseWikiStore annotation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py` | MODIFY | WikiStore → BaseWikiStore annotation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# search.py current (line 29):
from parrot.knowledge.wiki.store import WikiStore  # → change to BaseWikiStore

# ingest.py current (line 39-40):
from parrot.knowledge.wiki.store import (
    WikiStore,  # → change to BaseWikiStore
    ...
)

# Both files should import:
from parrot.knowledge.wiki.store import BaseWikiStore  # verified: store.py:279
```

### Existing Signatures to Use

```python
# search.py:47-54
class WikiCombinedSearch:
    def __init__(self, ..., store: Optional[WikiStore] = None, ...) -> None: ...
    # ↑ change to Optional[BaseWikiStore]

# ingest.py:89-96
class WikiIngestOrchestrator:
    def __init__(self, ..., store: Optional[WikiStore] = None, ...) -> None: ...
    # ↑ change to Optional[BaseWikiStore]
```

### Does NOT Exist

- ~~`WikiStore` as a distinct class~~ — it's just an alias for `SQLiteWikiStore` (store.py:1194)

---

## Acceptance Criteria

- [ ] `WikiCombinedSearch.__init__` accepts any `BaseWikiStore` subclass
- [ ] `WikiIngestOrchestrator.__init__` accepts any `BaseWikiStore` subclass
- [ ] No runtime behavior change
- [ ] Existing tests still pass: `pytest tests/knowledge/wiki/ -v`
- [ ] `mypy` / `pyright` clean on both files

---

## Completion Note

*(Agent fills this in when done)*
