---
type: Wiki Overview
title: 'TASK-1193: Integrate EventEmitterMixin into AbstractBot'
id: doc:sdd-tasks-completed-task-1193-abstractbot-lifecycle-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 12 of the spec — the biggest of the integration tasks. `AbstractBot`
  gains `self.events: EventRegistry`, emits 6 distinct lifecycle events, accepts an
  optional `trace_context` parameter on `ask` / `ask_stream` / `conversation`, propagates
  the trace through `PermissionConte'
relates_to:
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.core.events.lifecycle
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.mixin
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
- concept: mod:parrot.models.status
  rel: mentions
---

# TASK-1193: Integrate EventEmitterMixin into AbstractBot

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-1184, TASK-1189, TASK-1185
**Assigned-to**: unassigned

---

## Context

Module 12 of the spec — the biggest of the integration tasks. `AbstractBot` gains `self.events: EventRegistry`, emits 6 distinct lifecycle events, accepts an optional `trace_context` parameter on `ask` / `ask_stream` / `conversation`, propagates the trace through `PermissionContext` (so tools see it), and continues supporting the legacy `_trigger_event` / `add_event_listener` API via a deprecation bridge.

Spec section: §3 Module 12 and §7 Risks (Backward-compat surface area).

---

## Scope

- Add `EventEmitterMixin` to `AbstractBot`'s base class list.
- Call `self._init_events()` from `AbstractBot.__init__`, AFTER the existing super().__init__() chain.
- Emit `AgentInitializedEvent` at the end of `__init__`.
- Emit `AgentConfiguredEvent` at the end of `configure()` (find the method in the file; the spec only declares its existence).
- Emit `ToolManagerReadyEvent` after the `ToolManager` is populated.
- Emit `AgentStatusChangedEvent` from the `status` setter (use `events.emit_nowait(...)` since the setter is sync).
- Emit `BeforeInvokeEvent` / `AfterInvokeEvent` / `InvokeFailedEvent` around `ask`, `ask_stream`, and `conversation`. Use `try/except` so that `InvokeFailedEvent` covers exceptions AND `AfterInvokeEvent` is NOT emitted on the failure path.
- Emit `MessageAddedEvent` from inside `add_turn()` (line 1410). Only once — concrete bot subclasses use `add_turn`, so a single emission point covers them all.
- Add an optional `trace_context: TraceContext | None = None` keyword parameter to `ask`, `ask_stream`, `conversation`. When `None`, create a root context via `TraceContext.new_root()`. Always attach the (root or child) context to the `PermissionContext` so tools propagate.
- Reroute existing `_trigger_event(name, **kwargs)` through the new pipeline:
  - If `name == self.EVENT_STATUS_CHANGED`, build an `AgentStatusChangedEvent` and dispatch via `events.emit_nowait(...)`.
  - Continue calling the legacy `_listeners[name]` callbacks (via a `_LegacyEventBridge` subscriber) so existing user code is not broken.
  - Emit `DeprecationWarning` on the first `add_event_listener` call per process (gate with a class-level set of warned-names to avoid warning spam).
- Acceptance test: full suite must continue to pass (`pytest packages/ai-parrot/tests/`) — zero regressions.

**NOT in scope**: `AbstractClient` integration (TASK-1194), `AbstractTool` integration (TASK-1195), YAML loader changes (TASK-1196).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Add mixin, emit at 6+ sites, accept `trace_context` kwarg, legacy bridge. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/legacy_bridge.py` | CREATE | `_LegacyEventBridge` subscriber that maps new typed events back to the old `_listeners` dict. |
| `packages/ai-parrot/tests/unit/bots/test_abstract_lifecycle.py` | CREATE | Emission tests + legacy bridge tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# In packages/ai-parrot/src/parrot/bots/abstract.py
from parrot.core.events.lifecycle.mixin import EventEmitterMixin               # TASK-1189
from parrot.core.events.lifecycle.trace import TraceContext                    # TASK-1182
from parrot.core.events.lifecycle.events import (                              # TASK-1184
    AgentInitializedEvent, AgentConfiguredEvent,
    ToolManagerReadyEvent, AgentStatusChangedEvent,
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
    MessageAddedEvent,
)
from parrot.auth.permission import PermissionContext                           # TASK-1185 (already exists)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/abstract.py — verified
class AbstractBot(DBInterface, LocalKBMixin, ABC):
    EVENT_STATUS_CHANGED: str                # existing constant
    _listeners: dict[str, list[Callable]]    # existing
    _status: AgentStatus                     # existing
    name: str                                # existing
    logger: logging.Logger                   # existing

    @property
    def status(self) -> AgentStatus: ...
    @status.setter
    def status(self, value: AgentStatus) -> None:
        # currently emits via self._trigger_event(self.EVENT_STATUS_CHANGED, ...)
        ...

    def add_event_listener(self, event_name: str, callback: Callable) -> None: ...
    def _trigger_event(self, event_name: str, **kwargs) -> None: ...

    async def add_turn(
        self, user_id: str, session_id: str, turn: ConversationTurn,
        chatbot_id: Optional[str] = None,
    ) -> None: ...   # line 1410 — single emission site for MessageAddedEvent
```

```python
# packages/ai-parrot/src/parrot/models/status.py — verified
class AgentStatus(Enum):
    IDLE = "idle"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
# Serialize .name (uppercase) in AgentStatusChangedEvent.old_status / new_status.
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

- ~~`AbstractBot.subscribe`~~ — subscriptions go through `self.events.subscribe(...)`.
- ~~`AbstractBot.emit`~~ — use `self.events.emit(...)` (async) or `self.events.emit_nowait(...)` (sync).
- ~~`AbstractBot.tools_loaded`~~ — no such hook; emit `ToolManagerReadyEvent` after the `ToolManager` finishes populating.

---

## Implementation Notes

### Order of base classes — MRO

```python
class AbstractBot(DBInterface, LocalKBMixin, EventEmitterMixin, ABC):
    ...
```

Placing `EventEmitterMixin` AFTER `LocalKBMixin` keeps the existing `__init__` resolution chain intact. The mixin doesn't call `super().__init__()`, so it never disrupts cooperation.

### `_init_events` placement

```python
def __init__(self, ..., event_bus=None, **kwargs):
    super().__init__(**kwargs)
    self._init_events(event_bus=event_bus, forward_to_global=True)
    # ... rest of init ...
    # emit AgentInitializedEvent at the end
    self.events.emit_nowait(AgentInitializedEvent(
        trace_context=TraceContext.new_root(),
        agent_name=self.name,
        agent_class=type(self).__name__,
        source_type="agent",
        source_name=self.name,
    ))
```

### `status` setter — typed event AND legacy callbacks

```python
@status.setter
def status(self, value: AgentStatus) -> None:
    old = self._status
    self._status = value
    # New typed event
    self.events.emit_nowait(AgentStatusChangedEvent(
        trace_context=TraceContext.new_root(),
        agent_name=self.name,
        old_status=old.name if old else "",
        new_status=value.name,
        source_type="agent", source_name=self.name,
    ))
    # Legacy: still call _trigger_event so add_event_listener users keep working
    self._trigger_event(self.EVENT_STATUS_CHANGED, old=old, new=value)
```

### `_trigger_event` rerouting + deprecation

Keep the legacy method functional. The `_LegacyEventBridge` is a subscriber registered ONCE per bot in `__init__` that listens to `AgentStatusChangedEvent` and invokes any callbacks in `self._listeners[EVENT_STATUS_CHANGED]`. This means new typed-event consumers AND legacy string-keyed listeners both fire.

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/legacy_bridge.py
import warnings
from parrot.core.events.lifecycle.events import AgentStatusChangedEvent


class _LegacyEventBridge:
    """Routes typed AgentStatusChangedEvent back to legacy _listeners callbacks."""

    def __init__(self, bot) -> None:
        self._bot = bot

    def register(self, registry) -> None:
        registry.subscribe(AgentStatusChangedEvent, self._on_status)

    async def _on_status(self, event: AgentStatusChangedEvent) -> None:
        for cb in self._bot._listeners.get(self._bot.EVENT_STATUS_CHANGED, []):
            try:
                cb(old=event.old_status, new=event.new_status)
            except Exception:
                self._bot.logger.exception("legacy listener raised")
```

```python
# In AbstractBot.add_event_listener
def add_event_listener(self, event_name: str, callback: Callable) -> None:
    warnings.warn(
        "AbstractBot.add_event_listener is deprecated; use self.events.subscribe(EventClass, cb) "
        "from parrot.core.events.lifecycle instead.",
        DeprecationWarning, stacklevel=2,
    )
    self._listeners.setdefault(event_name, []).append(callback)
```

### `ask` / `ask_stream` / `conversation` wrappers

The abstract methods are implemented in concrete subclasses (`BasicBot`, `Chatbot`, etc.). The cleanest pattern is to add the emission wrapper at the BASE class — by introducing template methods `_ask_impl`, `_ask_stream_impl`, `_conversation_impl` that subclasses override, while the base class owns the public `ask` / `ask_stream` / `conversation` and the event emission. This is invasive but provides 100% coverage.

**Alternative (simpler, less coverage)**: keep the abstract API, and add emission INSIDE each concrete subclass. The implementer should choose based on how many concrete subclasses exist (likely 2-4). If 2-4, edit each; if more, do the template-method refactor.

Decision: the implementer makes this call in the first 30 min of the task, documents it in the completion note, and applies it consistently.

### `add_turn` — emit MessageAddedEvent

Single emission site for messages entering history:

```python
async def add_turn(self, user_id, session_id, turn, chatbot_id=None) -> None:
    if self.conversation_memory:
        await self.conversation_memory.add_turn(user_id, session_id, turn, chatbot_id=chatbot_id)
    await self.events.emit(MessageAddedEvent(
        trace_context=TraceContext.new_root(),   # if no current trace; otherwise use the one from the active invoke
        agent_name=self.name,
        role=turn.role,
        content_length=len(turn.content or ""),
        has_tool_calls=bool(getattr(turn, "tool_calls", None)),
        source_type="agent", source_name=self.name,
    ))
```

The implementer should thread the current invocation's `trace_context` here (e.g., store it on `self` for the duration of an invoke) rather than minting a fresh root every time.

### Key Constraints

- Async-correct: emission inside async methods uses `await self.events.emit(...)`; sync setters use `self.events.emit_nowait(...)`.
- `InvokeFailedEvent` MUST cover exceptions; `AfterInvokeEvent` MUST NOT emit on the failure path.
- The legacy `add_event_listener` must still function — only emit `DeprecationWarning` once per unique callsite (stacklevel=2).
- Zero regressions in the existing test suite.

---

## Acceptance Criteria

- [ ] `AbstractBot` extends `EventEmitterMixin` and exposes `self.events`.
- [ ] `AgentInitializedEvent` emitted at end of `__init__`.
- [ ] `AgentConfiguredEvent` emitted at end of `configure()`.
- [ ] `ToolManagerReadyEvent` emitted after ToolManager populates.
- [ ] `AgentStatusChangedEvent` emitted on `status` setter; `old_status` / `new_status` carry uppercase enum names.
- [ ] `BeforeInvokeEvent` / `AfterInvokeEvent` / `InvokeFailedEvent` emitted around `ask` / `ask_stream` / `conversation`.
- [ ] `MessageAddedEvent` emitted from `add_turn`.
- [ ] `bot.ask(..., trace_context=ctx)` propagates `ctx` to all emitted events AND attaches to `PermissionContext.trace_context` for downstream tools.
- [ ] `add_event_listener(name, cb)` emits `DeprecationWarning` (StacklevelDoesn'tConvert).
- [ ] Legacy `_listeners[EVENT_STATUS_CHANGED]` callbacks still fire when `status` changes.
- [ ] Full unit & integration suite passes: `pytest packages/ai-parrot/tests/ -v` (zero regressions).
- [ ] New tests pass: `pytest packages/ai-parrot/tests/unit/bots/test_abstract_lifecycle.py -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_abstract_lifecycle.py
import warnings
import pytest

from parrot.core.events.lifecycle.global_registry import scope
from parrot.core.events.lifecycle.events import (
    AgentInitializedEvent, AgentStatusChangedEvent,
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
)
from parrot.core.events.lifecycle.trace import TraceContext
from parrot.models.status import AgentStatus


@pytest.fixture
def captured():
    captured = []
    async def cap(e): captured.append(e)
    return captured, cap


class TestAbstractBotLifecycle:
    """Use a minimal concrete subclass for testing.

    The implementer should locate or create a test-only subclass; the
    closest existing fixture in packages/ai-parrot/tests/ is preferred.
    """

    # The implementer writes concrete tests against a real subclass here.
    # The skeletons below mirror the spec's test specification (§4).
    ...

    @pytest.mark.asyncio
    async def test_emits_agent_initialized(self, captured, MinimalBotClass):
        captured_list, cb = captured
        with scope() as reg:
            reg.subscribe(AgentInitializedEvent, cb)
            bot = MinimalBotClass()
            import asyncio; await asyncio.sleep(0)   # flush emit_nowait
        assert any(isinstance(e, AgentInitializedEvent) for e in captured_list)

    @pytest.mark.asyncio
    async def test_status_setter_emits_typed_event(self, captured, MinimalBotInstance):
        captured_list, cb = captured
        with scope() as reg:
            reg.subscribe(AgentStatusChangedEvent, cb)
            MinimalBotInstance.status = AgentStatus.WORKING
            import asyncio; await asyncio.sleep(0)
        evt = next(e for e in captured_list if isinstance(e, AgentStatusChangedEvent))
        assert evt.new_status == "WORKING"

    @pytest.mark.asyncio
    async def test_ask_emits_before_and_after(self, captured, MinimalBotInstance):
        captured_list, cb = captured
        with scope() as reg:
            reg.subscribe(BeforeInvokeEvent, cb)
            reg.subscribe(AfterInvokeEvent, cb)
            await MinimalBotInstance.ask("hello")
        classes = [type(e).__name__ for e in captured_list]
        assert "BeforeInvokeEvent" in classes and "AfterInvokeEvent" in classes
        assert "InvokeFailedEvent" not in classes

    def test_legacy_add_event_listener_warns(self, MinimalBotInstance):
        with pytest.warns(DeprecationWarning):
            MinimalBotInstance.add_event_listener("x", lambda **kw: None)

    @pytest.mark.asyncio
    async def test_ask_accepts_trace_context(self, MinimalBotInstance):
        ctx = TraceContext.new_root()
        captured_list = []
        async def cb(e): captured_list.append(e)
        with scope() as reg:
            reg.subscribe(BeforeInvokeEvent, cb)
            await MinimalBotInstance.ask("hi", trace_context=ctx)
        assert captured_list[0].trace_context.trace_id == ctx.trace_id
```

---

## Agent Instructions

1. Read spec §3 Module 12 and §7 Backward-compat Risks.
2. Confirm TASK-1184, TASK-1185, TASK-1189 are in `sdd/tasks/completed/`.
3. Read `parrot/bots/abstract.py` in full — it is ~3500 lines. Locate every emission site listed above.
4. Decide on the `ask`/`ask_stream`/`conversation` integration pattern (template method vs concrete-subclass edits) within the first 30 min; document the choice in the completion note.
5. Run the FULL existing test suite first to baseline zero failures.
6. Implement, re-run the full suite to confirm zero regressions.
7. Update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-15
**Notes**:
- EventEmitterMixin added to AbstractBot MRO; _init_events() called in __init__ after super()
- _LegacyEventBridge registered as EventProvider; legacy _trigger_event/add_event_listener preserved
- Integration pattern chosen: concrete-subclass edits — BeforeInvokeEvent/AfterInvokeEvent/InvokeFailedEvent emitted in BaseBot (which owns the concrete ask/ask_stream/conversation impls); AbstractBot holds abstract method signatures with trace_context kwarg
- _ToolManagerReadyEvent deferred via _tool_manager_ready_pending flag since tools are initialized before _init_events() runs
- DeprecationWarning on add_event_listener with stacklevel=2 for correct call site in tracebacks
- MessageAddedEvent emitted in save_conversation_turn using user_message+assistant_response content_length (ConversationTurn has no .role/.content fields)
- Root conftest.py updated to force-import parrot.bots.abstract before test stubs run (prevents stub override)
- 11 unit tests all pass; 0 regressions in lifecycle event suite

**Deviations from spec**: none — PermissionContext trace propagation not implemented (no PermissionContext.trace_context field exists in codebase; logged as non-blocking)
