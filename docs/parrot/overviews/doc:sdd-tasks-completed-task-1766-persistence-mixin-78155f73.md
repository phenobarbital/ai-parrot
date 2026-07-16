---
type: Wiki Overview
title: 'TASK-1766: PersistenceMixin Save Path Enhancement'
id: doc:sdd-tasks-completed-task-1766-persistence-mixin-save-enhancement-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The original prompt/query and tenant are NOT captured. This task ensures
  `prompt`
relates_to:
- concept: mod:parrot.bots.flows.core.storage.backends.postgres
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.persistence
  rel: mentions
---

# TASK-1766: PersistenceMixin Save Path Enhancement

**Feature**: FEAT-306 — AgentCrew Saved Crews (Execution Persistence & Replay)
**Spec**: `sdd/specs/agentcrew-saved-crews.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`PersistenceMixin._save_result()` builds a document with `crew_name`, `method`,
`timestamp`, and `result`, plus any `**kwargs` (currently `user_id` and `session_id`).
The original prompt/query and tenant are NOT captured. This task ensures `prompt`
and `tenant` are included in the persisted document so downstream read/replay
operations can access them.

Implements spec Module 5. Can run in parallel with TASK-1765 (no shared files).

---

## Scope

- Update `PersistenceMixin._save_result()` to include `prompt` and `tenant`
  in the persisted document. These arrive via `**kwargs` from callers.
- The method should extract `prompt` and `tenant` from kwargs and place them
  as top-level keys in the `data` dict (alongside `crew_name`, `method`, etc.).
- Default `tenant` to `"global"` if not provided.
- Default `prompt` to `None` if not provided (backwards compatible).
- Update `_NAMED_COLUMNS` in `postgres.py` to include `"tenant"` and `"prompt"`
  so `save()` extracts them as top-level columns instead of burying them in `payload`.

**NOT in scope**: Modifying `AgentCrew.run_*` callers (see TASK-1771).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/persistence.py` | MODIFY | Add prompt/tenant extraction to _save_result |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py` | MODIFY | Update _NAMED_COLUMNS, update _ensure_table DDL |
| `tests/unit/test_persistence_mixin_save.py` | CREATE | Tests for prompt/tenant in saved documents |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.storage.persistence import PersistenceMixin  # persistence.py:29
from parrot.bots.flows.core.storage.backends.postgres import PostgresResultStorage  # postgres.py:23
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/persistence.py:29
class PersistenceMixin:
    async def _save_result(
        self, result: Any, method: str, *,
        collection: str = "crew_executions", **kwargs: Any,
    ) -> None: ...  # line 65
    # Builds document: {"crew_name", "method", "timestamp", "result", **kwargs}
    # kwargs.setdefault("user_id", "unknown") at line 101

# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py:20
_NAMED_COLUMNS = frozenset(("crew_name", "method", "user_id", "session_id", "timestamp"))
# Used at line 107: payload_dict = {k: v for k, v in document.items() if k not in _NAMED_COLUMNS}

# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py:53
async def _ensure_table(self, conn: AsyncDB, table: str) -> None:
    # DDL at lines 66-76: CREATE TABLE IF NOT EXISTS with columns:
    # id uuid, crew_name text, method text, user_id text, session_id text,
    # timestamp timestamptz, payload jsonb

# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py:85
async def save(self, collection: str, document: dict[str, Any]) -> None:
    # Extracts crew_name, method, user_id, session_id, timestamp from document
    # Everything else goes into payload jsonb
    # INSERT at lines 113-123
```

### Does NOT Exist
- ~~`PersistenceMixin._save_result(prompt=...)`~~ — prompt is not currently passed; goes through **kwargs but no caller uses it yet
- ~~`_NAMED_COLUMNS` includes "tenant" or "prompt"~~ — currently only 5 columns
- ~~`crew_executions.tenant` column~~ — does not exist in the table DDL yet
- ~~`crew_executions.prompt` column~~ — does not exist in the table DDL yet

---

## Implementation Notes

### Pattern to Follow

In `_save_result()`, add explicit handling for `prompt` and `tenant`:
```python
data: dict[str, Any] = {
    "crew_name": getattr(self, "name", "unknown"),
    "method": method,
    "timestamp": time.time(),
    "result": (
        result.to_dict() if hasattr(result, "to_dict") else str(result)
    ),
    **kwargs,
}
data.setdefault("user_id", "unknown")
data.setdefault("tenant", "global")
# prompt comes from kwargs if caller provides it; no default needed (None is fine)
```

In `postgres.py`, update `_NAMED_COLUMNS`:
```python
_NAMED_COLUMNS = frozenset(("crew_name", "method", "user_id", "session_id", "timestamp", "tenant", "prompt"))
```

In `_ensure_table()`, add idempotent DDL for the new columns:
```python
# After CREATE TABLE IF NOT EXISTS:
await conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant TEXT NOT NULL DEFAULT 'global'")
await conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS prompt TEXT")
await conn.execute(f"CREATE INDEX IF NOT EXISTS {table}_tenant_user_idx ON {table} (tenant, user_id)")
```

In `save()`, extract tenant and prompt alongside the other named columns:
```python
tenant = document.get("tenant", "global")
prompt = document.get("prompt")
# Update INSERT to include tenant and prompt
```

### Key Constraints
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` requires PostgreSQL 9.6+
- The `tenant` column default is `'global'` — existing rows get this via DEFAULT
- The `prompt` column is nullable — legacy records will have NULL

---

## Acceptance Criteria

- [ ] `_save_result()` includes `tenant` (default `"global"`) and `prompt` in document
- [ ] `_NAMED_COLUMNS` includes `"tenant"` and `"prompt"`
- [ ] `_ensure_table()` adds `tenant` and `prompt` columns idempotently
- [ ] `_ensure_table()` creates composite index on `(tenant, user_id)`
- [ ] `save()` extracts and inserts `tenant` and `prompt` as top-level columns
- [ ] Existing callers that don't pass prompt/tenant continue working
- [ ] Tests verify prompt and tenant persistence
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_persistence_mixin_save.py
import pytest
import time
from unittest.mock import AsyncMock, MagicMock


class TestPersistenceMixinSaveEnhancement:
    async def test_save_result_includes_tenant_default(self):
        """tenant defaults to 'global' when not provided."""
        # Mock storage, call _save_result, verify document has tenant='global'

    async def test_save_result_includes_tenant_explicit(self):
        """tenant is included when explicitly passed."""
        # Call _save_result(... tenant="acme"), verify document

    async def test_save_result_includes_prompt(self):
        """prompt is included when passed via kwargs."""
        # Call _save_result(... prompt="Analyze trends"), verify document

    async def test_save_result_prompt_none_when_not_provided(self):
        """prompt is absent/None when not provided (backwards compat)."""

    async def test_named_columns_includes_tenant_and_prompt(self):
        """_NAMED_COLUMNS frozenset includes tenant and prompt."""
        from parrot.bots.flows.core.storage.backends.postgres import _NAMED_COLUMNS
        assert "tenant" in _NAMED_COLUMNS
        assert "prompt" in _NAMED_COLUMNS
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm _save_result signature and _NAMED_COLUMNS
4. **Update status** in `sdd/tasks/index/agentcrew-saved-crews.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1766-persistence-mixin-save-enhancement.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: `_save_result()` now does `data.setdefault("tenant", "global")`; `prompt`
flows through unchanged via `**kwargs` (no default needed — absent key reads as
`None` downstream). `_NAMED_COLUMNS` in `postgres.py` extended with `"tenant"` and
`"prompt"`. `_ensure_table()` issues idempotent `ALTER TABLE ... ADD COLUMN IF NOT
EXISTS` for both columns plus `CREATE INDEX IF NOT EXISTS {table}_tenant_user_idx
ON {table} (tenant, user_id)`, applied after `CREATE TABLE IF NOT EXISTS` so it
covers both brand-new and pre-existing tables. `save()` now extracts `tenant`
(default `"global"`) and `prompt` and includes them in the `INSERT` column list
ahead of `payload`. Created `tests/unit/test_persistence_mixin_save.py` per the
task's Test Specification (5 tests, reusing the `_FakeStorage`/`_Host` pattern
from `tests/bots/flows/core/storage/test_persistence_mixin.py`).

**Deviations from spec**: One necessary collateral fix — the pre-existing
`tests/bots/flows/core/storage/test_postgres_backend.py::test_postgres_wraps_bare_string_result`
hardcoded the `payload` arg's positional index in the `INSERT` call
(`insert_call.args[6]`). Adding `tenant`/`prompt` to the column list shifted
`payload` to `args[8]`; updated the index and added a comment. No behavioral
change to the test's intent, and all 26 relevant tests pass (unit + persistence
+ postgres backend + ABC).
