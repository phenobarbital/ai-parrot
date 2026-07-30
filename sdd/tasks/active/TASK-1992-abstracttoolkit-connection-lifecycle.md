# TASK-1992: AbstractToolkit Connection Lifecycle Hooks

**Feature**: FEAT-391 — Per-Tool Connection Lifecycle
**Spec**: `sdd/specs/per-tool-connection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1991
**Assigned-to**: unassigned

---

## Context

This task adds the same `_open()` / `_close()` / `_ensure_open()` lifecycle
hooks to `AbstractToolkit`, and modifies `ToolkitTool._execute()` to call
`toolkit._ensure_open()` before `_pre_execute()` when the toolkit has
`auto_open = True`.

This ensures that the first time any tool in a toolkit is called, the
toolkit's resource acquisition runs automatically. It mirrors the pattern
established in TASK-1991 for standalone `AbstractTool`.

Implements spec §2 and §3 Module 2.

---

## Scope

- Add `auto_open: bool = False` class attribute to `AbstractToolkit`
- Add `self._opened = False` instance attribute in `AbstractToolkit.__init__()`
- Add `async def _open(self) -> None` — no-op default
- Add `async def _close(self) -> None` — no-op default, resets `_opened = False`
- Add `async def _ensure_open(self) -> None` — idempotent gate
- Modify `ToolkitTool._execute()`: before the `_pre_execute()` call, insert
  `await toolkit._ensure_open()` when `toolkit.auto_open` is True

**NOT in scope**:
- AbstractTool changes (TASK-1991)
- ToolManager cleanup integration (TASK-1993)
- Test file creation (TASK-1994)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | Add lifecycle hooks to `AbstractToolkit`; modify `ToolkitTool._execute()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool  # verified: packages/ai-parrot/src/parrot/tools/__init__.py:143
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:32
class ToolkitTool(AbstractTool):
    def __init__(self, name, bound_method, description, args_schema, **kwargs):  # line 37

    async def _execute(self, **kwargs) -> Any:  # line 150
        # Gets toolkit: toolkit = getattr(self.bound_method, "__self__", None)
        # if isinstance(toolkit, AbstractToolkit):
        #     hook_kwargs = dict(kwargs); hook_kwargs["_permission_context"] = pctx
        #     await toolkit._pre_execute(self.name, **hook_kwargs)    <-- insert _ensure_open BEFORE this
        # if isinstance(toolkit, AbstractToolkit):
        #     kwargs = await toolkit._prepare_kwargs(self.name, kwargs)
        # ... filter kwargs, call bound_method ...
        # if isinstance(toolkit, AbstractToolkit):
        #     result = await toolkit._post_execute(self.name, result, **kwargs)


# packages/ai-parrot/src/parrot/tools/toolkit.py:207
class AbstractToolkit(ABC):
    exclude_tools: tuple[str, ...] = ()  # class attr
    tool_prefix: Optional[str] = None  # class attr
    confirming_tools: frozenset = frozenset()  # class attr
    credential_provider: Optional[str] = None  # class attr

    def __init__(self, **kwargs):  # line 296
        # Sets self.return_direct, self.base_url, self.credential_provider
        # Sets self.executor, self.webhook_callback_url, self.remote_timeout_seconds
        # Sets self._init_kwargs, self._tool_cache, self._tools_generated
        # Sets self.logger  (last attr set)

    async def start(self) -> None:  # line 337 — no-op default
    async def stop(self) -> None:  # line 344 — no-op default
    async def cleanup(self) -> None:  # line 351 — no-op default

    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:  # line 375
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any:  # line 390
```

### Does NOT Exist

- ~~`AbstractToolkit._open()`~~ — does not exist yet (this task adds it)
- ~~`AbstractToolkit._close()`~~ — does not exist yet (this task adds it)
- ~~`AbstractToolkit._ensure_open()`~~ — does not exist yet (this task adds it)
- ~~`AbstractToolkit.auto_open`~~ — does not exist yet (this task adds it)
- ~~`AbstractToolkit._opened`~~ — does not exist yet (this task adds it)
- ~~`AbstractToolkit.connect()`~~ — no such method
- ~~`ToolkitTool._ensure_open()`~~ — not on ToolkitTool; the gate is on the toolkit

---

## Implementation Notes

### Insertion point in `ToolkitTool._execute()`

The `_ensure_open()` call goes BEFORE `_pre_execute()` but after the
`isinstance(toolkit, AbstractToolkit)` check. Current structure:

```python
async def _execute(self, **kwargs) -> Any:
    toolkit = getattr(self.bound_method, "__self__", None)
    if isinstance(toolkit, AbstractToolkit):
        # ... build hook_kwargs ...
        await toolkit._pre_execute(self.name, **hook_kwargs)
```

Modify to:

```python
async def _execute(self, **kwargs) -> Any:
    toolkit = getattr(self.bound_method, "__self__", None)
    # NEW — lazy resource acquisition for the toolkit
    if isinstance(toolkit, AbstractToolkit) and toolkit.auto_open:
        await toolkit._ensure_open()
    if isinstance(toolkit, AbstractToolkit):
        # ... build hook_kwargs ...
        await toolkit._pre_execute(self.name, **hook_kwargs)
```

### Placement of new methods on AbstractToolkit

Place `_open()`, `_close()`, and `_ensure_open()` after `cleanup()` (line 351)
and before `_prepare_kwargs()` (line 358), keeping them grouped with the
other lifecycle methods. This mirrors the positioning in AbstractTool.

### Key Constraints

- `_opened` MUST be an instance attribute set in `__init__()`.
- `auto_open` is a class attribute.
- `_open()`, `_close()`, `_ensure_open()` are underscore-prefixed so
  `_generate_tools()` will never wrap them as LLM-callable tools (it
  only wraps public async methods).
- `_close()` should reset `_opened = False`.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/toolkit.py` — the file to modify
- `packages/ai-parrot/src/parrot/tools/abstract.py` — TASK-1991 adds the same pattern here

---

## Acceptance Criteria

- [ ] `AbstractToolkit` has `auto_open: bool = False` class attribute
- [ ] `AbstractToolkit.__init__()` sets `self._opened = False`
- [ ] `AbstractToolkit._open()` exists as async no-op
- [ ] `AbstractToolkit._close()` exists as async no-op, resets `_opened = False`
- [ ] `AbstractToolkit._ensure_open()` is idempotent
- [ ] `ToolkitTool._execute()` calls `toolkit._ensure_open()` when `toolkit.auto_open=True`
- [ ] `ToolkitTool._execute()` does NOT call `toolkit._ensure_open()` when `toolkit.auto_open=False`
- [ ] `_open`, `_close`, `_ensure_open` are NOT generated as LLM tools
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/toolkit.py`
- [ ] Existing tests still pass: `pytest packages/ai-parrot/tests/tools/ -v -x --timeout=30`

---

## Test Specification

Tests are created in TASK-1994. This task only modifies the production code.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/per-tool-connection.spec.md` for full context
2. **Check dependencies** — verify TASK-1991 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `AbstractToolkit` and `ToolkitTool`
   still have the same structure
4. **Update status** in `sdd/tasks/index/per-tool-connection.json` → `"in-progress"`
5. **Implement** the scope above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-1992-abstracttoolkit-connection-lifecycle.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
