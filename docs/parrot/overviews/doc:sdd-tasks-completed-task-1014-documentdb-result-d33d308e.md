---
type: Wiki Overview
title: 'TASK-1014: DocumentDbResultStorage backend (default)'
id: doc:sdd-tasks-completed-task-1014-documentdb-result-storage-backend-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The default backend. Wraps the existing `DocumentDb` interface and
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.documentdb
  rel: mentions
- concept: mod:parrot.interfaces.documentdb
  rel: mentions
---

# TASK-1014: DocumentDbResultStorage backend (default)

**Feature**: FEAT-147 — Crew Result Storage Backends
**Spec**: `sdd/specs/crew-result-storage-backends.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1013
**Assigned-to**: unassigned

---

## Context

The default backend. Wraps the existing `DocumentDb` interface and
preserves today's behaviour exactly so users with no explicit
configuration continue to write to MongoDB-compatible storage. Implements
spec §2 "Backend: DocumentDB" and §3 Module 2.

---

## Scope

- Implement `DocumentDbResultStorage(ResultStorage)` in
  `parrot/bots/flows/core/storage/backends/documentdb.py`.
- `save(collection, document)` opens an `async with DocumentDb()` block
  and calls `db.write(collection, document)` — this matches the current
  `_save_result` body in `parrot/bots/flows/core/storage/persistence.py:50`.
- `close()` is a no-op (the connection lifecycle is owned by the
  `async with` block per write).
- Add unit tests with a mocked `DocumentDb` recording the calls.

**NOT in scope**: Long-lived DocumentDB connections (current behaviour
is per-write `async with`; do not change this — it preserves the existing
contract). Rewriting `PersistenceMixin` (TASK-1017).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/flows/core/storage/backends/documentdb.py` | CREATE | `DocumentDbResultStorage` adapter. |
| `tests/bots/flows/core/storage/test_documentdb_backend.py` | CREATE | Unit tests with mocked `DocumentDb`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interfaces.documentdb import DocumentDb       # verified: parrot/interfaces/documentdb.py:63
```

### Existing Signatures to Use
```python
# parrot/interfaces/documentdb.py
class DocumentDb:                                              # line 63
    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        failed_writes_limit: int = DEFAULT_FAILED_WRITES_LIMIT,
        retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
        **kwargs,
    ): ...                                                     # line 91
    async def __aenter__(self) -> "DocumentDb": ...            # line 299
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...  # line 304
    async def write(                                           # line 447
        self,
        collection: str,
        data: Union[dict, List[dict]],
        ...
    ) -> ...: ...
```

The current PersistenceMixin code path that this backend reproduces is at
`parrot/bots/flows/core/storage/persistence.py:50`:
```python
async with DocumentDb() as db:
    await db.write(collection, data)
```

### Does NOT Exist
- ~~`DocumentDb.write_one`~~ — method does not exist; use `write(collection, dict)`.
- ~~Pre-opened module-level singleton `_DOCDB`~~ — not the pattern; each call uses `async with`.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/bots/flows/core/storage/backends/documentdb.py
from __future__ import annotations
from typing import Any
from navconfig.logging import logging
from parrot.interfaces.documentdb import DocumentDb
from .base import ResultStorage


class DocumentDbResultStorage(ResultStorage):
    """Default backend — preserves the legacy DocumentDB write path."""

    def __init__(self) -> None:
        self.logger = logging.getLogger("parrot.crew_storage.documentdb")

    async def save(self, collection: str, document: dict[str, Any]) -> None:
        async with DocumentDb() as db:
            await db.write(collection, document)

    async def close(self) -> None:
        return None
```

### Key Constraints
- Do NOT cache a `DocumentDb` instance on `self`. Per-call `async with` is
  the existing contract and the test fixtures rely on it.
- Logger namespace: `parrot.crew_storage.documentdb`.

### References in Codebase
- `parrot/bots/flows/core/storage/persistence.py:50` — exact existing code path being preserved.

---

## Acceptance Criteria

- [ ] `from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage` succeeds.
- [ ] `DocumentDbResultStorage` is registered in the factory (lazy import path `parrot.bots.flows.core.storage.backends.documentdb:DocumentDbResultStorage`); `get_result_storage("documentdb")` returns an instance.
- [ ] One call to `save("crew_executions", {...})` results in exactly one `DocumentDb.__aenter__`, one `DocumentDb.write("crew_executions", doc)`, and one `DocumentDb.__aexit__`.
- [ ] `await backend.close()` returns `None` and does not raise even if `save` was never called.
- [ ] `pytest tests/bots/flows/core/storage/test_documentdb_backend.py -v` is green.
- [ ] `ruff check parrot/bots/flows/core/storage/backends/documentdb.py` is clean.

---

## Test Specification

```python
# tests/bots/flows/core/storage/test_documentdb_backend.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.fixture
def mock_documentdb(monkeypatch):
    instance = MagicMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    instance.write = AsyncMock(return_value=None)
    cls = MagicMock(return_value=instance)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.documentdb.DocumentDb",
        cls,
    )
    return instance


@pytest.mark.asyncio
async def test_documentdb_save_uses_async_with(mock_documentdb):
    from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage
    backend = DocumentDbResultStorage()
    await backend.save("crew_executions", {"crew_name": "x"})
    mock_documentdb.__aenter__.assert_awaited_once()
    mock_documentdb.write.assert_awaited_once_with(
        "crew_executions", {"crew_name": "x"}
    )
    mock_documentdb.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_documentdb_close_is_noop():
    from parrot.bots.flows.core.storage.backends import DocumentDbResultStorage
    backend = DocumentDbResultStorage()
    assert await backend.close() is None
```

---

## Agent Instructions

1. **Read the spec** §2 "Backend: DocumentDB" and verify TASK-1013 is in `tasks/completed/`.
2. **Activate the venv**: `source .venv/bin/activate`.
3. **Verify** that `DocumentDb.__aenter__` and `DocumentDb.write` still exist at the line numbers above (`grep -n "async def __aenter__\|async def write" parrot/interfaces/documentdb.py`).
4. **Implement** the backend following the pattern.
5. **Run** `pytest tests/bots/flows/core/storage/test_documentdb_backend.py -v`.
6. **Move this file** to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-05
**Notes**: 3 tests pass. DocumentDb moved to module-level import for proper
monkeypatching in tests. Preserves per-call async-with contract exactly.

**Deviations from spec**: none
