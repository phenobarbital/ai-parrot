---
type: Wiki Overview
title: 'TASK-1017: Rewrite PersistenceMixin and consolidate the legacy duplicate'
id: doc:sdd-tasks-completed-task-1017-persistence-mixin-rewrite-and-consolidation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Rewrites `PersistenceMixin` to delegate to `self._result_storage` (lazily
relates_to:
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.persistence
  rel: mentions
---

# TASK-1017: Rewrite PersistenceMixin and consolidate the legacy duplicate

**Feature**: FEAT-147 — Crew Result Storage Backends
**Spec**: `sdd/specs/crew-result-storage-backends.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1013, TASK-1014, TASK-1015, TASK-1016
**Assigned-to**: unassigned

---

## Context

Rewrites `PersistenceMixin` to delegate to `self._result_storage` (lazily
resolved via `get_result_storage`) and to honour `self._persist_results`
as an opt-out. Adds in-flight task tracking on `self._persist_tasks` and
exposes `aclose()` plus `__aenter__` / `__aexit__` so host classes can
release connections deterministically.

Also consolidates the two duplicated mixin files: deletes the legacy
copy at `parrot/bots/flow/storage/persistence.py` and drops its
re-export from `parrot/bots/flow/storage/__init__.py`. Per spec §1
Non-Goals, the rest of the legacy package stays untouched until the user
finishes reviewing out-of-tree consumers.

Implements spec §2 "Lifecycle & Cleanup" and §3 Module 5.

---

## Scope

- Rewrite `parrot/bots/flows/core/storage/persistence.py` so that
  `PersistenceMixin._save_result` becomes:
  - Early-return when `self._persist_results` is False.
  - Lazy-resolve `self._result_storage` via
    `get_result_storage(self._result_storage_arg)` on first save.
  - Delegate the write to `await storage.save(collection, document)`.
  - Catch and log exceptions at WARNING (preserves fire-and-forget
    semantics).
- Add `async aclose()` to the mixin: `await
  asyncio.gather(*self._persist_tasks, return_exceptions=True)` then
  `await self._result_storage.close()` if non-None. Reset both
  attributes. Idempotent.
- Add `__aenter__` / `__aexit__` to the mixin that delegate to
  `aclose()`.
- Delete `parrot/bots/flow/storage/persistence.py`.
- Update `parrot/bots/flow/storage/__init__.py` to drop the
  `PersistenceMixin` re-export. Verify the file no longer references it.
- Add unit tests covering: opt-out, lazy backend resolution, exception
  swallowing, `aclose()` waits for pending tasks, `aclose()` is
  idempotent, async context-manager protocol.

**NOT in scope**: Touching `AgentCrew` / `AgentsFlow` constructors —
that wiring is TASK-1018 (the mixin only consumes attributes the host
class will set). Removing the rest of `parrot/bots/flow/storage/` —
deferred per spec §8 open question.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/flows/core/storage/persistence.py` | MODIFY | Full rewrite per scope. |
| `parrot/bots/flow/storage/persistence.py` | DELETE | Legacy duplicate. |
| `parrot/bots/flow/storage/__init__.py` | MODIFY | Drop the `PersistenceMixin` re-export. |
| `parrot/bots/flow/fsm.py` | MODIFY | Change line 41 to `from ..flows.core.storage import PersistenceMixin, SynthesisMixin`. |
| `tests/bots/flows/core/storage/test_persistence_mixin.py` | CREATE | Unit tests for the mixin. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.storage.backends import (
    ResultStorage,
    get_result_storage,
)  # CREATED by TASK-1013
```

### Existing Signatures to Use
```python
# parrot/bots/flows/core/storage/persistence.py — current shape (to be rewritten)
class PersistenceMixin:                                       # line 14
    """Mixin that adds DocumentDB persistence to crew/flow orchestrators."""

    async def _save_result(                                   # line 20
        self,
        result: Any,
        method: str,
        *,
        collection: str = "crew_executions",
        **kwargs,
    ) -> None: ...
    # Body imports DocumentDb (line 38) and `async with DocumentDb()` (line 50).
    # The new body MUST drop both and use self._result_storage instead.

# parrot/bots/flow/storage/__init__.py — current re-exports
# Verify with: cat parrot/bots/flow/storage/__init__.py
# After this task: remove the `PersistenceMixin` line from `__all__`
# and the matching `from .persistence import PersistenceMixin` import.
# Other re-exports (`ExecutionMemory`, `VectorStoreMixin`, `SynthesisMixin`)
# are kept until the user finishes the out-of-tree review.

# parrot/bots/flow/fsm.py:41
from .storage import PersistenceMixin, SynthesisMixin
# AFTER this task:
# from ..flows.core.storage import PersistenceMixin, SynthesisMixin
```

### Caller-side contract (consumed but not modified by this task)

The mixin's new body relies on three attributes set by the host class
(TASK-1018 wires them in):

```python
self._persist_results: bool                       # default True
self._result_storage_arg: Union[str, ResultStorage, None]
self._result_storage: Optional[ResultStorage]     # populated lazily
self._persist_tasks: set[asyncio.Task]            # initialised to set()
```

If any of these is missing on `self`, the mixin must use `getattr` with
sensible defaults so it remains backwards-compatible with any callers
that haven't been wired yet during the migration. Example:
`getattr(self, "_persist_results", True)`.

### Does NOT Exist
- ~~`PersistenceMixin._persist_tasks`~~ — does not exist today; this task adds the attribute by reading via `getattr` and lets the host class own it.
- ~~`PersistenceMixin.aclose`~~ — does not exist; CREATE.
- ~~`PersistenceMixin.__aenter__`~~ — does not exist; CREATE.
- ~~`get_result_storage` in any other location~~ — only at `parrot.bots.flows.core.storage.backends`.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/bots/flows/core/storage/persistence.py — new body
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from navconfig.logging import logging

from .backends import ResultStorage, get_result_storage


class PersistenceMixin:
    """Pluggable persistence for crew/flow execution results.

    The host class owns these attributes (initialised in its __init__):
        self._persist_results: bool
        self._result_storage_arg: str | ResultStorage | None
        self._result_storage: Optional[ResultStorage]
        self._persist_tasks: set[asyncio.Task]

    All four are accessed via getattr with defaults so the mixin remains
    safe even when a host class has not been wired yet.
    """

    async def _save_result(
        self,
        result: Any,
        method: str,
        *,
        collection: str = "crew_executions",
        **kwargs,
    ) -> None:
        if not getattr(self, "_persist_results", True):
            return

        logger = getattr(self, "logger", logging.getLogger(__name__))
        try:
            storage = self._ensure_result_storage()
            data = {
                "crew_name": getattr(self, "name", "unknown"),
                "method":    method,
                "timestamp": time.time(),
                "result":    result.to_dict() if hasattr(result, "to_dict") else str(result),
                **kwargs,
            }
            data.setdefault("user_id", "unknown")
            await storage.save(collection, data)
        except Exception as exc:
            logger.warning(
                "Failed to save result to '%s': %s", collection, exc,
            )

    def _ensure_result_storage(self) -> ResultStorage:
        storage: Optional[ResultStorage] = getattr(self, "_result_storage", None)
        if storage is None:
            storage = get_result_storage(getattr(self, "_result_storage_arg", None))
            self._result_storage = storage
        return storage

    async def aclose(self) -> None:
        """Wait for in-flight persist tasks, then release the storage backend."""
        logger = getattr(self, "logger", logging.getLogger(__name__))
        pending: set[asyncio.Task] = getattr(self, "_persist_tasks", set())
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            pending.clear()
        storage: Optional[ResultStorage] = getattr(self, "_result_storage", None)
        if storage is not None:
            try:
                await storage.close()
            except Exception as exc:
                logger.warning("Failed to close result storage: %s", exc)
            finally:
                self._result_storage = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()
```

### Key Constraints
- The mixin must NOT initialise `self._result_storage` in `__init__`
  (the host class owns construction) — this keeps the mixin truly mixin.
- `aclose()` is idempotent. After it runs, calling it again is a no-op
  because `_result_storage` is `None` and `_persist_tasks` is empty.
- Use `asyncio.gather(*pending, return_exceptions=True)` so a failing
  background save does not prevent the storage from being closed.

### References in Codebase
- `parrot/bots/flows/core/storage/persistence.py` (current code) — the
  before state.
- `parrot/bots/flow/storage/persistence.py` (current code) — the byte-equivalent
  duplicate that this task deletes.
- `parrot/bots/flow/fsm.py:41` — import site that must be re-pointed.

### Migration steps (run in this order)

1. Rewrite `parrot/bots/flows/core/storage/persistence.py` (canonical).
2. Update `parrot/bots/flow/fsm.py` line 41 to import from the canonical
   location.
3. Run `grep -rn "from .storage import PersistenceMixin\|from ..flow.storage import PersistenceMixin\|from .persistence import PersistenceMixin" parrot/` to find any remaining legacy imports; update them.
4. Edit `parrot/bots/flow/storage/__init__.py`: remove the
   `from .persistence import PersistenceMixin` line and remove
   `"PersistenceMixin"` from `__all__`.
5. Delete `parrot/bots/flow/storage/persistence.py`.
6. Run `pytest tests/bots/flows/core/storage/test_persistence_mixin.py -v` plus any pre-existing tests under `tests/bots/flow/` to ensure nothing broke.

---

## Acceptance Criteria

- [ ] `parrot/bots/flow/storage/persistence.py` is deleted.
- [ ] `grep -rn "from .storage import PersistenceMixin" parrot/bots/flow/` returns no results.
- [ ] `grep -rn "from .persistence import PersistenceMixin" parrot/bots/flow/storage/__init__.py` returns no results.
- [ ] `parrot/bots/flow/fsm.py` imports `PersistenceMixin` from `parrot.bots.flows.core.storage`.
- [ ] `_save_result` returns immediately when `self._persist_results` is False (no factory call, no log line).
- [ ] First `_save_result` lazily instantiates the backend via `get_result_storage`; second call reuses the cached instance.
- [ ] An exception inside the backend's `save()` is logged at WARNING and never propagates.
- [ ] `aclose()` awaits all tasks in `self._persist_tasks` before calling `storage.close()`.
- [ ] `aclose()` is idempotent (calling twice does not raise; calling on a never-persisted host is a no-op).
- [ ] `async with` protocol on the mixin calls `aclose()` on exit.
- [ ] `pytest tests/bots/flows/core/storage/test_persistence_mixin.py -v` is green.
- [ ] `ruff check parrot/bots/flows/core/storage/persistence.py parrot/bots/flow/fsm.py` is clean.

---

## Test Specification

```python
# tests/bots/flows/core/storage/test_persistence_mixin.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.bots.flows.core.storage import PersistenceMixin
from parrot.bots.flows.core.storage.backends import ResultStorage


class _FakeStorage(ResultStorage):
    def __init__(self):
        self.saves = []
        self.closed = False
    async def save(self, collection, document):
        self.saves.append((collection, document))
    async def close(self):
        self.closed = True


class _Host(PersistenceMixin):
    name = "TestCrew"
    def __init__(self, persist=True, storage=None):
        self._persist_results = persist
        self._result_storage_arg = storage
        self._result_storage = storage if isinstance(storage, ResultStorage) else None
        self._persist_tasks = set()


@pytest.mark.asyncio
async def test_save_skips_when_disabled():
    fake = _FakeStorage()
    host = _Host(persist=False, storage=fake)
    await host._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    assert fake.saves == []


@pytest.mark.asyncio
async def test_save_lazy_resolves_storage(monkeypatch):
    fake = _FakeStorage()
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.persistence.get_result_storage",
        lambda arg: fake,
    )
    host = _Host(persist=True, storage=None)
    await host._save_result(MagicMock(to_dict=lambda: {"x": 1}), "run_flow")
    await host._save_result(MagicMock(to_dict=lambda: {"x": 2}), "run_flow")
    assert len(fake.saves) == 2
    assert host._result_storage is fake  # cached


@pytest.mark.asyncio
async def test_save_swallows_backend_exceptions(monkeypatch, caplog):
    failing = MagicMock(spec=ResultStorage)
    failing.save = AsyncMock(side_effect=RuntimeError("boom"))
    failing.close = AsyncMock()
    host = _Host(persist=True, storage=failing)
    await host._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    assert "Failed to save result" in caplog.text


@pytest.mark.asyncio
async def test_aclose_awaits_pending_tasks_and_closes_storage():
    fake = _FakeStorage()
    host = _Host(persist=True, storage=fake)

    sentinel = []
    async def slow_save():
        await asyncio.sleep(0.01)
        sentinel.append(1)
    t = asyncio.create_task(slow_save())
    host._persist_tasks.add(t)

    await host.aclose()
    assert sentinel == [1]
    assert fake.closed is True
    assert host._result_storage is None


@pytest.mark.asyncio
async def test_aclose_is_idempotent():
    fake = _FakeStorage()
    host = _Host(persist=True, storage=fake)
    await host.aclose()
    await host.aclose()  # second call: no-op


@pytest.mark.asyncio
async def test_async_context_manager_calls_aclose():
    fake = _FakeStorage()
    host = _Host(persist=True, storage=fake)
    async with host:
        pass
    assert fake.closed is True
```

---

## Agent Instructions

1. **Read the spec** §2 "Lifecycle & Cleanup" and §3 Module 5.
2. **Verify** TASK-1013, 1014, 1015, 1016 are in `tasks/completed/`.
3. **Activate the venv**: `source .venv/bin/activate`.
4. **Confirm** the legacy duplicate diff before deleting:
   `diff parrot/bots/flow/storage/persistence.py parrot/bots/flows/core/storage/persistence.py`.
   The two files should still be functionally identical — if not, surface the discrepancy in the Completion Note before deleting.
5. **Implement** in the order documented in "Migration steps".
6. **Run** `pytest tests/bots/flows/core/storage/test_persistence_mixin.py -v`
   and a quick smoke test: `pytest tests/bots/flow/ -k persistence -v` if any
   pre-existing tests live there.
7. **Move this file** to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-05
**Notes**: 9 tests pass. Canonical persistence.py rewritten to delegate to
ResultStorage backends. Legacy flow/storage/persistence.py deleted.
fsm.py import updated to canonical location. Legacy __init__.py drops
PersistenceMixin re-export with an explanatory comment.

**Deviations from spec**: none
