# TASK-1991: AbstractTool Connection Lifecycle Hooks

**Feature**: FEAT-391 — Per-Tool Connection Lifecycle
**Spec**: `sdd/specs/per-tool-connection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task adds `_open()`, `_close()`, and `_ensure_open()` async lifecycle
methods to `AbstractTool`, plus the `auto_open` class attribute and `_opened`
instance flag. It also modifies `execute()` to call `_ensure_open()` when
`auto_open` is True, enabling automatic lazy resource acquisition on the
first tool call.

This is the foundation that Module 2 (AbstractToolkit) builds on — the same
pattern is applied to toolkits, which delegate to tools.

Implements spec §2 (Architectural Design) and §3 Module 1.

---

## Scope

- Add `auto_open: bool = False` class attribute to `AbstractTool`
- Add `self._opened = False` instance attribute in `__init__()`
- Add `async def _open(self) -> None` — no-op default, subclasses override
- Add `async def _close(self) -> None` — no-op default, subclasses override
- Add `async def _ensure_open(self) -> None` — idempotent gate: calls
  `_open()` at most once, sets `_opened = True` on success. Does NOT set
  `_opened` if `_open()` raises (allows retry on next call).
- Modify `execute()`: insert `await self._ensure_open()` when `self.auto_open`
  is True, BEFORE the existing `_execute()` call (after permission checks
  and lifecycle event emission, before argument validation and actual
  execution).
- `_close()` must reset `self._opened = False` after calling the no-op
  default (or subclass override), enabling reuse.

**NOT in scope**:
- AbstractToolkit changes (TASK-1992)
- ToolManager cleanup integration (TASK-1993)
- Test file creation (TASK-1994)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | Add `_open()`, `_close()`, `_ensure_open()`, `_opened`, `auto_open`; modify `execute()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: packages/ai-parrot/src/parrot/tools/__init__.py:142
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/abstract.py:126
class AbstractTool(EventEmitterMixin, ABC):
    name: str = None  # line 141
    description: str = None  # line 142
    args_schema: Type[BaseModel] = AbstractToolArgsSchema  # line 143
    return_direct: bool = False  # line 144
    credential_provider: Optional[str] = None  # line 150
    enable_redaction: bool = False  # line 154

    def __init__(self, name, description, output_dir, base_url, static_dir,
                 routing_meta, executor, webhook_callback_url,
                 remote_timeout_seconds, **kwargs):  # line 156
        # ... sets self.routing_meta, self.executor, self._init_kwargs, etc.
        # Last line of __init__: self._init_events()  # line 249

    @abstractmethod
    async def _execute(self, **kwargs) -> Any:  # line 293

    async def execute(self, *args, **kwargs) -> ToolResult:  # line 527
        # Permission check: lines 543-569
        # Store pctx: line 578
        # FEAT-176 lifecycle (BeforeToolCallEvent): lines 581-598
        # try block starts: line 601
        #   validate_args: line 605
        #   resolve kwargs: lines 608-611
        #   FEAT-264 credential seam: lines 617-671
        #     Actual _execute() call: lines 664-667
        # Normalise to ToolResult: lines 674-700
        # FEAT-252 scrubbing: lines 709-734
        # AfterToolCallEvent: lines 737-746
        # return: line 747
```

### Does NOT Exist

- ~~`AbstractTool._open()`~~ — does not exist yet (this task adds it)
- ~~`AbstractTool._close()`~~ — does not exist yet (this task adds it)
- ~~`AbstractTool._ensure_open()`~~ — does not exist yet (this task adds it)
- ~~`AbstractTool.auto_open`~~ — does not exist yet (this task adds it)
- ~~`AbstractTool._opened`~~ — does not exist yet (this task adds it)
- ~~`AbstractTool.connect()`~~ — no such method
- ~~`AbstractTool.disconnect()`~~ — no such method

---

## Implementation Notes

### Pattern to Follow

Follow the existing `_pre_execute()` / `_post_execute()` lifecycle hook
pattern — simple async methods with no-op defaults:

```python
# Existing pattern in toolkit.py (AbstractToolkit):
async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:
    return None

async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any:
    return result
```

### Key Constraints

- `_opened` MUST be an instance attribute set in `__init__()`, NOT a class
  attribute — class attributes are shared across instances.
- `auto_open` is a class attribute (opt-in per tool class), not instance.
- The `_ensure_open()` call in `execute()` should go inside the existing
  `try` block, BEFORE `self.validate_args()` (line 605) — resource
  acquisition must happen before the tool attempts to use the resource.
- If `_open()` raises, `_opened` must remain `False` so the next
  `execute()` retries.
- `_close()` should reset `_opened = False` after running cleanup.

### Insertion point in `execute()`

Insert after `_lc_t0 = time.perf_counter()` (line 598) and before
`self.logger.info("Executing tool: %s", self.name)` (line 602), inside
the existing `try:` block:

```python
        try:
            # NEW — lazy resource acquisition
            if self.auto_open:
                await self._ensure_open()

            self.logger.info("Executing tool: %s", self.name)
            # ... rest unchanged
```

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/abstract.py` — the file to modify
- `packages/ai-parrot/src/parrot/tools/toolkit.py:375-401` — `_pre_execute` / `_post_execute` pattern

---

## Acceptance Criteria

- [ ] `AbstractTool` has `auto_open: bool = False` class attribute
- [ ] `AbstractTool.__init__()` sets `self._opened = False`
- [ ] `AbstractTool._open()` exists as async no-op
- [ ] `AbstractTool._close()` exists as async no-op, resets `_opened = False`
- [ ] `AbstractTool._ensure_open()` is idempotent (calls `_open()` at most once)
- [ ] `execute()` calls `_ensure_open()` when `auto_open=True`
- [ ] `execute()` does NOT call `_ensure_open()` when `auto_open=False`
- [ ] If `_open()` raises, `_opened` stays `False` (retry on next call)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/abstract.py`
- [ ] Existing tests still pass: `pytest packages/ai-parrot/tests/tools/ -v -x --timeout=30`

---

## Test Specification

Tests are created in TASK-1994. This task only modifies the production code.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/per-tool-connection.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `AbstractTool` still has the
   same structure at `abstract.py:126`
4. **Update status** in `sdd/tasks/index/per-tool-connection.json` → `"in-progress"`
5. **Implement** the scope above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-1991-abstracttool-connection-lifecycle.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-31
**Notes**: Added `auto_open: bool = False` class attribute, `self._opened: bool = False`
instance attribute (set in `__init__`), and `_open()` / `_close()` / `_ensure_open()`
async methods to `AbstractTool` in `abstract.py`. `_ensure_open()` calls `_open()` at
most once and only sets `_opened = True` on success (retries on failure). `_close()`
resets `_opened = False` for reuse. Inserted `if self.auto_open: await
self._ensure_open()` at the top of the existing `try:` block in `execute()`, before
`self.logger.info("Executing tool: %s", ...)`.

Verified manually with a `TrackingTool` (auto_open=True) scenario: `_open()` called
exactly once across two `execute()` calls, `_close()` resets state, a `NoAutoOpen`
tool (default `auto_open=False`) never triggers `_open()`, and a `FailOpen` tool
that raises in `_open()` keeps `_opened=False` and retries on the next call.

`ruff check` on `abstract.py`: 58 pre-existing errors, unchanged before/after (no
new violations introduced). `pytest packages/ai-parrot/tests/tools/ -v`: 51
failed / 674 passed / 8 skipped — identical to the unmodified `dev` baseline
(verified by running the same suite in the main repo checkout); all 51 failures
are pre-existing and unrelated to this change (databasequery toolkit tests,
`test_auto_registration_hooks.py` — missing `validate_database_query` attribute /
registry wiring issues, not touched by this task).

**Deviations from spec**: none.
