# TASK-3402: `turn_scope` — per-turn ContextVar correlation for lifecycle events

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 3**. Live tool progress (G4) is built on lifecycle events the codebase
already emits: `AbstractTool.execute()` fires `BeforeToolCallEvent` / `AfterToolCallEvent` /
`ToolCallFailedEvent` (`tools/abstract.py:946`, `:1130`, `:1172`). Those events are emitted on
the **tool's** registry and forwarded to the **global** registry — a subscriber on
`bot.events` never sees them, and filtering by `trace_context.trace_id` is unreliable because
a tool mints `TraceContext.new_root()` whenever no `PermissionContext` carries a trace
(`tools/abstract.py:938-939`).

The correct correlation key is asyncio context: both `EventRegistry.emit_nowait` and the
global forwarder (`_forward_to_global_safely`, navigator-eventbus 0.3.0) schedule `emit`
with `loop.create_task(...)`, which copies the emitter's `contextvars.Context`. So a
`ContextVar` set around a turn (in the CLI) or a request (in the server SSE handler) is
visible to a `where=` predicate at dispatch time. This task provides that ContextVar, a
context manager and a predicate factory in core, next to the lifecycle package.

Consumers: `TurnRunner` (TASK-3404) and `StreamHandler.stream_sse` (TASK-3409).

---

## Scope

- Create `parrot/core/events/lifecycle/turn_scope.py` with `TURN_SCOPE`, `turn_scope()`
  and `in_turn_scope()` per the spec §3 Module 3 skeleton.
- Re-export the three names from `parrot/core/events/lifecycle/__init__.py` (import line +
  `__all__` entries).
- Tests proving (a) the predicate is true inside the scope and false outside, (b) it
  survives `asyncio.create_task`, and (c) a real `AbstractTool.execute()` inside
  `turn_scope("t1")` reaches a `get_global_registry()` subscriber filtered with
  `in_turn_scope("t1")`, while the same call outside the scope does not.

**NOT in scope**: mapping lifecycle events to `TurnEvent`s (TASK-3404), the server frames
(TASK-3409), any change to `AbstractTool`, `ToolManager`, `AbstractBot` or navigator-eventbus.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/turn_scope.py` | CREATE | `TURN_SCOPE`, `turn_scope()`, `in_turn_scope()` |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` | MODIFY | Import + `__all__` entries for the three names |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_turn_scope.py` | CREATE | Predicate, create_task propagation, real tool round-trip |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from navigator_eventbus.lifecycle.base import LifecycleEvent          # verified: parrot/core/events/lifecycle/__init__.py:19 (same path)
from navigator_eventbus.lifecycle.registry import EventRegistry       # verified: tests/unit/tools/test_tool_lifecycle.py:19
from parrot.core.events.lifecycle import get_global_registry, scope   # verified: parrot/core/events/lifecycle/__init__.py:22, __all__ :93-94
from parrot.core.events.lifecycle.events import (                     # verified: tests/unit/tools/test_tool_lifecycle.py:14-18
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent)
from parrot.tools.abstract import AbstractTool, ToolResult            # verified: tests/unit/tools/test_tool_lifecycle.py:22
from contextvars import ContextVar                                    # stdlib
import asyncio, contextlib                                            # stdlib
from typing import Callable, Iterator, Optional                       # stdlib
import pytest                                                         # verified: tests/unit/tools/test_tool_lifecycle.py:12
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py
from navigator_eventbus.lifecycle.trace import TraceContext                          # line 18
from navigator_eventbus.lifecycle.base import LifecycleEvent                         # line 19
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin                     # line 24  (last navigator import before the events block at :27)
__all__ = [ ..., "get_global_registry",  # line 93
            "scope",                     # line 94  (1 occurrence)
            ... ]

# navigator_eventbus 0.3.0 (installed) — EventRegistry
def subscribe(self, event_type: Type[E], callback: AsyncSubscriber, *, where: Optional[Callable[[E], bool]] = None, forward_to_bus: bool = False) -> str
def unsubscribe(self, subscription_id: str) -> bool
async def emit(self, event: LifecycleEvent) -> None          # evaluates `where(event)` for each subscription
def emit_nowait(self, event: LifecycleEvent) -> None         # loop.create_task(self.emit(event))  ← context copied
def _forward_to_global_safely(self, event) -> None           # create_task on the running loop ← context copied
# navigator_eventbus.lifecycle.global_registry
def get_global_registry() -> EventRegistry
@contextmanager def scope() -> Iterator[EventRegistry]       # yields EventRegistry(forward_to_global=False) installed as the global for the block

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):                  # line 281
    def __init__(self, name: Optional[str] = None, description: Optional[str] = None, ...)   # line 335-338
    async def execute(self, *args, **kwargs) -> ToolResult    # line 872
        # tool_tc = parent_tc.child() if pctx else TraceContext.new_root()   # lines 938-939
        # self.events.emit_nowait(BeforeToolCallEvent(trace_context=tool_tc, ...))   # lines 946-951
        # await self.events.emit(AfterToolCallEvent(...))     # lines 1130-1132
        # ToolCallFailedEvent                                  # line 1172
class ToolResult(BaseModel)                                  # line 250  (ToolResult(status="success", result="ok"))

# packages/ai-parrot/tests/unit/tools/test_tool_lifecycle.py — REUSE THIS SHAPE
class _OkTool(AbstractTool):                                 # line 29
    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", result="ok")
tool = _OkTool(name="ok-tool")                               # line 72
```

### Does NOT Exist
- ~~`parrot.core.events.lifecycle.turn_scope`~~ — created by this task.
- ~~`EventRegistry.subscribe(..., forward_to_global=...)`~~ — `docs/lifecycle_events.md` describes such a flag; the real 0.3.0 signature has only `where` and `forward_to_bus`. Forwarding is a property of the *emitting* registry.
- ~~`bot.events.subscribe(BeforeToolCallEvent, cb)` receiving tool events~~ — tool events go tool-registry → global; subscribe on `get_global_registry()`.
- ~~`ToolManager` injecting the bot's `_current_trace_context` into tools~~ — it does not; hence trace-id filtering is unreliable and this ContextVar exists.
- ~~`EventRegistry.emit` being synchronous for `emit_nowait`~~ — it is scheduled; tests must yield to the loop (`await asyncio.sleep(0)` twice) before asserting captures.
- ~~`parrot.core.events.lifecycle.LifecycleEvent` importable from inside `turn_scope.py`~~ — it IS re-exported at `__init__.py:19`, but importing it from the package `__init__` inside `turn_scope.py` would be circular once `__init__` imports `turn_scope`; import from `navigator_eventbus.lifecycle.base` instead.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/core/events/lifecycle/turn_scope.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/events/lifecycle/test_turn_scope.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool.execute",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#ToolResult",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py#BeforeToolCallEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py#AfterToolCallEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py#ToolCallFailedEvent"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# ContextVar + contextmanager: set/reset with the token, never assign None on exit
token = TURN_SCOPE.set(turn_id)
try:
    yield
finally:
    TURN_SCOPE.reset(token)
```

### Key Constraints
- The predicate reads `TURN_SCOPE.get(None)` at **dispatch** time (inside `emit`), not at
  subscription time. Do not capture the value in a closure.
- Module must import only from `navigator_eventbus.lifecycle.base` and stdlib (circular-import guard, see Does NOT Exist).
- The `__init__.py` edit adds one import line after line 24 and three `__all__` entries
  after `"scope",` — nothing else moves.
- Tests use `scope()` so the real global registry is never touched; after `await tool.execute()`
  yield to the loop (`await asyncio.sleep(0)` ×2) so the `create_task`-scheduled dispatches run.
- Inside a worktree run tests with `PYTHONPATH=packages/ai-parrot/src pytest ...`; never `uv sync` there.

### References in Codebase
- `packages/ai-parrot/tests/unit/tools/test_tool_lifecycle.py:29-46, 70-90` — fake tool + capture pattern.
- `packages/ai-parrot/tests/unit/events/lifecycle/test_global_registry.py` — `scope()` usage.
- `.venv/lib/python3.12/site-packages/navigator_eventbus/lifecycle/registry.py` — `emit_nowait`, `_forward_to_global_safely`.
- `sdd/specs/new-ui-cli-agents.spec.md` §2 Overview item 4, §3 Module 3, §7 "Tool-event correlation depends on task context".

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker.

### Steps (in order)
1. Write `turn_scope.py` — *why*: three tiny primitives; the ContextVar name is fixed so the CLI and server share one key.
2. Add the import and `__all__` entries to `__init__.py` — *why*: consumers import from `parrot.core.events.lifecycle` (spec §6 Verified Imports).
3. Write the round-trip test with a real `AbstractTool` under `scope()` — *why*: it proves the context-copy assumption the whole live-tool design rests on; if navigator-eventbus ever stops using `create_task`, this test is the alarm.

### `packages/ai-parrot/src/parrot/core/events/lifecycle/turn_scope.py` (CREATE)
```python
"""Per-turn correlation for lifecycle events via a ``ContextVar`` (FEAT-573 M3).

``EventRegistry.emit_nowait`` and the global-registry forwarder schedule dispatch with
``loop.create_task``, which copies the emitter's ``contextvars.Context``. Setting
``TURN_SCOPE`` around a turn therefore lets a ``where=`` predicate isolate exactly the
tool events that turn caused — in the CLI and in a multi-tenant server alike.
"""
from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Callable, Iterator, Optional

from navigator_eventbus.lifecycle.base import LifecycleEvent  # verified: parrot/core/events/lifecycle/__init__.py:19

TURN_SCOPE: ContextVar[Optional[str]] = ContextVar("parrot_turn_scope", default=None)


@contextlib.contextmanager
def turn_scope(turn_id: str) -> Iterator[None]:
    """Set ``TURN_SCOPE`` to ``turn_id`` for the body; always reset on exit."""
    token = TURN_SCOPE.set(turn_id)
    try:
        yield
    finally:
        TURN_SCOPE.reset(token)


def in_turn_scope(turn_id: str) -> Callable[[LifecycleEvent], bool]:
    """Predicate for ``EventRegistry.subscribe(where=...)``.

    Returns True when the *emitting* context's ``TURN_SCOPE`` equals ``turn_id``. The value
    is read at dispatch time, never captured at subscription time.
    """

    def _predicate(_event: LifecycleEvent) -> bool:
        return TURN_SCOPE.get(None) == turn_id

    return _predicate


__all__ = ["TURN_SCOPE", "turn_scope", "in_turn_scope"]
```
**Why this shape**: no logic to fill in — the whole module is the decided design. The
event argument is unused on purpose: the correlation lives in the context, not the payload.

### `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c 'from navigator_eventbus.lifecycle.mixin import EventEmitterMixin' packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py)
# AFTER — insert below `from navigator_eventbus.lifecycle.mixin import EventEmitterMixin` (verified: packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py:24)
from parrot.core.events.lifecycle.turn_scope import TURN_SCOPE, turn_scope, in_turn_scope  # FEAT-573 M3
```

### `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` (MODIFY — `__all__`)
```python
# occurrences: 1 (verified: grep -c '"scope",' packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py)
# AFTER — insert below `    "scope",` (verified: packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py:94)
    # Turn correlation (FEAT-573)
    "TURN_SCOPE",
    "turn_scope",
    "in_turn_scope",
```
**Why**: `TurnRunner` and `StreamHandler` import these from the package root, matching the
spec's Verified Imports; keeping them next to `scope`/`get_global_registry` groups the
registry-level helpers.

### `packages/ai-parrot/tests/unit/events/lifecycle/test_turn_scope.py` (CREATE)
```python
"""Tests for parrot.core.events.lifecycle.turn_scope (FEAT-573 TASK-3402)."""
from __future__ import annotations

import asyncio

import pytest  # verified: tests/unit/tools/test_tool_lifecycle.py:12

from parrot.core.events.lifecycle import TURN_SCOPE, get_global_registry, in_turn_scope, scope, turn_scope
from parrot.core.events.lifecycle.events import AfterToolCallEvent, BeforeToolCallEvent  # verified: test_tool_lifecycle.py:14
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: test_tool_lifecycle.py:22


class _OkTool(AbstractTool):
    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", result="ok")


def test_turn_scope_sets_and_resets() -> None:
    assert TURN_SCOPE.get(None) is None
    with turn_scope("t1"):
        assert TURN_SCOPE.get(None) == "t1"
        assert in_turn_scope("t1")(object()) is True   # type: ignore[arg-type]
        assert in_turn_scope("other")(object()) is False  # type: ignore[arg-type]
    assert TURN_SCOPE.get(None) is None


@pytest.mark.asyncio
async def test_turn_scope_predicate_survives_create_task() -> None:
    seen: list[bool] = []

    async def emitter() -> None:
        seen.append(in_turn_scope("t1")(object()))  # type: ignore[arg-type]

    with turn_scope("t1"):
        await asyncio.create_task(emitter())
    await asyncio.create_task(emitter())  # outside the scope
    assert seen == [True, False]


@pytest.mark.asyncio
async def test_real_tool_events_reach_scoped_global_subscriber() -> None:
    captured: list = []

    async def cb(event) -> None:
        captured.append(event)

    with scope() as reg:
        assert get_global_registry() is reg
        reg.subscribe(BeforeToolCallEvent, cb, where=in_turn_scope("t1"))
        reg.subscribe(AfterToolCallEvent, cb, where=in_turn_scope("t1"))
        tool = _OkTool(name="ok-tool")
        with turn_scope("t1"):
            await tool.execute()
        await asyncio.sleep(0); await asyncio.sleep(0)  # let create_task-scheduled dispatches run
        assert [type(e).__name__ for e in captured] == ["BeforeToolCallEvent", "AfterToolCallEvent"]
        await tool.execute()  # no scope → filtered out
        await asyncio.sleep(0); await asyncio.sleep(0)
        assert len(captured) == 2
        # FILL IN: assert both captured events share the same trace_context.span_id — bounded by
        # spec §2 "call_id is the tool event's span_id" (tools/abstract.py:948, :1132).
```
**Why**: the third test is the load-bearing one: it exercises the real
`AbstractTool.execute()` → tool registry → global forwarder path under `scope()`, exactly as
`TurnRunner` will consume it. If it ever fails, live tool progress is broken at the root.

### FILL IN checklist
- [ ] `test_turn_scope.py::test_real_tool_events_reach_scoped_global_subscriber` — span_id equality assertion; bounded by spec §2 Data Models (`call_id`).

---

## Acceptance Criteria

- [ ] `from parrot.core.events.lifecycle import TURN_SCOPE, turn_scope, in_turn_scope` works and `import parrot.core.events.lifecycle` has no circular-import error.
- [ ] `TURN_SCOPE` is reset on exit from `turn_scope()` even when the body raises.
- [ ] A `BeforeToolCallEvent`/`AfterToolCallEvent` emitted by a real `AbstractTool.execute()` inside `turn_scope("t1")` reaches a `get_global_registry()` subscriber filtered with `in_turn_scope("t1")`; the same call outside the scope does not (spec AC6 precondition).
- [ ] Existing lifecycle tests stay green: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_global_registry.py -q`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_turn_scope.py -v`
- [ ] `ruff check` and `mypy` clean on `turn_scope.py`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_turn_scope.py -q`
- `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_global_registry.py -q`
- `pytest packages/ai-parrot/tests/unit/tools/test_tool_lifecycle.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_turn_scope.py — see blueprint
def test_turn_scope_sets_and_resets(): ...
async def test_turn_scope_predicate_survives_create_task(): ...
async def test_real_tool_events_reach_scoped_global_subscriber(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3402-lifecycle-turn-scope.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-coder native `sonnet` seat (attempt c3d9302a89564e54b858bcdc444a06bf)
**Date**: 2026-09-18
**Notes**: Implemented `turn_scope.py` (`TURN_SCOPE` ContextVar, `turn_scope()`
context manager, `in_turn_scope()` predicate factory) verbatim per blueprint;
re-exported from `lifecycle/__init__.py`. Guard test covers set/reset,
survival across `asyncio.create_task`, and a real `AbstractTool.execute()`
round-trip reaching a scope-filtered global subscriber.

Merge clean (`coder_merge` outcome=merged); engine lint autofix (black)
applied. `pytest test_turn_scope.py + test_global_registry.py +
test_tool_lifecycle.py`: 22 passed (orchestrator, top-level worktree — the
sandboxed sub-worktree lacked the compiled `parrot.utils.types` extension,
same pre-existing limitation as prior tasks).

**Deviation from spec (reviewed and confirmed correct)**: the blueprint's
third test asserted a strict order
`["BeforeToolCallEvent", "AfterToolCallEvent"]` after two `asyncio.sleep(0)`
yields. The coder traced this as deterministically false against the real
navigator-eventbus 0.3.0 registry (`BeforeToolCallEvent` goes through
`emit_nowait()` — one extra `create_task` hop — while `AfterToolCallEvent`'s
directly-awaited `emit()` schedules its forward synchronously, so After can
legitimately land in the subscriber's list first). Changed the assertion to
membership/count (`sorted(...)`) and to a type-based span_id lookup instead
of fixed indices, preserving the test's actual purpose. Verified against
this task's own AC (line 335: only requires the event reaches the
scope-filtered subscriber and is excluded outside scope — no ordering
requirement) — the original blueprint assertion was itself incorrect about
an async-scheduling guarantee the library does not provide. Orchestrator
CONFIRMED this correction; no fix commit needed since it landed in the
delivery commit itself.

**Feedback recorded**: none — the historical TASK-3374 pattern
(unscoped-removal-reuses-full-uninstall-helper) supplied via `coder_feedback`
was correctly judged not applicable (this task creates net-new primitives,
wraps nothing).
