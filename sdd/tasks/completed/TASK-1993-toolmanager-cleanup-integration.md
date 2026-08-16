# TASK-1993: ToolManager Cleanup Integration

**Feature**: FEAT-391 — Per-Tool Connection Lifecycle
**Spec**: `sdd/specs/per-tool-connection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1991, TASK-1992
**Assigned-to**: unassigned

---

## Context

This task modifies `ToolManager.cleanup_toolkits()` to call `_close()` on
each registered toolkit (and on standalone `AbstractTool` instances) during
shutdown. This ensures resources acquired via `_open()` are released
automatically when the agent session ends.

Currently `cleanup_toolkits()` only calls `cleanup()` or `stop()` on
toolkits. This task adds `_close()` as the first step — before the existing
`cleanup()`/`stop()` call — so resources are released even if the toolkit
author only overrides `_close()` and not `cleanup()`.

Implements spec §3 Module 3.

---

## Scope

- Modify `ToolManager.cleanup_toolkits()` to call `await toolkit._close()`
  on each unique toolkit BEFORE calling `cleanup()` / `stop()`.
- Add a second loop for standalone `AbstractTool` instances (non-ToolkitTool)
  that call `await tool._close()` when the tool has `_opened = True`.
- `_close()` errors must be caught and logged (not raised), matching the
  existing error-isolation pattern in `cleanup_toolkits()`.

**NOT in scope**:
- AbstractTool changes (TASK-1991)
- AbstractToolkit changes (TASK-1992)
- Test file creation (TASK-1994)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Modify `cleanup_toolkits()` to call `_close()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.manager import ToolManager  # verified: packages/ai-parrot/src/parrot/tools/manager.py:233
from parrot.tools.toolkit import ToolkitTool, AbstractToolkit  # verified: packages/ai-parrot/src/parrot/tools/__init__.py:143
from parrot.tools.abstract import AbstractTool  # verified: packages/ai-parrot/src/parrot/tools/__init__.py:142
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/manager.py:233
class ToolManager(MCPToolManagerMixin):
    # self._tools: Dict[str, AbstractTool]  — the tool registry

    async def cleanup_toolkits(self) -> None:  # line 1922
        # Current implementation:
        # 1. Imports ToolkitTool
        # 2. Iterates self._tools.values()
        # 3. For ToolkitTool instances: gets parent toolkit via bound_method.__self__
        # 4. Deduplicates by id(toolkit) via `seen` set
        # 5. Calls cleanup() or stop() on each unique toolkit
        # 6. Catches and logs exceptions per-toolkit
```

The full current implementation (lines 1922-1955):

```python
async def cleanup_toolkits(self) -> None:
    from .toolkit import ToolkitTool
    seen: set[int] = set()
    for tool in self._tools.values():
        if not isinstance(tool, ToolkitTool):
            continue
        bound = getattr(tool, 'bound_method', None)
        if bound is None:
            continue
        toolkit = getattr(bound, '__self__', None)
        if toolkit is None:
            continue
        tk_id = id(toolkit)
        if tk_id in seen:
            continue
        seen.add(tk_id)
        cleanup_fn = getattr(toolkit, 'cleanup', None) or getattr(toolkit, 'stop', None)
        if cleanup_fn and callable(cleanup_fn):
            try:
                result = cleanup_fn()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                self.logger.debug(
                    "Error cleaning up toolkit %s: %s",
                    type(toolkit).__name__, exc,
                )
```

### Does NOT Exist

- ~~`ToolManager.close_all_tools()`~~ — no such method
- ~~`ToolManager.shutdown()`~~ — no such method
- ~~`ToolManager._standalone_tools`~~ — no such attribute; all tools are in `self._tools`

---

## Implementation Notes

### Modified `cleanup_toolkits()` structure

```python
async def cleanup_toolkits(self) -> None:
    from .toolkit import ToolkitTool
    seen: set[int] = set()

    # --- Phase 1: close and clean up toolkits ---
    for tool in self._tools.values():
        if not isinstance(tool, ToolkitTool):
            continue
        bound = getattr(tool, 'bound_method', None)
        if bound is None:
            continue
        toolkit = getattr(bound, '__self__', None)
        if toolkit is None:
            continue
        tk_id = id(toolkit)
        if tk_id in seen:
            continue
        seen.add(tk_id)

        # NEW: call _close() first (resource release)
        if getattr(toolkit, '_opened', False):
            try:
                await toolkit._close()
            except Exception as exc:
                self.logger.debug(
                    "Error in _close() for toolkit %s: %s",
                    type(toolkit).__name__, exc,
                )

        # Existing: call cleanup() or stop()
        cleanup_fn = getattr(toolkit, 'cleanup', None) or getattr(toolkit, 'stop', None)
        if cleanup_fn and callable(cleanup_fn):
            try:
                result = cleanup_fn()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                self.logger.debug(
                    "Error cleaning up toolkit %s: %s",
                    type(toolkit).__name__, exc,
                )

    # --- Phase 2: close standalone tools (non-ToolkitTool) ---
    for tool in self._tools.values():
        if isinstance(tool, ToolkitTool):
            continue
        if getattr(tool, '_opened', False):
            try:
                await tool._close()
            except Exception as exc:
                self.logger.debug(
                    "Error in _close() for tool %s: %s",
                    tool.name, exc,
                )
```

### Key Constraints

- `_close()` errors must be caught and logged, never raised — matches
  existing error-isolation pattern.
- Use `getattr(toolkit, '_opened', False)` as a guard to avoid calling
  `_close()` on toolkits that never opened (no-op but cleaner).
- The `_close()` call goes BEFORE `cleanup()`/`stop()` — resource release
  should happen before any additional cleanup logic.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/manager.py:1922-1955` — existing cleanup_toolkits()

---

## Acceptance Criteria

- [ ] `cleanup_toolkits()` calls `_close()` on each unique toolkit that has `_opened=True`
- [ ] `cleanup_toolkits()` calls `_close()` on standalone tools that have `_opened=True`
- [ ] `_close()` errors are caught and logged, not raised
- [ ] `_close()` is called BEFORE `cleanup()` / `stop()`
- [ ] Existing `cleanup()` / `stop()` behavior is preserved
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/manager.py`
- [ ] Existing tests still pass: `pytest packages/ai-parrot/tests/tools/ -v -x --timeout=30`

---

## Test Specification

Tests are created in TASK-1994. This task only modifies the production code.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/per-tool-connection.spec.md` for full context
2. **Check dependencies** — verify TASK-1991 and TASK-1992 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `cleanup_toolkits()` still matches
   the implementation shown above
4. **Update status** in `sdd/tasks/index/per-tool-connection.json` → `"in-progress"`
5. **Implement** the scope above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-1993-toolmanager-cleanup-integration.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-31
**Notes**: Modified `ToolManager.cleanup_toolkits()` exactly per the task's specified
structure: Phase 1 (existing toolkit loop) now calls `await toolkit._close()` before
`cleanup()`/`stop()` when `getattr(toolkit, '_opened', False)` is truthy, wrapped in
its own try/except that logs via `self.logger.debug` (never raises). Added a new
Phase 2 loop over standalone (non-`ToolkitTool`) tools that calls `await
tool._close()` under the same `_opened` guard and same catch-log pattern.

Verified manually: a toolkit with `auto_open=True` gets `_close()` called exactly
once during `cleanup_toolkits()` (and `_opened` reset to False by the base
`_close()`); a standalone tool with `auto_open=True` gets the same treatment; a
tool whose `_close()` raises has the error caught and logged without blocking
cleanup of the other tools/toolkits (confirmed the `good` tool's `_close()` still
ran after the `broken` tool's `_close()` raised).

`ruff check` on `manager.py`: 134 pre-existing errors -> 136 after (net +2,
both `BLE001` "blind Exception catch" on the two new `except Exception as exc:`
blocks — this matches the exact pattern already used one line above them in the
same function, per the task's own Codebase Contract code sample; no new
violation categories introduced).
`pytest packages/ai-parrot/tests/tools/ -v`: 51 failed / 674 passed / 8 skipped —
identical to the unmodified `dev` baseline; all failures are pre-existing and
unrelated (databasequery toolkit / auto-registration hook tests).

**Deviations from spec**: none.
