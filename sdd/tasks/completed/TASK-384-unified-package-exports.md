# TASK-384: Unified Memory Package Exports

**Feature**: long-term-memory
**Spec**: `sdd/specs/long-term-memory.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-380, TASK-381, TASK-382, TASK-383
**Assigned-to**: unassigned

---

## Context

This task finalizes the `parrot/memory/unified/` package (Module 5 from the spec) by setting up proper `__init__.py` exports and updating the parent `parrot/memory/__init__.py` to include the unified components.

---

## Scope

- Update `parrot/memory/unified/__init__.py` with public exports:
  - `UnifiedMemoryManager`
  - `ContextAssembler`
  - `LongTermMemoryMixin`
  - `MemoryContext`
  - `MemoryConfig`
- Update `parrot/memory/__init__.py` to import and re-export unified components
- Write a simple import smoke test

**NOT in scope**: Modifying any implementation files, bot integration (TASK-385)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/unified/__init__.py` | MODIFY | Add public exports |
| `parrot/memory/__init__.py` | MODIFY | Add unified imports to `__all__` |
| `tests/memory/unified/test_imports.py` | CREATE | Import smoke tests |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/memory/unified/__init__.py
from .models import MemoryContext, MemoryConfig
from .context import ContextAssembler
from .manager import UnifiedMemoryManager
from .mixin import LongTermMemoryMixin

__all__ = [
    "MemoryContext",
    "MemoryConfig",
    "ContextAssembler",
    "UnifiedMemoryManager",
    "LongTermMemoryMixin",
]
```

### Key Constraints
- Follow the same export pattern as `parrot/memory/episodic/__init__.py`
- Only export public API — no internal helpers
- Parent `__init__.py` update must not break existing imports

### References in Codebase
- `parrot/memory/__init__.py` — existing exports
- `parrot/memory/episodic/__init__.py` — export pattern to follow

---

## Acceptance Criteria

- [ ] `from parrot.memory.unified import UnifiedMemoryManager, LongTermMemoryMixin` works
- [ ] `from parrot.memory import UnifiedMemoryManager, LongTermMemoryMixin` works
- [ ] Existing imports from `parrot.memory` are not broken
- [ ] All tests pass: `pytest tests/memory/unified/test_imports.py -v`

---

## Test Specification

```python
# tests/memory/unified/test_imports.py
def test_unified_package_imports():
    from parrot.memory.unified import (
        UnifiedMemoryManager,
        ContextAssembler,
        LongTermMemoryMixin,
        MemoryContext,
        MemoryConfig,
    )
    assert UnifiedMemoryManager is not None
    assert ContextAssembler is not None
    assert LongTermMemoryMixin is not None

def test_parent_package_imports():
    from parrot.memory import UnifiedMemoryManager, LongTermMemoryMixin
    assert UnifiedMemoryManager is not None

def test_existing_imports_not_broken():
    from parrot.memory import (
        ConversationMemory,
        ConversationHistory,
        ConversationTurn,
        InMemoryConversation,
        RedisConversation,
        EpisodicMemoryMixin,
        EpisodicMemoryStore,
    )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/long-term-memory.spec.md` for full context
2. **Check dependencies** — verify TASK-380 through TASK-383 are completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-384-unified-package-exports.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-23
**Notes**: Updated both `__init__.py` files. Full unified suite: 49/49 tests pass.

**Deviations from spec**: none
