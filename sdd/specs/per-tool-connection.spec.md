---
type: feature
base_branch: dev
---

# Feature Specification: Per-Tool Connection Lifecycle

**Feature ID**: FEAT-391
**Date**: 2026-07-30
**Author**: Jesus Lara
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

Tools and toolkits that depend on external resources (database connections,
HTTP sessions, message broker channels, etc.) currently have no standardized
async lifecycle for acquiring and releasing those resources. The only
framework-provided hooks are:

- `AbstractToolkit.start()` / `stop()` / `cleanup()` — **public** methods
  that must be called manually by the agent or ToolManager. They are also
  visible to `_generate_tools()` and must be explicitly listed in
  `exclude_tools` to prevent the LLM from calling them.
- `AbstractToolkit._pre_execute()` / `_post_execute()` — per-call hooks,
  not meant for one-time resource setup/teardown.

Standalone `AbstractTool` subclasses have no lifecycle hooks at all beyond
`_execute()`. This forces tool authors to inline connection management
inside `_execute()`:

```python
async def _execute(self, **kwargs):
    conn = await get_connection()      # boilerplate
    try:
        result = await conn.query(...)  # actual logic
    finally:
        await conn.close()             # boilerplate
```

This pattern is error-prone (easy to forget cleanup), hard to test (every
test must mock the connection setup), and couples the tool's business logic
to its resource management.

### Goals

- Provide `_open()` and `_close()` async lifecycle methods on both
  `AbstractTool` and `AbstractToolkit` that are called automatically by
  the framework — no manual calling required.
- `_open()` is called once when the toolkit is first used (lazy
  initialization on first tool call) or eagerly via an explicit opt-in.
- `_close()` is called during toolkit/tool shutdown (via `ToolManager.cleanup_toolkits()`
  or agent teardown).
- The methods are **private** (underscore-prefixed) so `AbstractToolkit._generate_tools()`
  never exposes them as LLM-callable tools.
- Existing `start()` / `stop()` / `cleanup()` remain unchanged for
  backward compatibility — `_open()` / `_close()` are a lower-level,
  automatic alternative.
- Reduce boilerplate for database-backed toolkits like `DatabaseToolkit`
  and `DatabaseQueryToolkit`.

### Non-Goals (explicitly out of scope)

- Connection pooling or pool management — that remains the responsibility
  of the concrete tool/toolkit implementation inside `_open()`.
- Retry/reconnect logic on transient failures — out of scope for the
  lifecycle hooks themselves (can be implemented inside `_open()`).
- Changing the `@tool` decorator — standalone decorated functions are
  stateless and do not need resource lifecycle.
- Removing the existing `start()` / `stop()` / `cleanup()` public methods.

---

## 2. Architectural Design

### Overview

Add two protected async methods to `AbstractTool` and `AbstractToolkit`:

- `async def _open(self) -> None` — acquire resources (connections, sessions,
  pools). Default implementation is a no-op. Called **at most once** per
  instance lifetime (idempotent via an `_opened` flag).
- `async def _close(self) -> None` — release resources. Default
  implementation is a no-op. Called **at most once** per instance lifetime
  (idempotent via the same `_opened` flag).

**Calling convention:**

| Layer | When `_open()` is called | When `_close()` is called |
|---|---|---|
| `AbstractTool.execute()` | Before `_execute()`, on first call (lazy) | Via `ToolManager.cleanup_toolkits()` or explicit call |
| `AbstractToolkit` (via `ToolkitTool._execute()`) | Before the first tool in the toolkit executes (lazy) | Via `ToolManager.cleanup_toolkits()` or explicit call |

The lazy-init approach means no async I/O happens during `__init__()`,
which is important because `__init__` is synchronous.

A class-level flag `auto_open: bool = False` controls whether the
lazy-init seam is active. Toolkits/tools that set `auto_open = True`
get automatic `_open()` on first call; others must call `_open()` manually
(or via `start()`). This prevents surprise I/O for simple tools that
don't need resource management.

### Component Diagram

```
AbstractTool
  ├── _opened: bool = False
  ├── auto_open: bool = False
  ├── async _open() → None        # override in subclasses
  ├── async _close() → None       # override in subclasses
  ├── async _ensure_open() → None # idempotent _open() gate
  └── execute()
        ├── [if auto_open] await _ensure_open()
        ├── ... existing logic ...
        └── await _execute()

AbstractToolkit
  ├── _opened: bool = False
  ├── auto_open: bool = False
  ├── async _open() → None
  ├── async _close() → None
  ├── async _ensure_open() → None
  └── (via ToolkitTool._execute())
        ├── [if toolkit.auto_open] await toolkit._ensure_open()
        ├── await toolkit._pre_execute()
        ├── await bound_method()
        └── await toolkit._post_execute()

ToolManager.cleanup_toolkits()
  └── for each toolkit:
        ├── await toolkit._close()   # NEW — always called
        └── await toolkit.cleanup()  # existing behavior preserved
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractTool` | extends | Add `_open()`, `_close()`, `_ensure_open()`, `_opened`, `auto_open` |
| `AbstractToolkit` | extends | Add `_open()`, `_close()`, `_ensure_open()`, `_opened`, `auto_open` |
| `ToolkitTool._execute()` | modifies | Insert `_ensure_open()` call before `_pre_execute()` |
| `AbstractTool.execute()` | modifies | Insert `_ensure_open()` call before `_execute()` |
| `ToolManager.cleanup_toolkits()` | modifies | Call `_close()` during cleanup |
| `DatabaseToolkit` | consumer | Can migrate `start()` internals to `_open()` |

### Data Models

No new Pydantic models required. Only instance attributes:

```python
# On AbstractTool and AbstractToolkit:
_opened: bool = False
auto_open: bool = False  # class-level, opt-in
```

### New Public Interfaces

```python
# AbstractTool (abstract.py)
class AbstractTool(EventEmitterMixin, ABC):
    auto_open: bool = False

    async def _open(self) -> None:
        """Acquire external resources. Override in subclasses."""

    async def _close(self) -> None:
        """Release external resources. Override in subclasses."""

    async def _ensure_open(self) -> None:
        """Idempotent gate: calls _open() at most once."""
        if not self._opened:
            await self._open()
            self._opened = True


# AbstractToolkit (toolkit.py)
class AbstractToolkit(ABC):
    auto_open: bool = False

    async def _open(self) -> None:
        """Acquire external resources. Override in subclasses."""

    async def _close(self) -> None:
        """Release external resources. Override in subclasses."""

    async def _ensure_open(self) -> None:
        """Idempotent gate: calls _open() at most once."""
        if not self._opened:
            await self._open()
            self._opened = True
```

---

## 3. Module Breakdown

### Module 1: AbstractTool Lifecycle Hooks

- **Path**: `packages/ai-parrot/src/parrot/tools/abstract.py`
- **Responsibility**: Add `_open()`, `_close()`, `_ensure_open()`, `_opened`
  flag, and `auto_open` class attribute to `AbstractTool`. Modify `execute()`
  to call `_ensure_open()` when `auto_open` is True.
- **Depends on**: none

### Module 2: AbstractToolkit Lifecycle Hooks

- **Path**: `packages/ai-parrot/src/parrot/tools/toolkit.py`
- **Responsibility**: Add `_open()`, `_close()`, `_ensure_open()`, `_opened`
  flag, and `auto_open` class attribute to `AbstractToolkit`. Modify
  `ToolkitTool._execute()` to call `toolkit._ensure_open()` when
  `toolkit.auto_open` is True, before `_pre_execute()`.
- **Depends on**: Module 1 (shared pattern)

### Module 3: ToolManager Cleanup Integration

- **Path**: `packages/ai-parrot/src/parrot/tools/manager.py`
- **Responsibility**: Modify `cleanup_toolkits()` to call `_close()` on each
  toolkit (and standalone tools) before calling `cleanup()` / `stop()`.
  Also handle standalone `AbstractTool` instances that override `_close()`.
- **Depends on**: Module 1, Module 2

### Module 4: Tests

- **Path**: `packages/ai-parrot/tests/tools/test_tool_connection_lifecycle.py`
- **Responsibility**: Unit tests covering `_open()`/`_close()` semantics for
  both `AbstractTool` and `AbstractToolkit`, idempotency, error handling,
  and `ToolManager.cleanup_toolkits()` integration.
- **Depends on**: Module 1, Module 2, Module 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_abstract_tool_open_not_called_without_auto_open` | Module 1 | Verify `_open()` is NOT called during `execute()` when `auto_open=False` |
| `test_abstract_tool_auto_open_calls_open_once` | Module 1 | Verify `_open()` is called exactly once on first `execute()` when `auto_open=True` |
| `test_abstract_tool_ensure_open_idempotent` | Module 1 | Calling `_ensure_open()` multiple times only calls `_open()` once |
| `test_abstract_tool_close_called_on_cleanup` | Module 3 | Verify `_close()` is called during `ToolManager.cleanup_toolkits()` |
| `test_abstract_tool_close_idempotent` | Module 1 | Calling `_close()` after already closed is a no-op |
| `test_toolkit_auto_open_on_first_tool_call` | Module 2 | First tool execution triggers `toolkit._open()` |
| `test_toolkit_open_before_pre_execute` | Module 2 | `_open()` runs before `_pre_execute()` |
| `test_toolkit_close_in_cleanup` | Module 3 | `ToolManager.cleanup_toolkits()` calls `toolkit._close()` |
| `test_open_error_propagates` | Module 1 | If `_open()` raises, the tool call fails with a clear error |
| `test_close_error_logged_not_raised` | Module 3 | If `_close()` raises during cleanup, it is logged but does not prevent other toolkits from closing |

### Integration Tests

| Test | Description |
|---|---|
| `test_database_toolkit_open_close_flow` | Verify a `DatabaseToolkit`-style subclass with `auto_open=True` connects on first tool call and disconnects during cleanup |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_tool():
    """Tool subclass that tracks _open/_close calls."""
    class TrackingTool(AbstractTool):
        auto_open = True
        open_count = 0
        close_count = 0

        async def _open(self):
            self.open_count += 1

        async def _close(self):
            self.close_count += 1

        async def _execute(self, **kwargs):
            return "ok"

    return TrackingTool(name="tracking_tool")
```

---

## 5. Acceptance Criteria

- [ ] `AbstractTool` exposes `_open()`, `_close()`, `_ensure_open()` async methods
- [ ] `AbstractToolkit` exposes `_open()`, `_close()`, `_ensure_open()` async methods
- [ ] When `auto_open = True`, `_open()` is called lazily on first `execute()` / first toolkit tool call
- [ ] When `auto_open = False` (default), no automatic `_open()` call occurs — backward compatible
- [ ] `_open()` is idempotent — called at most once per instance via `_ensure_open()`
- [ ] `_close()` is called during `ToolManager.cleanup_toolkits()` for all registered toolkits and standalone tools
- [ ] `_close()` errors are logged but do not prevent other toolkits from closing
- [ ] `_open()` and `_close()` are NOT exposed as LLM-callable tools (private, underscore-prefixed)
- [ ] Existing `start()` / `stop()` / `cleanup()` behavior is unchanged
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/tools/test_tool_connection_lifecycle.py -v`
- [ ] No breaking changes to existing tool/toolkit subclasses

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: packages/ai-parrot/src/parrot/tools/__init__.py:142
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool  # verified: packages/ai-parrot/src/parrot/tools/__init__.py:143
from parrot.tools import AbstractTool, AbstractToolkit, ToolkitTool, tool  # verified: packages/ai-parrot/src/parrot/tools/__init__.py:214-219
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):  # line 126
    name: str = None  # line 141
    description: str = None  # line 142
    auto_open: bool = False  # DOES NOT EXIST YET — to be added
    _opened: bool  # DOES NOT EXIST YET — to be added

    def __init__(self, name, description, output_dir, base_url, static_dir,
                 routing_meta, executor, webhook_callback_url,
                 remote_timeout_seconds, **kwargs):  # line 156

    async def _execute(self, **kwargs) -> Any:  # line 293 (abstract)

    async def execute(self, *args, **kwargs) -> ToolResult:  # line 527
        # Permission check at line 543
        # FEAT-176 lifecycle at line 581
        # Actual _execute() call at line 665
        # FEAT-252 scrubbing at line 709

    async def run(self, *args, **kwargs) -> Any:  # line 801


# packages/ai-parrot/src/parrot/tools/toolkit.py
class ToolkitTool(AbstractTool):  # line (inside toolkit.py)
    async def _execute(self, **kwargs) -> Any:
        # Gets toolkit via getattr(self.bound_method, "__self__", None)
        # Calls toolkit._pre_execute() BEFORE the bound method
        # Calls toolkit._post_execute() AFTER the bound method

class AbstractToolkit(ABC):  # line 218 area
    exclude_tools: tuple[str, ...] = ()  # class attr
    auto_open: bool  # DOES NOT EXIST YET — to be added
    _opened: bool  # DOES NOT EXIST YET — to be added

    def __init__(self, **kwargs):
        # Sets self._tool_cache, self._tools_generated, self.logger

    async def start(self) -> None:  # existing — no-op default
    async def stop(self) -> None:   # existing — no-op default
    async def cleanup(self) -> None:  # existing — no-op default

    async def _pre_execute(self, tool_name, /, **kwargs) -> None:  # existing lifecycle hook
    async def _post_execute(self, tool_name, result, /, **kwargs) -> Any:  # existing lifecycle hook


# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    async def cleanup_toolkits(self) -> None:  # line 1922
        # Iterates registered ToolkitTool instances
        # Gets parent toolkit via bound_method.__self__
        # Calls cleanup() or stop() on each unique toolkit
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AbstractTool._ensure_open()` | `AbstractTool.execute()` | inserted before `_execute()` call | `abstract.py:601` (try block) |
| `AbstractToolkit._ensure_open()` | `ToolkitTool._execute()` | inserted before `_pre_execute()` call | `toolkit.py` (ToolkitTool._execute) |
| `AbstractToolkit._close()` | `ToolManager.cleanup_toolkits()` | called before existing cleanup/stop | `manager.py:1945` |
| `AbstractTool._close()` | `ToolManager.cleanup_toolkits()` | new loop for standalone tools | `manager.py:1922` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractTool._open()`~~ — does not exist yet (this spec adds it)
- ~~`AbstractTool._close()`~~ — does not exist yet (this spec adds it)
- ~~`AbstractTool._ensure_open()`~~ — does not exist yet (this spec adds it)
- ~~`AbstractTool.auto_open`~~ — does not exist yet (this spec adds it)
- ~~`AbstractTool._opened`~~ — does not exist yet (this spec adds it)
- ~~`AbstractToolkit._open()`~~ — does not exist yet (this spec adds it)
- ~~`AbstractToolkit._close()`~~ — does not exist yet (this spec adds it)
- ~~`AbstractToolkit._ensure_open()`~~ — does not exist yet (this spec adds it)
- ~~`AbstractToolkit.auto_open`~~ — does not exist yet (this spec adds it)
- ~~`AbstractToolkit._opened`~~ — does not exist yet (this spec adds it)
- ~~`ToolManager.initialize_toolkits()`~~ — no such method exists
- ~~`AbstractToolkit.connect()`~~ — no such method exists
- ~~`AbstractTool.connect()`~~ — no such method exists

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Follow the existing `_pre_execute()` / `_post_execute()` lifecycle hook
  pattern from `AbstractToolkit` (FEAT-305/TASK-747).
- Use underscore-prefixed method names so `_generate_tools()` in
  `AbstractToolkit` skips them (it only wraps public async methods).
- Keep `_open()` / `_close()` as simple no-op defaults that subclasses
  override — same pattern as `start()` / `stop()`.
- The `_opened` flag must be set in `__init__()` (not as a class
  attribute that gets shared across instances).

### Known Risks / Gotchas

- **Concurrency**: `_ensure_open()` uses a simple boolean flag, not a lock.
  This matches the existing `_current_pctx` pattern (see `abstract.py:577`
  comment) — single-agent sessions where a given tool instance is never
  awaited concurrently. If concurrent access becomes a requirement,
  `_ensure_open()` should be upgraded to use `asyncio.Lock`.
- **Error in `_open()`**: If `_open()` raises, the tool call must fail with
  a clear error. The `_opened` flag must NOT be set, so the next call
  retries `_open()`.
- **Error in `_close()`**: During cleanup, `_close()` errors must be
  caught and logged (not raised) to prevent one broken toolkit from
  blocking cleanup of others.
- **Existing `DatabaseToolkit`**: Already has `start()` / `stop()` with
  connection management. Migration to `_open()` / `_close()` is optional
  and out of scope for this feature — but the new hooks should be designed
  so `DatabaseToolkit` *could* adopt them by overriding `_open()` →
  `_connect_asyncdb()` and `_close()` → `stop()` body.
- **`_generate_tools()` safety**: `AbstractToolkit._generate_tools()` only
  wraps public (non-underscore) async methods. Since `_open`, `_close`,
  and `_ensure_open` are all underscore-prefixed, they will never appear
  as LLM-callable tools. No `exclude_tools` entry needed.

### External Dependencies

None — no new packages required.

---

## 8. Open Questions

- [ ] Should `_open()` failure set a permanent "failed" state that prevents
  retries, or should each `execute()` call retry `_open()` until it
  succeeds? — *Owner: Jesus*
  *Recommendation*: retry on each call (don't set `_opened = True` on failure)
  so transient errors (network blip) recover automatically.
- [ ] Should `_close()` reset the `_opened` flag so `_open()` can be called
  again (reusable lifecycle) or is it terminal? — *Owner: Jesus*
  *Recommendation*: reset `_opened = False` in `_close()` so toolkits can
  be stopped and restarted.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks)
- All four modules are tightly coupled (each builds on the previous).
- No cross-feature dependencies.
- Single worktree, sequential task execution.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-30 | Jesus Lara (via Claude) | Initial draft |
