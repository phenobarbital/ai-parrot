# TASK-1994: Connection Lifecycle Tests

**Feature**: FEAT-391 — Per-Tool Connection Lifecycle
**Spec**: `sdd/specs/per-tool-connection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1991, TASK-1992, TASK-1993
**Assigned-to**: unassigned

---

## Context

This task creates the comprehensive test suite for the `_open()` / `_close()`
lifecycle hooks added by TASK-1991 through TASK-1993. Tests cover both
`AbstractTool` and `AbstractToolkit` lifecycle semantics, idempotency,
error handling, and `ToolManager.cleanup_toolkits()` integration.

Implements spec §4 (Test Specification).

---

## Scope

- Create test file `packages/ai-parrot/tests/tools/test_tool_connection_lifecycle.py`
- Test `AbstractTool` lifecycle:
  - `_open()` not called when `auto_open=False`
  - `_open()` called once on first `execute()` when `auto_open=True`
  - `_ensure_open()` is idempotent
  - `_close()` resets `_opened` flag
  - `_open()` error keeps `_opened=False` (retry on next call)
- Test `AbstractToolkit` lifecycle:
  - `_open()` called on first tool call when `auto_open=True`
  - `_ensure_open()` called before `_pre_execute()`
  - `_open()` not called when `auto_open=False`
- Test `ToolManager.cleanup_toolkits()` integration:
  - `_close()` called on toolkits during cleanup
  - `_close()` called on standalone tools during cleanup
  - `_close()` errors logged, not raised
  - `_close()` not called on non-opened tools/toolkits

**NOT in scope**:
- Production code changes (those are in TASK-1991/1992/1993)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/tools/test_tool_connection_lifecycle.py` | CREATE | Full test suite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: packages/ai-parrot/src/parrot/tools/__init__.py:142
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool  # verified: packages/ai-parrot/src/parrot/tools/__init__.py:143
from parrot.tools.manager import ToolManager  # verified: packages/ai-parrot/src/parrot/tools/manager.py:233

# After TASK-1991, AbstractTool will have:
#   auto_open: bool = False  (class attr)
#   _opened: bool  (instance attr, set in __init__)
#   async def _open(self) -> None
#   async def _close(self) -> None
#   async def _ensure_open(self) -> None

# After TASK-1992, AbstractToolkit will have the same set.
# ToolkitTool._execute() will call toolkit._ensure_open() when toolkit.auto_open=True.

# After TASK-1993, ToolManager.cleanup_toolkits() will call _close() on toolkits and standalone tools.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/abstract.py:126
class AbstractTool(EventEmitterMixin, ABC):
    auto_open: bool = False  # added by TASK-1991
    async def _open(self) -> None: ...  # added by TASK-1991
    async def _close(self) -> None: ...  # added by TASK-1991
    async def _ensure_open(self) -> None: ...  # added by TASK-1991
    async def execute(self, *args, **kwargs) -> ToolResult: ...  # line 527

# packages/ai-parrot/src/parrot/tools/toolkit.py:207
class AbstractToolkit(ABC):
    auto_open: bool = False  # added by TASK-1992
    async def _open(self) -> None: ...  # added by TASK-1992
    async def _close(self) -> None: ...  # added by TASK-1992
    async def _ensure_open(self) -> None: ...  # added by TASK-1992

# packages/ai-parrot/src/parrot/tools/manager.py:233
class ToolManager(MCPToolManagerMixin):
    async def cleanup_toolkits(self) -> None: ...  # line 1922, modified by TASK-1993
```

### Does NOT Exist

- ~~`AbstractTool.connect()`~~ — no such method
- ~~`AbstractToolkit.connect()`~~ — no such method
- ~~`ToolManager.close_all_tools()`~~ — no such method
- ~~`parrot.tools.lifecycle`~~ — no such module

---

## Implementation Notes

### Test fixtures

```python
import pytest
from unittest.mock import AsyncMock, patch


class TrackingTool(AbstractTool):
    """Tool subclass that tracks _open/_close calls."""
    auto_open = True
    open_count = 0
    close_count = 0

    async def _open(self):
        self.open_count += 1

    async def _close(self):
        await super()._close()  # resets _opened
        self.close_count += 1

    async def _execute(self, **kwargs):
        return "ok"


class TrackingToolkit(AbstractToolkit):
    """Toolkit subclass that tracks _open/_close calls."""
    auto_open = True
    open_count = 0
    close_count = 0

    async def _open(self):
        self.open_count += 1

    async def _close(self):
        await super()._close()
        self.close_count += 1

    async def greet(self, name: str) -> str:
        """Say hello."""
        return f"Hello, {name}"


class FailingOpenTool(AbstractTool):
    """Tool whose _open() always raises."""
    auto_open = True

    async def _open(self):
        raise ConnectionError("cannot connect")

    async def _execute(self, **kwargs):
        return "ok"
```

### Key test cases

1. **`test_auto_open_false_no_call`** — Create a tool with `auto_open=False`,
   call `execute()`, assert `_open()` was NOT called.

2. **`test_auto_open_true_calls_once`** — Create `TrackingTool`, call
   `execute()` twice, assert `open_count == 1`.

3. **`test_ensure_open_idempotent`** — Call `_ensure_open()` 5 times,
   assert `open_count == 1`.

4. **`test_close_resets_opened`** — Open, then close, assert `_opened == False`.
   Call `_ensure_open()` again, assert `open_count == 2` (re-opened).

5. **`test_open_error_retries`** — Use `FailingOpenTool`, call `execute()`,
   assert `_opened` is still False. Patch `_open` to succeed, call
   `execute()` again, assert it works.

6. **`test_toolkit_auto_open_on_first_tool`** — Create `TrackingToolkit`,
   get tools, call the first tool, assert `open_count == 1`.

7. **`test_toolkit_open_before_pre_execute`** — Mock `_pre_execute` and
   `_ensure_open`, verify call order.

8. **`test_cleanup_calls_close`** — Register toolkit in ToolManager, call
   `cleanup_toolkits()`, assert `_close()` was called.

9. **`test_cleanup_close_error_logged`** — Register toolkit whose `_close()`
   raises, call `cleanup_toolkits()`, assert no exception raised and
   error was logged.

10. **`test_cleanup_standalone_tool`** — Register a standalone tool with
    `_opened=True` in ToolManager, call `cleanup_toolkits()`, assert
    `_close()` was called.

### Key Constraints

- Use `pytest-asyncio` for async tests
- Use `pytest.mark.asyncio` decorator
- Do NOT hit real databases or external services
- Mock/stub only what's necessary — prefer actual class instantiation

### References in Codebase

- `packages/ai-parrot/tests/tools/` — existing test directory
- `packages/ai-parrot/tests/tools/test_abstract_tool.py` — if it exists, follow its patterns
- `packages/ai-parrot/tests/tools/compression/test_manager_integration.py` — ToolManager test patterns

---

## Acceptance Criteria

- [ ] Test file created at `packages/ai-parrot/tests/tools/test_tool_connection_lifecycle.py`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_tool_connection_lifecycle.py -v`
- [ ] Tests cover `AbstractTool` auto_open=True and auto_open=False paths
- [ ] Tests cover `AbstractToolkit` auto_open on first tool call
- [ ] Tests cover `_ensure_open()` idempotency
- [ ] Tests cover `_close()` resetting `_opened` flag
- [ ] Tests cover `_open()` failure keeping `_opened=False`
- [ ] Tests cover `ToolManager.cleanup_toolkits()` calling `_close()`
- [ ] Tests cover `_close()` error isolation in cleanup
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/tools/test_tool_connection_lifecycle.py`

---

## Test Specification

This task IS the test task. See the fixture and test case outlines in
Implementation Notes above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/per-tool-connection.spec.md` for full context
2. **Check dependencies** — verify TASK-1991, TASK-1992, and TASK-1993 are
   in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm all three prior tasks'
   implementations exist by reading `abstract.py`, `toolkit.py`, and
   `manager.py`
4. **Update status** in `sdd/tasks/index/per-tool-connection.json` → `"in-progress"`
5. **Implement** the test suite
6. **Run tests**: `pytest packages/ai-parrot/tests/tools/test_tool_connection_lifecycle.py -v`
7. **Verify** all acceptance criteria
8. **Move this file** to `sdd/tasks/completed/TASK-1994-connection-lifecycle-tests.md`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
