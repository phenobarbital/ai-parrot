# TASK-5429: Add awaited scope recovery and operation-lock primitives

**Feature**: FEAT-858 — Bookstore Agentic Retrieval
**Spec**: `sdd/specs/bookstore-agentic-retrieval.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h; host wall time depends on provider when applicable)
**Depends-on**: TASK-5428
**Assigned-to**: unassigned

## Context

Implement this bounded deliverable of the approved FEAT-858 spec. Its behavioral authority
is the spec's §2 and owning §3 module, with §4 validation and §5 acceptance criteria.
Verified source base: `8387cd3e1b604955928064ff51a2fa207deceb36`. No implementation has been performed by this planning task.

## Scope

- Implement spec M4 async readiness while keeping synchronous _toolkit construction-only.
- Add keyword-only reindex_lock_timeout_s=5.0, positive finite, and private operation-lock helpers using root/.bookstore-operations as the tree_lock storage directory.
- Guard first async use per scope; mark ready only after completed recovery. Cancellation leaves readiness retryable; no unobserved task or nested event loop.
- Make sweep acquire book-<slug> nonblockingly, recheck filesystem state, skip active staging even after one hour, and report/log failures.
- Route async consumers through readiness; keep sweep on raw _toolkit to avoid recursion. Include remove and optimize(apply=True) in book operation locking. Actual add_book identity serialization is the next task.

**NOT in scope**: files outside the table, provider SDK calls, PageIndex loop/validator changes,
unrelated refactoring, new dependencies, and other tasks' deliverables.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py` | CREATE | Task regression coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from contextlib import asynccontextmanager  # verified: stdlib; existing pageindex/locks.py:11
from typing import AsyncIterator  # verified: stdlib; existing pageindex/locks.py:13
from parrot.knowledge.pageindex.locks import tree_lock, TreeLockTimeout  # verified: packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py:30,48
from pathlib import Path  # verified: stdlib; existing library.py:26
import pytest  # verified: existing Bookstore test_toolkit.py:5
from unittest.mock import AsyncMock, MagicMock  # verified: stdlib; Bookstore conftest.py:13
from parrot.knowledge.bookstore.config import LibraryLocation  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/config.py:33
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:112,179
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # verified: packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:161
from typing import Any, Optional  # verified: stdlib; existing library.py:27
```

### Existing Signatures to Use

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:193
def __init__(
        self,
        locations: list[LibraryLocation],
        adapter: Optional[Any] = None,
        lightweight_model: Optional[str] = None,
    ) -> None:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:234
def _toolkit(self, scope: str) -> PageIndexToolkit:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:293
async def _sweep_reserved_trees(self, scope: str) -> None:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1434
async def remove_book(self, book_id: str) -> bool:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1460
async def optimize_book(
        self,
        book_id: str,
        *,
        apply: bool = False,
        llm_passes: Optional[bool] = None,
    ) -> dict[str, Any]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py:48
async def tree_lock(storage_dir: Path, tree_name: str, *, timeout: float) -> AsyncIterator[None]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py:30
class TreeLockTimeout(TimeoutError):
```


### Dependency-produced contracts

- TASK-5428: serializes overlapping writes to packages/ai-parrot/src/parrot/knowledge/bookstore/library.py

Those newly created symbols/files are planned contracts, not claims that they exist at this base. Read prerequisite commits before implementation.

### Does NOT Exist

- Bookstore has no async _ready_toolkit or operation-lock helpers at the base; _toolkit is synchronous.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.__init__",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._toolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._sweep_reserved_trees",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.remove_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.optimize_book",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py#tree_lock",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py#TreeLockTimeout",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/config.py#LibraryLocation",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#BookstoreError",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit"
  ]
}
```

## Implementation Notes

TASK-5428: serializes overlapping writes to packages/ai-parrot/src/parrot/knowledge/bookstore/library.py

Use the activated project environment, async I/O, strict types, Google-style docstrings,
self.logger and existing dependency patterns. Do not alter shared conftest.py. This task
has no Delegation Contract: its behavioral branches/tests or host evidence still require
normal implementation reasoning; blueprint placeholders are planning instructions only.

## Implementation Blueprint

### Steps (in order)

1. Implement spec M4 async readiness while keeping synchronous _toolkit construction-only. **Why**: Concurrent first use awaits one completed sweep; cancellation permits a later retry.
2. Add keyword-only reindex_lock_timeout_s=5.0, positive finite, and private operation-lock helpers using root/.bookstore-operations as the tree_lock storage directory. **Why**: An actively locked staging tree older than the threshold survives; stale unlocked staging is removed and legacy replacement restore respects current existence.
3. Guard first async use per scope; mark ready only after completed recovery. Cancellation leaves readiness retryable; no unobserved task or nested event loop. **Why**: Operation locks live outside the PageIndex publication namespace and timeout configuration rejects invalid values.
4. Make sweep acquire book-<slug> nonblockingly, recheck filesystem state, skip active staging even after one hour, and report/log failures. **Why**: Async consumers use readiness without recursive sweep, lock reentrancy, or pending tasks retained across event loops.
5. Route async consumers through readiness; keep sweep on raw _toolkit to avoid recursion. Include remove and optimize(apply=True) in book operation locking. Actual add_book identity serialization is the next task. **Why**: Concurrent first use awaits one completed sweep; cancellation permits a later retry.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'class Bookstore:' packages/ai-parrot/src/parrot/knowledge/bookstore/library.py)
# Container/attachment anchor: class Bookstore:
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:179; merge scoped edits, never replace the whole container.
from contextlib import asynccontextmanager
from typing import AsyncIterator
from parrot.knowledge.pageindex.locks import tree_lock, TreeLockTimeout

# Extend the existing constructor, preserving all initialized state.
def __init__(self, locations: list[LibraryLocation], adapter: Optional[Any] = None,
             lightweight_model: Optional[str] = None, *,
             reindex_lock_timeout_s: float = 5.0) -> None:
    """Configure bounded operation locks and lazy async scope initialization."""
    # FILL IN: merge validation/state into existing constructor; AC-1, AC-3, AC-4.
    raise NotImplementedError

async def _ready_toolkit(self, scope: str) -> PageIndexToolkit:
    """Await one successful recovery before exposing this scope to async operations."""
    # FILL IN: active-loop readiness lock, retry-on-cancel, raw _toolkit in sweep; AC-1, AC-4.
    raise NotImplementedError

# FILL IN: private context-manager helpers and sweep locking within this file.
# Lock order is source -> allocation -> book -> PageIndex; recovery uses book -> PageIndex.
# Do not acquire the live PageIndex lock around rename; AC-2 and AC-3.
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py` (CREATE)

```python
"""Deterministic regression coverage for this FEAT-858 task."""
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError

@pytest.mark.asyncio
async def test_concurrent_scope_open(tmp_path: Path) -> None:
    """First async callers join one successful recovery."""
    # FILL IN: arrange synthetic state and assert the documented observable result; AC-1..AC-4.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_active_old_staging_survives(tmp_path: Path) -> None:
    """Recovery cannot delete an active import just because it is old."""
    # FILL IN: arrange synthetic state and assert the documented observable result; AC-1..AC-4.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_cancelled_scope_open_retries(tmp_path: Path) -> None:
    """Cancellation leaves initialization retryable."""
    # FILL IN: arrange synthetic state and assert the documented observable result; AC-1..AC-4.
    raise NotImplementedError

```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.

## Acceptance Criteria

- [ ] AC-1: Concurrent first use awaits one completed sweep; cancellation permits a later retry.
- [ ] AC-2: An actively locked staging tree older than the threshold survives; stale unlocked staging is removed and legacy replacement restore respects current existence.
- [ ] AC-3: Operation locks live outside the PageIndex publication namespace and timeout configuration rejects invalid values.
- [ ] AC-4: Async consumers use readiness without recursive sweep, lock reentrancy, or pending tasks retained across event loops.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_library.py -q`

## Test Specification

Exercise the observable cases in the blueprint and AC-1..AC-4 with synthetic temporary
state and bounded synchronization. Existing operands listed above are regression gates,
not authorization to edit them unless they appear in the file table. No live provider
calls in pytest. Save execution logs under artifacts/logs/.


## Agent Instructions

1. Run `$sdd-start TASK-5429` to provision the feature worktree; do not implement on dev.
2. Read the approved spec and dependency evidence before editing.
3. Reverify every MODIFY anchor; dependency-created files must be inspected after their creators land.
4. Implement only the declared files; final code must contain no blueprint placeholders.
5. Run the Validation Commands and appropriate formatting/lint checks; retain real logs.
6. Commit scoped work and finalize with `parrot sdd task finalize` using actual completion evidence.

## Completion Note

Seat gpt-5.6-terra (codex), 1 attempt, 368s. Merged; bookstore test dir 219 passed (test_integration_graph.py fails with sqlite 'unable to open database file' in the sandbox - untouched file, environmental). Review recorded; diff not read line by line.
