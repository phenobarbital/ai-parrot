---
type: Wiki Overview
title: 'TASK-1195: Integrate EventEmitterMixin into AbstractTool + trace propagation'
id: doc:sdd-tasks-completed-task-1195-abstracttool-lifecycle-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 14 of the spec. `AbstractTool.execute()` already strips `_permission_context`
  (line 391) and stashes it on `self._current_pctx` (line 421). This task wraps `execute()`
  so it emits `BeforeToolCallEvent` / `AfterToolCallEvent` / `ToolCallFailedEvent`
  around the concrete `_ex
relates_to:
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.mixin
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1195: Integrate EventEmitterMixin into AbstractTool + trace propagation

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-1184, TASK-1189, TASK-1185
**Assigned-to**: unassigned
**Parallel**: yes (touches only `parrot/tools/abstract.py` — no overlap with TASK-1193 or TASK-1194)

---

## Context

Module 14 of the spec. `AbstractTool.execute()` already strips `_permission_context` (line 391) and stashes it on `self._current_pctx` (line 421). This task wraps `execute()` so it emits `BeforeToolCallEvent` / `AfterToolCallEvent` / `ToolCallFailedEvent` around the concrete `_execute()` call, while also pulling `trace_context` from `self._current_pctx` to mint a child span for the tool. This delivers the A2A trace propagation guarantee (agent A → tool wrapper → agent B inside the tool all share the same trace_id).

Spec section: §3 Module 14, §7 Risks (A2A trace context propagation).

---

## Scope

- Add `EventEmitterMixin` to `AbstractTool` base.
- Call `_init_events()` in `__init__`.
- Modify the existing `execute()` method to:
  - Read `parent_trace = self._current_pctx.trace_context if self._current_pctx else None`.
  - Mint a child trace (`parent_trace.child()`) or a root trace (if no parent).
  - Emit `BeforeToolCallEvent` with `args_summary` (truncated, see Notes).
  - Time the call.
  - Try/except around the concrete `_execute(*args, **kwargs)`:
    - Success → emit `AfterToolCallEvent` with `result_status`, `result_size_bytes`.
    - Exception → emit `ToolCallFailedEvent` with `error_type`/`error_message`, then re-raise.
  - When the tool wraps a sub-agent (A2A pattern), the tool sets `_current_pctx.trace_context = <child trace>` BEFORE calling `_execute` so the sub-agent's `PermissionContext` carries the right parent.
- Implement `_args_summary(kwargs)` — truncate strings >200 chars, drop binary-ish values (bytes, file handles).
- Add unit tests covering: success path, failure path (no After), trace child wiring, args truncation.
- Add integration test `test_a2a_trace_context_propagation` (per spec §4 Integration Tests) — AgentA invokes AgentB as a tool; verify trace_id matches and parent_span_id is the agent A's BeforeToolCallEvent.span_id.

**NOT in scope**: `AbstractToolkit._pre_execute` / `_post_execute` (spec §1 Non-Goals: those remain untouched).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | Mixin + emission wrapper around `execute()`. |
| `packages/ai-parrot/tests/unit/tools/test_tool_lifecycle.py` | CREATE | Before/After/Failed + args truncation tests. |
| `packages/ai-parrot/tests/integration/events/test_a2a_trace_propagation.py` | CREATE | Agent A → Agent B-as-tool trace continuity test. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# In packages/ai-parrot/src/parrot/tools/abstract.py
import time
from typing import Any

from parrot.core.events.lifecycle.mixin import EventEmitterMixin               # TASK-1189
from parrot.core.events.lifecycle.trace import TraceContext                    # TASK-1182
from parrot.core.events.lifecycle.events import (                              # TASK-1184
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/abstract.py — VERIFIED
class AbstractTool(ABC):                                  # line 71
    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        output_dir: Optional[Union[str, Path]] = None,
        base_url: Optional[str] = None,
        static_dir: Optional[Union[str, Path]] = None,
        routing_meta: Optional[Dict] = None,
        **kwargs,
    ): ...                                                # line 91

    async def execute(self, *args, **kwargs) -> ToolResult:                  # line 375
        # line 391:  pctx = kwargs.pop('_permission_context', None)
        # line 392:  resolver = kwargs.pop('_resolver', None)
        # line 421:  self._current_pctx = pctx
        # then calls self._execute(*args, **kwargs)
        ...

    @abstractmethod
    async def _execute(self, *args, **kwargs) -> ToolResult: ...
```

```python
# packages/ai-parrot/src/parrot/auth/permission.py — after TASK-1185
@dataclass
class PermissionContext:
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None
    trace_context: Optional[TraceContext] = None
    extra: dict[str, Any] = field(default_factory=dict)
```

### Does NOT Exist

- ~~`AbstractTool.events` before this task~~ — being added.
- ~~A separate `_execute_with_context` API~~ — the existing `execute()` already serves as the wrapper; we extend it in-place.

---

## Implementation Notes

### Wrapping the existing `execute()`

The existing `execute()` at line 375 already does:
1. Pop `_permission_context`, `_resolver` from kwargs (lines 391–392).
2. Store on `self._current_pctx`, `self._current_resolver` (~ line 421).
3. Call `self._execute(*args, **kwargs)`.
4. Return result.

We extend it with emission and trace mint:

```python
async def execute(self, *args, **kwargs) -> ToolResult:
    pctx = kwargs.pop('_permission_context', None)
    resolver = kwargs.pop('_resolver', None)
    self._current_pctx = pctx
    self._current_resolver = resolver

    # ─── lifecycle: derive trace context ───
    parent_tc = pctx.trace_context if pctx else None
    tool_tc = parent_tc.child() if parent_tc else TraceContext.new_root()
    if pctx is not None:
        # Replace pctx.trace_context with the child so sub-agents see it as parent.
        # PermissionContext is frozen-ish (dataclass without frozen=True); just assign.
        pctx.trace_context = tool_tc

    args_summary = self._args_summary(kwargs)
    self.events.emit_nowait(BeforeToolCallEvent(
        trace_context=tool_tc,
        tool_name=self.name or type(self).__name__,
        tool_class=type(self).__name__,
        args_summary=args_summary,
        source_type="tool", source_name=self.name or type(self).__name__,
    ))

    t0 = time.perf_counter()
    try:
        result = await self._execute(*args, **kwargs)
    except Exception as exc:
        dur = (time.perf_counter() - t0) * 1000
        await self.events.emit(ToolCallFailedEvent(
            trace_context=tool_tc,
            tool_name=self.name or type(self).__name__,
            duration_ms=dur,
            error_type=type(exc).__name__,
            error_message=str(exc),
            source_type="tool", source_name=self.name or type(self).__name__,
        ))
        raise

    dur = (time.perf_counter() - t0) * 1000
    # result_size_bytes: serialize result.value (or .data, depending on ToolResult shape)
    result_bytes = self._result_size(result)
    await self.events.emit(AfterToolCallEvent(
        trace_context=tool_tc,
        tool_name=self.name or type(self).__name__,
        duration_ms=dur,
        result_status="success" if getattr(result, "ok", True) else "partial",
        result_size_bytes=result_bytes,
        source_type="tool", source_name=self.name or type(self).__name__,
    ))
    return result
```

The implementer should match the actual surrounding logic at line 391–423 (toolkit binding, OAuth resolver, etc.) — the snippet above is conceptual. Read the file carefully.

### `_args_summary` — bounded, JSON-safe

```python
def _args_summary(self, kwargs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in kwargs.items():
        if k.startswith("_"):     # skip private kwargs (already popped, but defensive)
            continue
        if isinstance(v, str):
            out[k] = v[:200] + "…" if len(v) > 200 else v
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, dict, tuple)):
            out[k] = f"<{type(v).__name__} len={len(v)}>"
        else:
            out[k] = f"<{type(v).__name__}>"
    return out
```

### `_result_size`

```python
def _result_size(self, result) -> int:
    try:
        if hasattr(result, "value"):
            return len(str(result.value).encode("utf-8"))
        if hasattr(result, "content"):
            return len(str(result.content).encode("utf-8"))
        return len(str(result).encode("utf-8"))
    except Exception:
        return 0
```

### A2A trace propagation

When AgentA invokes AgentB as a tool:
- AgentA's `ask()` sets `pctx.trace_context = <agent A's child trace>` (TASK-1193).
- The tool wrapping AgentB receives this `pctx`, mints `tool_tc = pctx.trace_context.child()`, and re-assigns `pctx.trace_context = tool_tc`.
- AgentB's `ask()` (when invoked inside the tool) reads `pctx.trace_context` and uses it as the parent for its own `BeforeInvokeEvent`.
- Result: agent A → tool → agent B form a connected span chain with one `trace_id`.

The integration test `test_a2a_trace_context_propagation` verifies this end-to-end.

### Key Constraints

- `PermissionContext` is a plain `@dataclass` (not `frozen=True`), so direct assignment is fine.
- `BeforeToolCallEvent` is emitted sync (via `emit_nowait`) because we're inside an already-async method but want low overhead before the timed call. `AfterToolCallEvent` / `ToolCallFailedEvent` use `await self.events.emit(...)` so they complete before the method returns.
- `args_summary` must be JSON-serializable (the registry's `to_dict()` will run `json.dumps` if dual-emit is on).

---

## Acceptance Criteria

- [ ] `AbstractTool` exposes `self.events: EventRegistry`.
- [ ] `execute()` emits `BeforeToolCallEvent` before `_execute`.
- [ ] On success: emits `AfterToolCallEvent`, no Failed.
- [ ] On exception: emits `ToolCallFailedEvent`, no After, exception re-raised.
- [ ] `BeforeToolCallEvent.trace_context.parent_span_id` equals the parent's `span_id` when a `_permission_context` carrying a `trace_context` is passed.
- [ ] `pctx.trace_context` is updated to the tool's new trace before `_execute` runs (so sub-agents see it as parent).
- [ ] `args_summary` truncates strings >200 chars and omits binary-ish values.
- [ ] Existing tool tests continue to pass.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/unit/tools/test_tool_lifecycle.py -v`.
- [ ] Integration test passes: `pytest packages/ai-parrot/tests/integration/events/test_a2a_trace_propagation.py -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/tools/test_tool_lifecycle.py
import pytest

from parrot.core.events.lifecycle.global_registry import scope
from parrot.core.events.lifecycle.events import (
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
)
from parrot.core.events.lifecycle.trace import TraceContext
from parrot.auth.permission import PermissionContext


class _OkTool:   # minimal AbstractTool subclass
    async def _execute(self, **kw):
        return type("R", (), {"value": "ok"})()


class _FailTool:
    async def _execute(self, **kw):
        raise ValueError("nope")


class TestToolLifecycle:
    @pytest.mark.asyncio
    async def test_success_emits_before_and_after(self):
        captured = []
        async def cap(e): captured.append(e)
        with scope() as reg:
            reg.subscribe(BeforeToolCallEvent, cap)
            reg.subscribe(AfterToolCallEvent, cap)
            tool = _OkTool(name="t")
            await tool.execute(x="hi")
        classes = [type(e).__name__ for e in captured]
        assert classes == ["BeforeToolCallEvent", "AfterToolCallEvent"]

    @pytest.mark.asyncio
    async def test_failure_emits_failed_not_after(self):
        captured = []
        async def cap(e): captured.append(e)
        with scope() as reg:
            reg.subscribe(BeforeToolCallEvent, cap)
            reg.subscribe(AfterToolCallEvent, cap)
            reg.subscribe(ToolCallFailedEvent, cap)
            tool = _FailTool(name="t")
            with pytest.raises(ValueError):
                await tool.execute()
        classes = [type(e).__name__ for e in captured]
        assert "BeforeToolCallEvent" in classes and "ToolCallFailedEvent" in classes
        assert "AfterToolCallEvent" not in classes

    @pytest.mark.asyncio
    async def test_trace_child_wiring(self):
        parent = TraceContext.new_root()
        # Construct a minimal PermissionContext (use mock or fixture from existing tests).
        from unittest.mock import MagicMock
        pctx = PermissionContext(session=MagicMock(), trace_context=parent)
        captured = []
        async def cap(e): captured.append(e)
        with scope() as reg:
            reg.subscribe(BeforeToolCallEvent, cap)
            tool = _OkTool(name="t")
            await tool.execute(_permission_context=pctx)
        evt = captured[0]
        assert evt.trace_context.trace_id == parent.trace_id
        assert evt.trace_context.parent_span_id == parent.span_id
        # pctx.trace_context updated to the tool's new trace
        assert pctx.trace_context.parent_span_id == parent.span_id
```

---

## Agent Instructions

1. Read spec §3 Module 14 and §7 A2A trace propagation risk.
2. Confirm TASK-1184, TASK-1185, TASK-1189 are in `sdd/tasks/completed/`.
3. Read `parrot/tools/abstract.py` around lines 375–425 to understand the current `execute()` flow.
4. Implement the wrapper carefully — do NOT break OAuth resolution or toolkit `_pre_execute` / `_post_execute` chains.
5. Add the A2A integration test — for this you need an Agent that wraps another agent as a tool. Use existing patterns in `parrot/bots/orchestration/` or a minimal mock.
6. Run the full tools test suite for regressions.
7. Update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-15
**Notes**:
- EventEmitterMixin added to AbstractTool MRO
- _init_events() called at end of AbstractTool.__init__
- _args_summary(kwargs): truncates strings >200 chars, skips _-prefixed keys, replaces complex types with descriptors
- _result_size(result): tries .value, .content, .result attrs then falls back to str()
- execute() modified: derives tool_tc from pctx.trace_context (or new root), emits BeforeToolCallEvent (sync emit_nowait), sets pctx.trace_context=tool_tc for A2A propagation, times the call, emits AfterToolCallEvent on success, emits ToolCallFailedEvent in exception handler before returning ToolResult(status='error')
- AuthorizationRequired still re-raises (no lifecycle event emitted for it — preserves FEAT-107 behavior)
- 11 unit tests and 3 A2A integration tests all pass
- Existing toolkit hook and auth-required tests (20) unchanged and passing

**Deviations from spec**: ToolCallFailedEvent is emitted but exception is NOT re-raised (AbstractTool.execute() converts all non-AuthorizationRequired exceptions to ToolResult(status='error') — this is pre-existing design intent). Tests adapted accordingly.
