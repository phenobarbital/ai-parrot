# TASK-795: Implement AbstractClient Per-Loop Client Cache

**Feature**: FEAT-112 — Per-Loop LLM Client Cache
**Spec**: `sdd/specs/per-loop-llm-client-cache.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Every `AbstractClient` subclass caches a single SDK client on `self.client` that
binds (via aiohttp/httpx) to the event loop first used — so reusing the wrapper
from a background thread (fresh loop) raises `RuntimeError: got Future attached
to a different loop`.

This task implements **Module 1** of the spec: introduce a per-loop cache on
`AbstractClient` so every subclass benefits without per-subclass edits, while
preserving connection reuse within a loop.

See spec §2 (Architectural Design) and §3 (Module 1).

---

## Scope

Modify `parrot/clients/base.py` only. No subclass changes in this task.

- Add module-level `_LoopClientEntry` dataclass (client, loop_ref: weakref, metadata: dict).
- Replace `self.client: Any = None` in `__init__` with:
  - `self._clients_by_loop: dict[int, _LoopClientEntry] = {}`
  - `self._locks_by_loop: dict[int, asyncio.Lock] = {}` (lock allocated lazily per loop — `asyncio.Lock()` is itself loop-bound).
- Introduce `client` as a property:
  - Getter returns the SDK client bound to `id(asyncio.get_running_loop())`, or `None` if absent / no running loop.
  - Setter accepts `None` (clears only the current-loop entry for legacy compatibility) and rejects non-`None` values with a `DeprecationWarning` followed by `AttributeError` (hard deprecation — spec §8 Q2 decision).
- Implement `async def _ensure_client(self, **hints) -> Any`:
  1. Resolve `loop_id = id(asyncio.get_running_loop())`.
  2. Acquire the lazily-created lock for this loop.
  3. Look up the entry; if present and `_client_invalid_for_current(entry.client, **hints)` is `False`, return `entry.client`.
  4. Otherwise call `await self.get_client(**{k: v for k, v in hints.items() if k in _get_client_params})` and store a new `_LoopClientEntry(client=..., loop_ref=weakref.ref(loop), metadata={})`.
  5. Emit `self.logger.info("Per-loop cache miss: building new SDK client for loop %s", loop_id)` on cache-miss paths (spec §8 Q5 decision: log line, not DEBUG-only counter).
  6. Return the client.
- Add `def _client_invalid_for_current(self, client: Any, **hints: Any) -> bool`; default implementation returns `False`. Subclasses override this (e.g. `GoogleGenAIClient` in TASK-796).
- Add `async def _close_current_loop_entry(self) -> None`:
  - Pop the current-loop entry, call `await client.close()` if the SDK client exposes a coroutine `close()`, else `close()` if sync.
  - Intended for the Google error-recovery paths that currently call `await self.close()` mid-request (spec §7 Known Risks).
- Rewrite `async def close(self) -> None`:
  - Iterate `self._clients_by_loop.items()` (snapshot via `list(...)` to allow mutation).
  - For each entry: if `entry.loop_ref()` is still alive AND equals the running loop (if any), `await entry.client.close()` when supported; otherwise drop the reference without awaiting.
  - Clear `self._clients_by_loop` at the end.
- Add `async def close_all(self) -> None` as explicit alias / synonym for "tear down every loop's entry" (spec §8 Q1 decision: both `close` and `close_all`).
- Rewrite `__aenter__` to call `await self._ensure_client()` instead of directly assigning `self.client`. Keep the `use_session=True` branch that creates `self.session` (no production subclass currently sets `use_session=True` — verified; do NOT restructure `self.session` in this task).

**NOT in scope**:
- Any subclass change (covered by TASK-796 / TASK-797 / TASK-798 / TASK-799).
- Writing unit tests (TASK-800) — but write the code so it's testable.
- Touching `parrot/clients/live.py` (TASK-799).
- Removing the legacy `self.session` aiohttp.ClientSession pathway (spec §7 notes it is unused; out-of-scope cleanup).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | Add `_LoopClientEntry`, `_clients_by_loop`, `_locks_by_loop`, `_ensure_client`, `_client_invalid_for_current`, `client` property/setter, `_close_current_loop_entry`, rewrite `close()`, add `close_all()`, rewrite `__aenter__`. |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verify every item still matches `git blame` / `read` of the current source
> before writing code. File is edited actively.

### Verified Imports

```python
# packages/ai-parrot/src/parrot/clients/base.py (top of file; re-use as-is)
import asyncio                                                  # already imported
import logging                                                  # already imported (self.logger)
from abc import ABC, abstractmethod                             # already imported
from dataclasses import dataclass                               # ADD
from typing import Any, Dict, List, Optional, Union             # already imported
from weakref import ref as weakref_ref, ReferenceType           # ADD
import aiohttp                                                  # already imported (used by self.session)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/base.py

class AbstractClient(ABC):
    use_session: bool = False                           # line 220
    client_type: str                                    # class-var (subclasses override)
    client_name: str                                    # class-var (subclasses override)
    base_headers: dict                                  # subclasses populate

    def __init__(
        self,
        conversation_memory: Optional[ConversationMemory] = None,
        preset: Optional[str] = None,
        tools: Optional[List[Union[str, AbstractTool]]] = None,
        use_tools: bool = False,
        debug: bool = True,
        tool_manager: Optional[ToolManager] = None,
        **kwargs,
    ):                                                  # line 242
        self.client: Any = None                         # line 254   <-- REPLACE
        self.session: Optional[aiohttp.ClientSession] = None  # line 255 (keep as-is)
        self.use_session: bool = kwargs.get('use_session', self.use_session)  # line 256
        # ... (keep everything else)
        self.logger: logging.Logger = logging.getLogger(self.__name__)  # line 275

    @abstractmethod
    async def get_client(self) -> Any:                  # line 342
        raise NotImplementedError

    async def __aenter__(self):                         # line 346
        if self.use_session:
            self.session = aiohttp.ClientSession(headers=self.base_headers)  # line 349
        if not self.client:
            self.client = await self.get_client()       # line 353   <-- REPLACE with _ensure_client
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # line 356
        if self.session:
            await self.session.close()
        return False

    async def close(self):                              # line 469   <-- REWRITE
        if self.client is not None and hasattr(self.client, 'close'):
            close_method = self.client.close
            if asyncio.iscoroutinefunction(close_method):
                await close_method()
            elif callable(close_method):
                close_method()
```

### Does NOT Exist

- ~~`parrot.clients.base.ClientCache`~~ — no existing cache abstraction.
- ~~`parrot.clients.base.AbstractClient.loop_id`~~ — not an attribute.
- ~~`parrot.clients.base.AbstractClient._per_loop`~~ — reserved name; use `_clients_by_loop`.
- ~~`asyncio.current_event_loop()`~~ — not a real API. Use `asyncio.get_running_loop()` only; NEVER `asyncio.get_event_loop()` (creates a new loop when none is running, poisoning the cache).
- ~~`AbstractClient.client_pool`~~ — no pool attribute.
- ~~`AbstractClient._loop_meta`~~ — the spec mentions this name in the diagram but the implementation stores the loop weakref inside `_LoopClientEntry.loop_ref`; do not introduce a second dict.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/clients/base.py (new helper near top of file)

@dataclass
class _LoopClientEntry:
    """One (loop -> SDK client) binding inside AbstractClient's cache."""
    client: Any
    loop_ref: "ReferenceType"   # weakref to AbstractEventLoop
    metadata: dict

# inside AbstractClient

def __init__(self, ...):
    ...
    self._clients_by_loop: dict[int, _LoopClientEntry] = {}
    self._locks_by_loop: dict[int, asyncio.Lock] = {}

def _get_current_loop(self) -> Optional[asyncio.AbstractEventLoop]:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None

def _get_or_create_lock(self) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    lock = self._locks_by_loop.get(loop_id)
    if lock is None:
        lock = asyncio.Lock()
        self._locks_by_loop[loop_id] = lock
    return lock

@property
def client(self) -> Optional[Any]:
    loop = self._get_current_loop()
    if loop is None:
        return None
    entry = self._clients_by_loop.get(id(loop))
    return entry.client if entry else None

@client.setter
def client(self, value: Optional[Any]) -> None:
    if value is not None:
        import warnings
        warnings.warn(
            "Direct assignment of AbstractClient.client is deprecated; "
            "override get_client() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise AttributeError(
            "AbstractClient.client is now a loop-local property. "
            "Do not assign directly — return the client from get_client()."
        )
    loop = self._get_current_loop()
    if loop is None:
        return
    self._clients_by_loop.pop(id(loop), None)

async def _ensure_client(self, **hints: Any) -> Any:
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    lock = self._get_or_create_lock()
    async with lock:
        entry = self._clients_by_loop.get(loop_id)
        if entry is not None and not self._client_invalid_for_current(entry.client, **hints):
            return entry.client
        self.logger.info("Per-loop cache miss: building new SDK client for loop %s", loop_id)
        new_client = await self.get_client(**self._filter_get_client_hints(**hints))
        self._clients_by_loop[loop_id] = _LoopClientEntry(
            client=new_client,
            loop_ref=weakref_ref(loop),
            metadata={},
        )
        return new_client

def _filter_get_client_hints(self, **hints: Any) -> dict:
    """Subclasses with a custom get_client() signature can override to
    select which hints reach get_client(). Default: pass nothing — the
    base abstract signature is ``get_client(self)``."""
    return {}

def _client_invalid_for_current(self, client: Any, **hints: Any) -> bool:
    return False

async def _close_current_loop_entry(self) -> None:
    loop = self._get_current_loop()
    if loop is None:
        return
    entry = self._clients_by_loop.pop(id(loop), None)
    if entry is None:
        return
    await self._safe_close_entry(entry, is_current_loop=True)

async def close(self) -> None:
    await self.close_all()

async def close_all(self) -> None:
    current = self._get_current_loop()
    current_id = id(current) if current is not None else None
    for loop_id, entry in list(self._clients_by_loop.items()):
        await self._safe_close_entry(entry, is_current_loop=(loop_id == current_id))
    self._clients_by_loop.clear()
    self._locks_by_loop.clear()

async def _safe_close_entry(self, entry: "_LoopClientEntry", *, is_current_loop: bool) -> None:
    target_loop = entry.loop_ref()
    if target_loop is None or not is_current_loop:
        # loop is dead or is a foreign loop — do NOT await on it
        self.logger.debug("Dropping SDK client for dead/foreign loop without awaiting close()")
        return
    client = entry.client
    if client is None or not hasattr(client, "close"):
        return
    close_method = client.close
    try:
        if asyncio.iscoroutinefunction(close_method):
            await close_method()
        elif callable(close_method):
            close_method()
    except Exception as exc:  # noqa: BLE001
        self.logger.debug("Error closing SDK client for loop %s: %s", id(target_loop), exc)
```

### Key Constraints

- `_clients_by_loop` key is `id(asyncio.get_running_loop())`. **Never** use
  `asyncio.get_event_loop()` anywhere in this module.
- `asyncio.Lock()` is loop-bound — allocate one lock *per loop*, never share.
- The `client` setter ONLY accepts `None` (legacy "reset" semantics used by
  `GrokClient.close`). Non-`None` writes raise `AttributeError` with a clear
  migration message. Existing subclasses that write non-`None` to `self.client`
  are migrated in TASK-796/797/798 — those tasks land before this is deployed.
- Document `close` vs `close_all` in docstrings: both tear down every loop's
  entry in this release; we keep both names so subclasses / callers can be
  explicit. Per spec §8 Q1, both exist.
- `_ensure_client` accepts arbitrary `**hints` so subclasses like
  `GoogleGenAIClient` can pass `model=...` for invalidation-hook use.
- Log line on cache-miss (INFO level) per spec §8 Q5. Do NOT log on cache-hit
  (hot path).

### References in Codebase

- Current `close()` implementation: `packages/ai-parrot/src/parrot/clients/base.py:469`.
- Current `__aenter__`: `packages/ai-parrot/src/parrot/clients/base.py:346`.
- Example subclass that stores `self.client` today: `packages/ai-parrot/src/parrot/clients/grok.py:78-92`.

---

## Acceptance Criteria

- [ ] `_LoopClientEntry` dataclass exists at module level in `base.py`.
- [ ] `AbstractClient.__init__` no longer contains `self.client = None`; instead
      initializes `_clients_by_loop = {}` and `_locks_by_loop = {}`.
- [ ] `AbstractClient.client` is a `@property` returning the loop-local client.
- [ ] `AbstractClient.client.setter` accepts `None` silently and rejects non-`None`
      with a `DeprecationWarning` + `AttributeError`.
- [ ] `AbstractClient._ensure_client(**hints)` exists and is used by the
      rewritten `__aenter__`.
- [ ] `AbstractClient._client_invalid_for_current(client, **hints)` default
      returns `False`.
- [ ] `AbstractClient._close_current_loop_entry()` closes only the entry bound
      to the running loop.
- [ ] `AbstractClient.close()` and `close_all()` both tear down every entry,
      never awaiting on a dead or foreign loop.
- [ ] Each cache-miss is logged at `INFO` with the loop id.
- [ ] `asyncio.get_event_loop()` is NOT used anywhere in `base.py`.
- [ ] Running the existing test suite does not regress on imports:
      `pytest packages/ai-parrot/tests/test_anthropic_client.py -v --collect-only` succeeds.
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/base.py` is clean.

---

## Test Specification

> Tests live in TASK-800; this task must leave the module testable but writes
> NO tests itself. A smoke import check is enough here.

```python
# Sanity: the module must still import after the rewrite.
import asyncio
from parrot.clients.base import AbstractClient, _LoopClientEntry  # noqa: F401

class _Dummy(AbstractClient):
    client_type = "dummy"
    client_name = "dummy"
    async def get_client(self):
        return object()
    async def ask(self, *a, **kw):
        raise NotImplementedError

async def _smoke():
    d = _Dummy()
    assert d.client is None             # no loop-local client yet
    c = await d._ensure_client()
    assert d.client is c                # property resolves to same object
    await d.close()
    assert d.client is None

asyncio.run(_smoke())
```

---

## Agent Instructions

When you pick up this task:

1. Read spec `sdd/specs/per-loop-llm-client-cache.spec.md` §2, §3 (Module 1), §7, §8.
2. Verify no dependency tasks in progress (none listed).
3. Verify the Codebase Contract — `grep` / `read` the line numbers given.
4. Update status in `sdd/tasks/.index.json` → `"in-progress"`.
5. Implement per scope + notes. Keep the diff scoped to `base.py`.
6. Run the smoke import above; then run
   `pytest packages/ai-parrot/tests/test_anthropic_client.py -v --collect-only`
   to ensure no import-time regressions.
7. Move this file to `sdd/tasks/completed/`, update the index.
8. Commit: `sdd: TASK-795 — AbstractClient per-loop cache`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**:
