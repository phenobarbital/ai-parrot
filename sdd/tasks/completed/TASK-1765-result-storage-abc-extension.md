# TASK-1765: ResultStorage ABC Extension

**Feature**: FEAT-307 — AgentCrew Saved Crews (Execution Persistence & Replay)
**Spec**: `sdd/specs/agentcrew-saved-crews.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The `ResultStorage` ABC (FEAT-147) currently only defines `save()` and `close()`.
This task adds read methods (`list`, `get`, `delete`, `count`) as abstract methods
with default `NotImplementedError` implementations so existing backends don't break.
This is the foundation that all backend-specific tasks (TASK-1768, 1769, 1770) depend on.

Implements spec Module 1.

---

## Scope

- Add four new abstract methods to `ResultStorage`:
  - `async def list(self, collection, filters=None, limit=20, offset=0) -> list[dict]`
  - `async def get(self, collection, record_id) -> Optional[dict]`
  - `async def delete(self, collection, record_id) -> bool`
  - `async def count(self, collection, filters=None) -> int`
- Each method gets a default implementation that raises `NotImplementedError` with
  a descriptive message (e.g., `f"{type(self).__name__} does not support list()"`)
  so subclasses that don't override them fail gracefully.
- Update `__all__` in `backends/__init__.py` if needed (no new exports expected).
- Write unit tests verifying the ABC contract.

**NOT in scope**: Implementing the methods in any concrete backend (see TASK-1768–1770).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/base.py` | MODIFY | Add list, get, delete, count methods |
| `tests/unit/test_result_storage_abc.py` | CREATE | Unit tests for ABC contract |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.storage.backends.base import ResultStorage  # backends/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/base.py:8
class ResultStorage(ABC):
    @abstractmethod
    async def save(self, collection: str, document: dict[str, Any]) -> None: ...  # line 18
    @abstractmethod
    async def close(self) -> None: ...  # line 27
```

### Does NOT Exist
- ~~`ResultStorage.list()`~~ — does not exist yet; this task creates it
- ~~`ResultStorage.get()`~~ — does not exist yet
- ~~`ResultStorage.delete()`~~ — does not exist yet
- ~~`ResultStorage.count()`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
The new methods should NOT be `@abstractmethod` — they should be regular `async def`
methods with a default `raise NotImplementedError(...)`. This preserves backwards
compatibility: existing backends that only implement `save()` and `close()` continue
to work. Backends that want read support override these methods.

```python
async def list(
    self,
    collection: str,
    filters: dict[str, Any] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    raise NotImplementedError(
        f"{type(self).__name__} does not support list()"
    )
```

### Key Constraints
- Must be async throughout
- Type hints using `dict[str, Any]` (PEP 585 style, matching existing code)
- `filters` is a plain dict (not a Pydantic model) at the storage layer
- `record_id` is `str` (UUID as string)
- Imports: `from typing import Any, Optional` (match existing file imports)

---

## Acceptance Criteria

- [ ] `ResultStorage` defines `list`, `get`, `delete`, `count` methods
- [ ] Default implementations raise `NotImplementedError` with backend class name
- [ ] Existing `save()` and `close()` abstract methods unchanged
- [ ] Tests verify ABC contract and default NotImplementedError behavior
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/base.py`
- [ ] Import works: `from parrot.bots.flows.core.storage.backends.base import ResultStorage`

---

## Test Specification

```python
# tests/unit/test_result_storage_abc.py
import pytest
from parrot.bots.flows.core.storage.backends.base import ResultStorage


class ConcreteStorage(ResultStorage):
    """Minimal concrete subclass for testing."""
    async def save(self, collection, document):
        pass
    async def close(self):
        pass


@pytest.fixture
def storage():
    return ConcreteStorage()


class TestResultStorageABC:
    async def test_list_raises_not_implemented(self, storage):
        with pytest.raises(NotImplementedError, match="ConcreteStorage"):
            await storage.list("test_collection")

    async def test_get_raises_not_implemented(self, storage):
        with pytest.raises(NotImplementedError, match="ConcreteStorage"):
            await storage.get("test_collection", "some-id")

    async def test_delete_raises_not_implemented(self, storage):
        with pytest.raises(NotImplementedError, match="ConcreteStorage"):
            await storage.delete("test_collection", "some-id")

    async def test_count_raises_not_implemented(self, storage):
        with pytest.raises(NotImplementedError, match="ConcreteStorage"):
            await storage.count("test_collection")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `ResultStorage` still has only `save()` and `close()`
4. **Update status** in `sdd/tasks/index/agentcrew-saved-crews.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1765-result-storage-abc-extension.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Added `list`, `get`, `delete`, `count` as regular (non-abstract) `async def`
methods on `ResultStorage`, each raising `NotImplementedError(f"{type(self).__name__} does
not support X()")` by default, preserving backwards compatibility with `save()`/`close()`
unchanged. Created `tests/unit/test_result_storage_abc.py` exactly per the task's Test
Specification (4 tests, all passing). Verified no regressions in
`tests/bots/flows/core/storage/test_base.py` and `test_persistence_mixin.py` (14/14 passing).
`ruff check` clean on both touched files.

**Deviations from spec**: none
