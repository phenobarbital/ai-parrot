---
type: Wiki Overview
title: 'TASK-1244: Core Package Mirror Update'
id: doc:sdd-tasks-completed-task-1244-core-package-mirror-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `parrot.forms` core package contains fallback copies of `FormStorage`,
relates_to:
- concept: mod:parrot.forms
  rel: mentions
- concept: mod:parrot.forms.registry
  rel: mentions
- concept: mod:parrot.forms.schema
  rel: mentions
- concept: mod:parrot.forms.storage
  rel: mentions
- concept: mod:parrot.forms.style
  rel: mentions
---

# TASK-1244: Core Package Mirror Update

**Feature**: FEAT-185 — Refactor FormRegistry
**Spec**: `sdd/specs/refactor-formregistry.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1242, TASK-1243
**Assigned-to**: unassigned

---

## Context

The `parrot.forms` core package contains fallback copies of `FormStorage`,
`FormRegistry`, and `PostgresFormStorage` used when `parrot-formdesigner` is
not installed. These copies must mirror the interface changes made by
TASK-1242 and TASK-1243 to keep the core package consistent.

Implements spec §3 Modules 4 and 5.

---

## Scope

- **`packages/ai-parrot/src/parrot/forms/registry.py`**:
  - Add `async def close(self) -> None` (default no-op) to `FormStorage`.
  - Add `app: web.Application | None = None` parameter to `FormRegistry.__init__`.
  - Add `on_startup` / `on_shutdown` methods mirroring TASK-1242.
  - Keep existing simpler signatures (no `tenant` parameter on `FormStorage`
    methods — the core version is deliberately simpler).
- **`packages/ai-parrot/src/parrot/forms/storage.py`**:
  - Refactor `PostgresFormStorage.__init__` to accept optional `pool` (can be None).
  - Add `dsn`, `min_size`, `max_size`, `**pool_kwargs` parameters.
  - Add `_owns_pool` flag.
  - Update `initialize()` to create pool if none provided.
  - Add `async def close()`.
  - Keep the class-level SQL constants (don't switch to dynamic schema).

**NOT in scope**: parrot-formdesigner package (TASK-1242, TASK-1243),
call-site changes (TASK-1245), tests (TASK-1246).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/registry.py` | MODIFY | Add `close()` to `FormStorage`, refactor `FormRegistry.__init__` + signals |
| `packages/ai-parrot/src/parrot/forms/storage.py` | MODIFY | Refactor constructor, add pool creation + `close()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/forms/registry.py
from parrot.forms.registry import FormStorage   # verified: forms/registry.py:29
from parrot.forms.registry import FormRegistry  # verified: forms/registry.py:94
from parrot.forms.schema import FormSchema      # verified via registry.py:21
from parrot.forms.style import StyleSchema      # verified via registry.py:22

# packages/ai-parrot/src/parrot/forms/storage.py
from parrot.forms.storage import PostgresFormStorage  # verified: forms/storage.py:39
from parrot.forms.registry import FormStorage         # verified via storage.py:29
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/forms/registry.py
class FormStorage(ABC):                                    # line 29
    @abstractmethod
    async def save(self, form, style=None) -> str:         # line 39
    @abstractmethod
    async def load(self, form_id, version=None):           # line 55
    @abstractmethod
    async def delete(self, form_id) -> bool:               # line 73
    @abstractmethod
    async def list_forms(self) -> list[dict[str, str]]:    # line 85

class FormRegistry:                                        # line 94
    def __init__(self, storage: FormStorage | None = None) -> None:  # line 111
    _forms: dict[str, FormSchema]                          # line 117
    _lock: asyncio.Lock                                    # line 118
    _storage: FormStorage | None                           # line 119
    async def load_from_storage(self) -> int:              # line 290

# packages/ai-parrot/src/parrot/forms/storage.py
class PostgresFormStorage(FormStorage):                    # line 39
    CREATE_TABLE_SQL: str                                  # line 58 (class-level constant)
    UPSERT_SQL: str                                        # line 72
    LOAD_SQL: str                                          # line 82
    def __init__(self, pool: Any) -> None:                 # line 106
    _pool: Any                                             # line 112
    async def initialize(self) -> None:                    # line 115
```

### Does NOT Exist

- ~~`FormStorage.close()`~~ — does not exist in core; you are adding it
- ~~`FormRegistry.on_startup`~~ — does not exist in core; you are adding it
- ~~`FormRegistry._app`~~ — does not exist in core; you are adding it
- ~~`PostgresFormStorage.close()`~~ — does not exist in core; you are adding it
- ~~`PostgresFormStorage._owns_pool`~~ — does not exist in core; you are adding it
- ~~`parrot.forms.registry.FormAlreadyExistsError`~~ — does NOT exist in the core copy (only in parrot-formdesigner)

---

## Implementation Notes

### Pattern to Follow

Mirror the exact same changes from TASK-1242 and TASK-1243, but adapted to
the simpler core signatures:
- Core `FormStorage` methods do NOT have `tenant` parameters.
- Core `PostgresFormStorage` uses class-level SQL constants — keep them.
- Core `FormRegistry` does NOT have `clone_form`, `set_storage`, etc.

### Key Constraints

- The core package is a fallback. It doesn't need feature parity with
  parrot-formdesigner — just interface parity for the constructor/lifecycle.
- `aiohttp` import must be TYPE_CHECKING guarded (same as TASK-1242).
- Keep the `import asyncpg` under TYPE_CHECKING as it already is (line 33).

---

## Acceptance Criteria

- [ ] Core `FormStorage` has `async def close(self) -> None` (no-op)
- [ ] Core `FormRegistry.__init__` accepts `app: web.Application | None = None`
- [ ] Core `FormRegistry` has `on_startup` / `on_shutdown` methods
- [ ] Core `PostgresFormStorage` can be constructed without `pool`
- [ ] Core `PostgresFormStorage.initialize()` creates pool when none provided
- [ ] Core `PostgresFormStorage.close()` closes self-owned pool
- [ ] `from parrot.forms import FormRegistry, PostgresFormStorage` still works
- [ ] No breaking changes to the fallback `__init__.py` re-export shim

---

## Test Specification

```python
import pytest
from parrot.forms.registry import FormRegistry, FormStorage
from parrot.forms.storage import PostgresFormStorage


async def test_core_registry_no_app():
    registry = FormRegistry()
    assert len(registry) == 0


async def test_core_storage_no_pool():
    storage = PostgresFormStorage(schema="test")
    assert storage._pool is None
    assert storage._owns_pool is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read** TASK-1242 and TASK-1243 completed files to see what changed
2. **Mirror** the interface changes in the core package files
3. **Verify** backward compat of `parrot/forms/__init__.py` re-exports
4. **Move this file** to `sdd/tasks/completed/TASK-1244-core-package-mirror.md`
5. **Update index** → `"done"`

---

## Completion Note

**Completed by**: SDD Worker (claude-sonnet-4-6)
**Date**: 2026-05-19
**Notes**: Mirrored all TASK-1242/1243 changes to core package. Added `close()` no-op to core `FormStorage`. Updated core `FormRegistry.__init__` to accept `app` param, added `on_startup`/`on_shutdown` handlers. Updated core `PostgresFormStorage.__init__` to keyword-only with `pool`/`dsn` params, added `_owns_pool` flag, updated `initialize()` to create pool, added `close()`. Kept class-level SQL constants as per spec.

**Deviations from spec**: none
