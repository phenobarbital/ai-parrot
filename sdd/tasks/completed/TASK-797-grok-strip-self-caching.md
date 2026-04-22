# TASK-797: Strip GrokClient self-caching — rely on base per-loop cache

**Feature**: FEAT-112 — Per-Loop LLM Client Cache
**Spec**: `sdd/specs/per-loop-llm-client-cache.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-795
**Assigned-to**: unassigned

---

## Context

`GrokClient.get_client()` caches the xAI `AsyncClient` directly on
`self.client` and `GrokClient.close()` sets `self.client = None`. After
TASK-795, `self.client` is a loop-local property — the non-`None` write in
`get_client()` will raise `AttributeError` (hard deprecation). This task
removes that self-caching so the base class owns everything.

See spec §3 (Module 3) entry for `grok.py`.

---

## Scope

Modify `packages/ai-parrot/src/parrot/clients/grok.py` only.

- In `__init__`, remove `self.client: Optional[AsyncClient] = None` (line 78).
  The base class property handles this.
- Rewrite `async def get_client(self) -> AsyncClient` to always construct and
  return a fresh `AsyncClient`, with NO `self.client` write:

  ```python
  async def get_client(self) -> AsyncClient:
      return AsyncClient(api_key=self.api_key, timeout=self.timeout)
  ```

- In `async def close(self)`, remove `self.client = None` (line 92). Keep the
  `await super().close()` call (which now tears down every per-loop entry).
- If `ask()` / any public method has a `if not self.client: raise RuntimeError(
  "Client not initialized. Use async context manager.")` guard, replace it
  with `await self._ensure_client()` at the top of the method so callers that
  reuse the wrapper without `async with` still work. Grep first — do NOT
  invent a guard that isn't there.

**NOT in scope**:
- Changes to any other subclass (TASK-798).
- Grok-specific tool/streaming logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/grok.py` | MODIFY | Strip `self.client` writes from `__init__`, `get_client()`, `close()`; wire `_ensure_client` into public entry points if a stale guard is present. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/clients/grok.py
import os
from typing import Any, Dict, List, Optional
from xai_sdk import AsyncClient                               # verified via class annotation, grok.py:78-83
from parrot.clients.base import AbstractClient                # verified — subclass of AbstractClient
from parrot.clients.grok_models import GrokModel              # inferred from `_default_model = GrokModel.GROK_4.value` line 47
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/grok.py

class GrokClient(AbstractClient):                             # line 41
    client_type: str = "xai"                                  # line 45
    client_name: str = "grok"                                 # line 46
    _default_model: str = GrokModel.GROK_4.value              # line 47
    _lightweight_model: str = "grok-4-1-fast-non-reasoning"   # line 48

    def __init__(self, api_key=None, timeout: int = 3600, **kwargs):  # line 50
        super().__init__(**kwargs)                            # line 64
        self.api_key = api_key or os.getenv("XAI_API_KEY")    # line 65
        # ... fallback to navconfig ...
        self.timeout = timeout                                # line 77
        self.client: Optional[AsyncClient] = None             # line 78   <-- REMOVE

    async def get_client(self) -> AsyncClient:                # line 80
        if not self.client:
            self.client = AsyncClient(api_key=self.api_key, timeout=self.timeout)  # line 83
        return self.client                                    # line 87    <-- REPLACE whole body

    async def close(self):                                    # line 89
        await super().close()                                 # line 91
        self.client = None                                    # line 92   <-- REMOVE
```

### Does NOT Exist

- ~~`AbstractClient.client_pool`~~ — no pool attribute.
- ~~`GrokClient._client_loop_id`~~ — the Google-only interim hack never lived here.
- ~~`GrokClient.use_session = True`~~ — verified no `use_session=True` exists in this file.

---

## Implementation Notes

### Pattern to Follow

After-state for the three edits:

```python
def __init__(self, api_key: Optional[str] = None, timeout: int = 3600, **kwargs):
    super().__init__(**kwargs)
    self.api_key = api_key or os.getenv("XAI_API_KEY")
    if not self.api_key:
        try:
            from navconfig import config
            self.api_key = config.get("XAI_API_KEY")
        except ImportError:
            pass
    if not self.api_key:
        raise ValueError("XAI_API_KEY not found in environment or config")
    self.timeout = timeout
    # NOTE: no self.client = None — base class handles that as a property.

async def get_client(self) -> AsyncClient:
    return AsyncClient(api_key=self.api_key, timeout=self.timeout)

async def close(self):
    await super().close()
    # NOTE: no self.client = None — base's close() cleared the per-loop cache.
```

### Key Constraints

- Do NOT write to `self.client` anywhere in `grok.py` after this task.
- If `GrokClient.ask()` (or any public entry point) has an "not initialized"
  guard, replace it with `await self._ensure_client()` to keep ergonomics
  for callers that don't use `async with`. Confirm via grep first.
- Keep `self.timeout` and the env-var fallback exactly as-is.

### References in Codebase

- Base class behavior (dependency): `parrot/clients/base.py` post-TASK-795.
- Grok subclass today: `packages/ai-parrot/src/parrot/clients/grok.py:40-92`.

---

## Acceptance Criteria

- [ ] `grep -n "self.client" packages/ai-parrot/src/parrot/clients/grok.py` returns NO matches.
- [ ] `GrokClient.get_client()` body is a single `return AsyncClient(...)`.
- [ ] `GrokClient.close()` body is a single `await super().close()`.
- [ ] Import smoke: `python -c "from parrot.clients.grok import GrokClient"` succeeds.
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/grok.py` is clean.
- [ ] Existing grok tests still collect:
      `pytest packages/ai-parrot/tests/test_grok_client.py --collect-only`.

---

## Test Specification

> Formal tests in TASK-800. Smoke check here:

```python
import asyncio
from parrot.clients.grok import GrokClient

async def _smoke():
    # Requires XAI_API_KEY env var; skip if absent.
    import os
    if not os.getenv("XAI_API_KEY"):
        print("skipped — no XAI_API_KEY")
        return
    c = GrokClient()
    client_1 = await c._ensure_client()
    client_2 = await c._ensure_client()
    assert client_1 is client_2, "same loop must reuse the client"
    await c.close()

asyncio.run(_smoke())
```

---

## Agent Instructions

1. Verify TASK-795 is in `sdd/tasks/completed/`.
2. Verify the Codebase Contract — `grep` the three `self.client` call sites.
3. Update status to `"in-progress"` in the index.
4. Apply the three edits in order: `__init__`, `get_client`, `close`.
5. Run acceptance greps; ensure the file still imports.
6. Move this file to `sdd/tasks/completed/`; update the index.
7. Commit: `sdd: TASK-797 — GrokClient uses base per-loop cache`.

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-04-22
**Notes**: Removed self.client=None from __init__, simplified get_client() to pure
construction, simplified close() to only call super().close(). Also replaced the
"GrokClient not initialised" RuntimeError guard in invoke() with await self._ensure_client()
per task spec instructions. All acceptance checks pass.
**Deviations from spec**: None.
