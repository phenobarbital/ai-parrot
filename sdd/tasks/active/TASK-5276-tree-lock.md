# TASK-5276: Cross-process per-tree writer lock

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1** (`knowledge/pageindex/locks.py`). Every publication of a
PageIndex generation (spec §2 Overview, step 1) takes an exclusive lock on the tree so two
processes — an agent, the Bookstore CLI, the future MCP server — can never publish over each
other. Nothing locks a tree today (spec §6 "Does NOT Exist").

---

## Scope

- Create `knowledge/pageindex/locks.py` with `TreeLockTimeout`, `lock_path()` and the async
  context manager `tree_lock()`.
- Exclude **other processes** with `fcntl.flock(fd, LOCK_EX | LOCK_NB)` polled every
  `_LOCK_POLL_SECONDS` (0.05 s) with `asyncio.sleep` — the pattern of
  `knowledge/wiki/repo_cache.py:53-95`.
- Exclude **other coroutines of the same process** with a per-path `asyncio.Lock` taken before
  the file lock, so in-process waiters do not spin on `flock`.
- Raise `TreeLockTimeout` when the deadline passes; raise `RuntimeError` when `fcntl` is
  unavailable (no silent no-op, unlike `repo_lock`).
- Write `tests/knowledge/pageindex/test_locks.py`.

**NOT in scope**: using the lock anywhere (TASK-5282 / TASK-5283), lock-file cleanup on
`delete_tree` (TASK-5283), shared/read locks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py` | CREATE | Lock module |
| `packages/ai-parrot/tests/knowledge/pageindex/test_locks.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.store import JSONTreeStore  # verified: knowledge/pageindex/store.py:23
```

### Existing Signatures to Use
```python
# knowledge/pageindex/store.py
class JSONTreeStore:                                   # line 23
    @staticmethod
    def _validate_name(tree_name: str) -> None         # lines 36-38 — raises ValueError on a bad name (regex :20)

# knowledge/wiki/repo_cache.py  (PATTERN ONLY — do not import repo_lock)
_LOCK_POLL_SECONDS = 0.05                              # line 23
async def repo_lock(lock_path: Path, *, timeout: float, shared: bool = False) -> AsyncIterator[bool]  # line 53
    # open(lock_path, "a+"); fcntl.flock(fd, mode | LOCK_NB) in a loop; asyncio.sleep between tries;
    # LOCK_UN + close in finally (lines 69-95). Yields False on timeout — tree_lock must RAISE instead.
```

### Does NOT Exist
- ~~`parrot.knowledge.pageindex.locks`~~ — created by this task
- ~~any lock on PageIndex trees~~ — none today; `NodeEmbeddingStore._cache_lock` is an LRU guard
- ~~`fcntl.lockf` semantics~~ — do NOT use `lockf`/POSIX record locks: they are per-process and do
  not exclude two descriptors of the same process; use `fcntl.flock`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_locks.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/store.py#JSONTreeStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Never block the event loop: no blocking `flock` without `LOCK_NB`.
- `asyncio.Lock` objects bind to the running loop. Keep them in a
  `weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]` so pytest's
  per-test loops never share a lock — *because* a lock created on a closed loop raises.
- The in-process lock is acquired with `asyncio.wait_for(lock.acquire(), remaining)` so the single
  `timeout` covers both stages.
- Release order in `finally`: `LOCK_UN`, close the handle, then release the `asyncio.Lock`.

---

## Implementation Blueprint

### Steps (in order)
1. Create `locks.py` from the block below — *why*: fixes the public names TASK-5282 imports.
2. Fill the acquisition loop — *why*: it is the only behavioural part.
3. Write the tests, including a real second process — *why*: AC-1 is about processes.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py` (CREATE)
```python
"""Cross-process, per-tree writer lock for PageIndex generation publication (FEAT-831)."""

from __future__ import annotations

import asyncio
import logging
import time
import weakref
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

try:  # POSIX only.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platform
    fcntl = None  # type: ignore[assignment]

from parrot.knowledge.pageindex.store import JSONTreeStore  # verified: store.py:23

logger = logging.getLogger("parrot.knowledge.pageindex.locks")

_LOCK_POLL_SECONDS: float = 0.05
_LOCAL_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]" = (
    weakref.WeakKeyDictionary()
)


class TreeLockTimeout(TimeoutError):
    """Raised when the per-tree lock is not acquired within ``timeout`` seconds."""


def lock_path(storage_dir: Path, tree_name: str) -> Path:
    """Return ``<storage_dir>/.locks/<tree_name>.lock`` after validating ``tree_name``."""
    JSONTreeStore._validate_name(tree_name)
    return Path(storage_dir) / ".locks" / f"{tree_name}.lock"


def _local_lock(path: Path) -> asyncio.Lock:
    # FILL IN: return the asyncio.Lock for str(path.resolve()) on the running loop, creating it
    # on first use — bounded by the WeakKeyDictionary rule in Key Constraints
    raise NotImplementedError


@asynccontextmanager
async def tree_lock(storage_dir: Path, tree_name: str, *, timeout: float) -> AsyncIterator[None]:
    """Hold an exclusive lock on ``tree_name`` for the duration of the block.

    Raises:
        TreeLockTimeout: the lock was not acquired within ``timeout`` seconds.
        RuntimeError: ``fcntl`` is unavailable on this platform.
    """
    if fcntl is None:
        raise RuntimeError("tree_lock requires fcntl (POSIX)")
    path = lock_path(storage_dir, tree_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(timeout, 0.0)
    local = _local_lock(path)
    # FILL IN: acquire `local` with asyncio.wait_for(remaining); on asyncio.TimeoutError raise
    # TreeLockTimeout(tree_name) — bounded by AC-2
    handle = open(path, "a+")  # noqa: SIM115,ASYNC230 - closed in finally
    try:
        # FILL IN: poll fcntl.flock(handle.fileno(), LOCK_EX | LOCK_NB); on OSError sleep
        # _LOCK_POLL_SECONDS until `deadline`, then raise TreeLockTimeout — bounded by AC-1/AC-2
        yield
    finally:
        # FILL IN: LOCK_UN (ignore OSError), handle.close(), local.release() — in that order
        pass
```
**Why this shape**: spec M1 fixes the names, the lock-file location and "raise, never yield
False". The two-stage lock is required because `flock` only excludes separate open file
descriptions; two coroutines of one process would otherwise both poll the file.

### FILL IN checklist
- [ ] `_local_lock` — loop-scoped lock registry; bounded by Key Constraints
- [ ] in-process acquisition with the shared deadline; bounded by AC-2
- [ ] `flock` polling loop; bounded by AC-1
- [ ] release order in `finally`; bounded by AC-3

---

## Acceptance Criteria

- [ ] AC-1: while another **process** holds `flock` on `lock_path(dir, "t")`, `tree_lock(dir, "t", timeout=0.2)` raises `TreeLockTimeout`.
- [ ] AC-2: a second coroutine in the same process waits for the first and acquires after it releases; with a too-short timeout it raises `TreeLockTimeout`.
- [ ] AC-3: the lock is free after the block exits with an exception.
- [ ] AC-4: an invalid tree name raises `ValueError` before any file is created.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_locks.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_locks.py
import asyncio
import fcntl
import multiprocessing as mp

import pytest

from parrot.knowledge.pageindex.locks import TreeLockTimeout, lock_path, tree_lock


def _hold(path: str, ready, release) -> None:
    with open(path, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        ready.set()
        release.wait(10)


@pytest.mark.asyncio
async def test_tree_lock_excludes_second_process(tmp_path):
    path = lock_path(tmp_path, "t")
    path.parent.mkdir(parents=True)
    ctx = mp.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    proc = ctx.Process(target=_hold, args=(str(path), ready, release))
    proc.start()
    try:
        assert ready.wait(10)
        with pytest.raises(TreeLockTimeout):
            async with tree_lock(tmp_path, "t", timeout=0.2):
                pass
    finally:
        release.set()
        proc.join(10)


@pytest.mark.asyncio
async def test_tree_lock_serializes_coroutines(tmp_path):
    # FILL IN: two tasks append to a list inside tree_lock with an await in between; assert no interleaving
    ...


@pytest.mark.asyncio
async def test_tree_lock_releases_on_exception(tmp_path):
    # FILL IN: raise inside the block, then acquire again with timeout=0
    ...


def test_lock_path_rejects_bad_name(tmp_path):
    with pytest.raises(ValueError):
        lock_path(tmp_path, "../x")
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-generation-publication --feature-id FEAT-831`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-generation-publication.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
7. **Verify** — run the Validation Commands and `ruff check` on the files you touched.
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`).
9. **Close the task** with `parrot sdd task close TASK-5276 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
