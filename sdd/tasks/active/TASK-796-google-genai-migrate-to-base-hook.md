# TASK-796: Migrate GoogleGenAIClient to Base Per-Loop Cache (remove interim hack)

**Feature**: FEAT-112 — Per-Loop LLM Client Cache
**Spec**: `sdd/specs/per-loop-llm-client-cache.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-795
**Assigned-to**: unassigned

---

## Context

`GoogleGenAIClient` carries an interim cross-loop invalidation hack
(`_client_loop_id`, `_current_loop_id`, a subclass `_ensure_client`) that shipped
on `dev` to unblock NextStop. With TASK-795 landed, the base class owns
per-loop caching — the Google subclass needs to (a) stop rebuilding across
loops (that's now free) and (b) keep its **model-class** invalidation via the
new `_client_invalid_for_current` hook, storing state in the per-loop entry's
`metadata` dict (not on the instance).

See spec §3 (Module 2) and §7 Known Risks (error-recovery paths).

---

## Scope

Modify `packages/ai-parrot/src/parrot/clients/google/client.py` only.

- Remove these interim-fix members:
  - `self._client_loop_id: Optional[int]` (line ~99)
  - `def _current_loop_id(self)` (line ~165)
  - `async def _ensure_client(self, model=None)` (line ~172) — the subclass override; base class now owns this method name.
- Remove the `self.client = None` line in `__init__` (line ~94); the base class
  no longer has that attribute directly (it's a property).
- Remove `self._client_model_class: str = None` (line ~95) as an instance
  attribute. Model-class tracking moves into `_LoopClientEntry.metadata`.
- Override `_client_invalid_for_current` from the base class:

  ```python
  def _client_invalid_for_current(self, client, **hints) -> bool:
      model = hints.get("model") or self.model or self._default_model
      if isinstance(model, GoogleModel):
          model = model.value
      desired = self._model_class_key(model)
      # Look up the current-loop entry to compare metadata.
      loop = self._get_current_loop()
      if loop is None:
          return False
      entry = self._clients_by_loop.get(id(loop))
      if entry is None:
          return True
      cached = entry.metadata.get("model_class")
      return cached is not None and cached != desired
  ```

- Override `_filter_get_client_hints` so the base `_ensure_client` forwards
  `model=...` to the subclass `get_client(model=...)`:

  ```python
  def _filter_get_client_hints(self, **hints) -> dict:
      return {"model": hints["model"]} if "model" in hints else {}
  ```

- After `_ensure_client` builds a fresh client for a loop, stamp the
  model-class metadata. Two clean ways:
  - **Preferred**: override `_ensure_client` minimally in this subclass only
    to record metadata after base builds. Example:

    ```python
    async def _ensure_client(self, model=None, **hints):  # type: ignore[override]
        if model is not None:
            hints["model"] = model
        client = await super()._ensure_client(**hints)
        # Stamp metadata on the just-built / just-reused entry.
        loop = asyncio.get_running_loop()
        entry = self._clients_by_loop.get(id(loop))
        if entry is not None:
            resolved = hints.get("model") or self.model or self._default_model
            if isinstance(resolved, GoogleModel):
                resolved = resolved.value
            entry.metadata["model_class"] = self._model_class_key(resolved)
        return client
    ```

    This preserves the existing `_ensure_client(model=...)` signature used by
    the 5 call sites in `google/client.py` (lines 1897, 2113, 2721, 3115, 3349)
    without touching them.
- Rewrite the existing `get_client(self, model=None, **kwargs)` so it:
  - Does NOT reference `self._client_model_class` or `self._client_loop_id`.
  - Does NOT call `await self.close()` mid-build (the base's
    `_ensure_client` + `_client_invalid_for_current` handles invalidation
    by replacing the dict entry when `get_client()` returns).
  - Simply constructs and **returns** a fresh `genai.Client` for the requested
    model. No caching inside `get_client`.
- Replace mid-request error-recovery calls to `await self.close()` (spec §7
  gotcha, file `client.py` around lines 2105 / 2715) with
  `await self._close_current_loop_entry()` so sibling loops are not evicted.
- Do NOT touch the 5 call sites of `await self._ensure_client(...)` in method
  bodies — their signature remains `_ensure_client(model=...)` after the
  override above.
- Rewrite the subclass `close()` to just `await super().close_all()` (or delete
  the override entirely if there is nothing else to do). Verify by reading the
  current `close()` around line ~290.

**NOT in scope**:
- Changes to `GeminiLiveClient` (TASK-799) or any non-Google subclass.
- Writing unit tests for the Google invalidation (TASK-800 covers this).
- Refactoring `_model_class_key`, `_is_gemini3_model`, `_is_preview_model`,
  `_requires_thinking`, or the Vertex AI client-construction logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/google/client.py` | MODIFY | Remove interim loop-id tracking; override `_client_invalid_for_current` + `_ensure_client` (thin wrapper) + `_filter_get_client_hints`; retire `self._client_model_class` → entry metadata; swap `self.close()` mid-request for `self._close_current_loop_entry()`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/clients/google/client.py — already imports:
import asyncio                                                  # verified line ~1-20 area
from google import genai                                        # verified
from google.genai.types import HttpOptions                      # verified
from google.oauth2 import service_account                       # verified

# In this file already:
from parrot.clients.base import AbstractClient                  # transitively via module imports
from parrot.clients.google.models import GoogleModel            # verified
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/google/client.py

class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):
    client_type: str = 'google'                         # line 66
    client_name: str = 'google'                         # line 67
    _default_model: str = 'gemini-2.5-flash'            # line 68
    _fallback_model: str = 'gemini-3.1-flash-lite-preview'  # line 69
    _model_garden: bool = False                         # line 70
    _lightweight_model: str = "gemini-3.1-flash-lite-preview"  # line 71

    def __init__(self, vertexai: bool = False, model_garden: bool = False, **kwargs):  # line 73
        # ... existing setup ...
        super().__init__(**kwargs)                      # line 92
        self.max_tokens = kwargs.get('max_tokens', None)  # line 93
        self.client = None                              # line 94  <-- REMOVE
        self._client_model_class: str = None            # line 95  <-- REMOVE
        self._client_loop_id: Optional[int] = None      # line 99  <-- REMOVE
        self.voice_db = VoiceRegistry(...)              # line 101

    @staticmethod
    def _is_gemini3_model(model: str) -> bool:          # line 104
    @staticmethod
    def _is_preview_model(model: str) -> bool:          # line 115
    @staticmethod
    def _requires_thinking(model: str) -> bool:         # line 123
    @staticmethod
    def _as_model_str(model) -> str:                    # line 139
    def _model_class_key(self, model: str) -> str:      # line 153  <-- KEEP, used by hook

    def _current_loop_id(self) -> Optional[int]:        # line 165  <-- REMOVE
    async def _ensure_client(self, model=None) -> genai.Client:  # line 172  <-- REWRITE
    async def get_client(self, model=None, **kwargs) -> genai.Client:  # line 200  <-- SIMPLIFY
    async def close(self):                              # line ~290 <-- SIMPLIFY

    # Call sites that invoke self._ensure_client(...) — do NOT rewrite
    # their call signatures; the new subclass _ensure_client keeps
    # ``model=...`` kwarg compatibility:
    #   simple_chat loop                  line 1897
    #   stateful retry rebuild            line 2113
    #   streaming retry rebuild           line 2721
    #   image/file-upload path            line 3115
    #   suspended-state resume            line 3349
```

### Does NOT Exist

- ~~`GoogleGenAIClient.per_call_client()`~~ — not a method; spec rejects per-call clients.
- ~~`AbstractClient._loop_meta`~~ — base does not have this; use `_clients_by_loop[id].metadata`.
- ~~`self._client_loop_id` after this task~~ — must be removed.
- ~~`await self.close()` mid-request for error recovery~~ — must migrate to `_close_current_loop_entry()` (spec §7 gotcha).

---

## Implementation Notes

### Key Constraints

- Preserve the 5 existing call sites' `_ensure_client(model=...)` signature
  by keeping the subclass override's keyword argument. The override simply
  folds `model` into `hints` before delegating to `super()._ensure_client`.
- Stamp `entry.metadata["model_class"]` AFTER `super()._ensure_client(...)`
  returns, so it is correct whether the entry was reused or rebuilt.
- The base class already logs the cache miss; the subclass should NOT add a
  duplicate log.
- Keep `self.voice_db` and every other non-loop-related attribute exactly as-is.
- Google's error-recovery branches that currently do
  `await self.close(); await self._ensure_client(...)` must become
  `await self._close_current_loop_entry(); await self._ensure_client(...)` to
  avoid evicting healthy sibling-loop entries.

### References in Codebase

- Base class (dependency): `packages/ai-parrot/src/parrot/clients/base.py` post-TASK-795.
- Hook contract: see `AbstractClient._client_invalid_for_current` (docstring).
- Example `_ensure_client(model=...)` call site: `google/client.py:1897`.

---

## Acceptance Criteria

- [ ] `grep -n '_client_loop_id' packages/ai-parrot/src/parrot/clients/google/client.py` → no matches.
- [ ] `grep -n '_current_loop_id' packages/ai-parrot/src/parrot/clients/google/client.py` → no matches.
- [ ] `grep -n '_client_model_class' packages/ai-parrot/src/parrot/clients/google/client.py` → no matches (state lives in entry metadata now).
- [ ] `_client_invalid_for_current` is overridden and returns `True` when the
      cached entry's `metadata["model_class"]` differs from the one implied by
      the incoming `model` hint.
- [ ] After a successful `_ensure_client(model=...)` call, the current loop's
      entry has `entry.metadata["model_class"]` set to the matching key.
- [ ] Every pre-existing `await self.close()` mid-request error-recovery path
      has become `await self._close_current_loop_entry()`.
- [ ] `get_client(self, model=None, **kwargs) -> genai.Client` no longer
      references loop ids or `self._client_model_class`; it simply constructs
      and returns a fresh client.
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/google/client.py` is clean.
- [ ] Import smoke: `python -c "from parrot.clients.google.client import GoogleGenAIClient"` succeeds.

---

## Test Specification

> Formal tests in TASK-800. For this task, a repl smoke is sufficient:

```python
import asyncio
from parrot.clients.google.client import GoogleGenAIClient

async def _smoke():
    c = GoogleGenAIClient()   # requires Google creds; skip if unavailable
    # Just assert the hook signature is wired correctly:
    assert hasattr(c, "_client_invalid_for_current")
    assert c._client_invalid_for_current(object(), model="gemini-2.5-flash") is True  # no entry yet

asyncio.run(_smoke())
```

---

## Agent Instructions

1. Verify TASK-795 is in `sdd/tasks/completed/` before starting.
2. Read spec §3 Module 2 + §7 Known Risks.
3. Verify the Codebase Contract — line numbers for removals / overrides.
4. Update status to `"in-progress"` in the index.
5. Apply scoped edits to `google/client.py`.
6. Run grep acceptance checks; run ruff; run a collect-only pytest on
   `packages/ai-parrot/tests/test_google_client.py` to ensure imports still work.
7. Move this file to `sdd/tasks/completed/`; update the index.
8. Commit: `sdd: TASK-796 — Google GenAI client migrates to base per-loop hook`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**:
