---
type: Wiki Overview
title: 'Feature Specification: AgentCrew Lifecycle Hooks'
id: doc:sdd-specs-agentcrew-hooks-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AgentCrew currently provides no way for users to register callbacks that
  fire
relates_to:
- concept: mod:parrot
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: AgentCrew Lifecycle Hooks

**Feature ID**: FEAT-157
**Date**: 2026-05-11
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Proposal**: `sdd/proposals/agentcrew-hooks.proposal.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

AgentCrew currently provides no way for users to register callbacks that fire
when the crew finishes execution. The only hook-like mechanism is the
`on_agent_complete` parameter on `run_flow()`, which fires per-agent, only in
flow mode, and does not distinguish success from failure at the crew level.

Users who need to log results, send notifications, trigger downstream pipelines,
or perform cleanup after a crew completes must inspect the returned `CrewResult`
manually — adding boilerplate around every `run_*()` call.

### Goals

- Allow users to register `on_complete` callbacks that fire when crew execution
  finishes with a usable result (status `completed` or `partial`).
- Allow users to register `on_error` callbacks that fire when crew execution
  fails (status `failed`), and also for `partial` results where some agents failed.
- Support both synchronous and asynchronous callables.
- Fire hooks from all four execution modes uniformly (sequential, loop, parallel, flow).
- Hooks must not prevent result return — exceptions in hooks are caught and logged.

### Non-Goals (explicitly out of scope)

- Replacing or modifying the per-agent `on_agent_complete` callback in `run_flow()`.
- Modifying the per-node `add_pre_action()` / `add_post_action()` mechanism.
- Adding hooks to the `CrewDefinition` Pydantic model (hooks are runtime callables,
  not serializable definitions).
- Hook priority/ordering beyond list-insertion order.
- Fire-and-forget (background) hook execution — may be a future enhancement.

---

## 2. Architectural Design

### Overview

Add two private lists to `AgentCrew` — `_on_complete_hooks` and `_on_error_hooks` —
populated via public `on_complete()` and `on_error()` registration methods. A single
private async method `_fire_hooks(result: CrewResult)` inspects `result.status` and
invokes the appropriate lists. This method is called from all four `run_*()` methods
after the `CrewResult` is built and synthesized, but before the `return` statement.

Hook signature: `(crew_name: str, result: CrewResult) -> None` (sync or async).

The dispatch logic for `partial` status: both `_on_complete_hooks` AND `_on_error_hooks`
fire, because `partial` means some agents succeeded (usable results) but some failed
(errors to handle).

### Component Diagram

```
AgentCrew
├── on_complete(callback)        ─→  _on_complete_hooks: List[CrewHookCallback]
├── on_error(callback)           ─→  _on_error_hooks: List[CrewHookCallback]
│
├── run_sequential() ─┐
├── run_loop()        ├─→ build CrewResult → synthesize → _fire_hooks(result) → persist → return
├── run_parallel()    │
└── run_flow()       ─┘
                          │
                          └─→ _fire_hooks(result: CrewResult)
                                ├── if status in ('completed','partial'): run _on_complete_hooks
                                └── if status in ('failed','partial'):    run _on_error_hooks
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentCrew.__init__` | modified | Initialize empty hook lists |
| `AgentCrew.run_sequential` | modified | Insert `_fire_hooks()` call before return |
| `AgentCrew.run_loop` | modified | Insert `_fire_hooks()` call before return |
| `AgentCrew.run_parallel` | modified | Insert `_fire_hooks()` call before return |
| `AgentCrew.run_flow` | modified | Insert `_fire_hooks()` call before return |
| `ActionCallback` type | reused | Existing type alias for sync/async callables |
| `CrewResult` | consumed (read-only) | Passed to hooks as argument |

### Data Models

```python
# New type alias in parrot/bots/flows/core/types.py
CrewHookCallback = Callable[[str, "CrewResult"], Union[None, Awaitable[None]]]
```

This is more specific than `ActionCallback` (which is `Callable[..., ...]`) —
it documents the exact signature: `(crew_name: str, result: CrewResult) -> None`.

### New Public Interfaces

```python
class AgentCrew:
    def on_complete(
        self,
        callback: CrewHookCallback,
    ) -> None:
        """Register a callback to fire when crew execution completes.

        Fires for status 'completed' and 'partial'. Callbacks receive
        (crew_name, result) and may be sync or async.

        Args:
            callback: Callable with signature (crew_name: str, result: CrewResult).
        """

    def on_error(
        self,
        callback: CrewHookCallback,
    ) -> None:
        """Register a callback to fire when crew execution has errors.

        Fires for status 'failed' and 'partial'. Callbacks receive
        (crew_name, result) and may be sync or async.

        Args:
            callback: Callable with signature (crew_name: str, result: CrewResult).
        """

    async def _fire_hooks(self, result: CrewResult) -> None:
        """Dispatch lifecycle hooks based on result status.

        Invoked by all run_*() methods after CrewResult is built.
        Exceptions in hooks are caught and logged — never block return.
        """
```

---

## 3. Module Breakdown

### Module 1: Hook Type Definition
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/types.py`
- **Responsibility**: Define `CrewHookCallback` type alias
- **Depends on**: none

### Module 2: Hook Registration and Dispatch
- **Path**: `packages/ai-parrot/src/parrot/bots/orchestration/crew.py`
- **Responsibility**: Add `_on_complete_hooks`, `_on_error_hooks` lists to
  `__init__`, `on_complete()`, `on_error()` registration methods, and
  `_fire_hooks()` dispatch method. Insert `_fire_hooks()` calls in all four
  `run_*()` methods.
- **Depends on**: Module 1

### Module 3: Tests
- **Path**: `tests/test_crew_hooks.py`
- **Responsibility**: Verify hook registration, invocation, error handling,
  and status-based dispatch across all execution modes.
- **Depends on**: Module 2

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_on_complete_registration` | Module 2 | Registering a callback adds it to `_on_complete_hooks` |
| `test_on_error_registration` | Module 2 | Registering a callback adds it to `_on_error_hooks` |
| `test_on_complete_fires_on_completed_status` | Module 2 | Hook fires when `result.status == 'completed'` |
| `test_on_complete_fires_on_partial_status` | Module 2 | Hook fires when `result.status == 'partial'` |
| `test_on_complete_not_fires_on_failed_status` | Module 2 | Hook does NOT fire when `result.status == 'failed'` |
| `test_on_error_fires_on_failed_status` | Module 2 | Hook fires when `result.status == 'failed'` |
| `test_on_error_fires_on_partial_status` | Module 2 | Hook fires when `result.status == 'partial'` |
| `test_on_error_not_fires_on_completed_status` | Module 2 | Hook does NOT fire when `result.status == 'completed'` |
| `test_hook_receives_crew_name_and_result` | Module 2 | Callback receives `(crew_name, CrewResult)` |
| `test_async_hook_supported` | Module 2 | Async callback is properly awaited |
| `test_sync_hook_supported` | Module 2 | Sync callback runs without errors |
| `test_hook_exception_does_not_block_return` | Module 2 | Raising in a hook logs error, result still returns |
| `test_multiple_hooks_all_fire` | Module 2 | All registered hooks fire in order |
| `test_fire_hooks_directly` | Module 2 | `_fire_hooks()` dispatches based on status |

### Integration Tests

| Test | Description |
|---|---|
| `test_hooks_fire_after_run_sequential` | End-to-end: register hook, run sequential, verify hook was called |
| `test_hooks_fire_after_run_parallel` | End-to-end: register hook, run parallel, verify hook was called |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_crew():
    """Create a minimal AgentCrew with mock agents for hook testing."""
    ...

@pytest.fixture
def completed_result():
    """CrewResult with status='completed'."""
    return CrewResult(output="done", status="completed")

@pytest.fixture
def failed_result():
    """CrewResult with status='failed'."""
    return CrewResult(output=None, status="failed", errors={"agent1": "boom"})

@pytest.fixture
def partial_result():
    """CrewResult with status='partial'."""
    return CrewResult(output="partial", status="partial", errors={"agent2": "failed"})
```

---

## 5. Acceptance Criteria

- [x] `CrewHookCallback` type alias defined in `parrot/bots/flows/core/types.py`
- [ ] `AgentCrew.on_complete(callback)` registers a callback
- [ ] `AgentCrew.on_error(callback)` registers a callback
- [ ] `_fire_hooks(result)` dispatches hooks based on `result.status`:
  - `completed` → on_complete hooks only
  - `partial` → both on_complete AND on_error hooks
  - `failed` → on_error hooks only
- [ ] Both sync and async callbacks are supported
- [ ] Exceptions in hooks are caught, logged, and do not prevent result return
- [ ] Hooks fire in all four execution modes: sequential, loop, parallel, flow
- [ ] Hooks receive `(crew_name: str, result: CrewResult)` as arguments
- [ ] Multiple hooks can be registered and all fire in registration order
- [ ] All unit tests pass (`pytest tests/test_crew_hooks.py -v`)
- [ ] No breaking changes to existing public API
- [ ] No modification to existing `on_agent_complete` parameter in `run_flow()`

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Already imported in crew.py
from ...models.crew import CrewResult  # verified: crew.py:42-47
from ..flows.core.types import AgentRef, DependencyResults, PromptBuilder  # verified: crew.py:55-59

# Must ADD to crew.py imports:
from ..flows.core.types import CrewHookCallback  # NEW — after defining in types.py

# Already in types.py:
from typing import Any, Awaitable, Callable, Dict, Protocol, Union  # verified: types.py:12-19
ActionCallback = Callable[..., Union[None, Awaitable[None]]]  # verified: types.py:27
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/orchestration/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):  # line 148
    def __init__(
        self,
        name: str = "AgentCrew",                           # line 189
        agents: List[Union[BasicAgent, AbstractBot]] = None,  # line 190
        ...
        **kwargs                                            # line 204
    ):  # line 187
        self.name = name or 'AgentCrew'                     # line 215
        self.agents: Dict[str, Union[BasicAgent, AbstractBot]] = {}  # line 216
        self.logger = logging.getLogger(f"parrot.crews.{self.name}")  # line 223
        self._persist_tasks: set[asyncio.Task] = set()      # line 278
        # Hook lists will be added after line 278

    async def run_sequential(self, query: str, ...) -> CrewResult:  # line 1059
        # ... returns at line 1378

    async def run_loop(self, initial_task: str, ...) -> CrewResult:  # line 1380
        # ... returns at line 1835

    async def run_parallel(self, tasks: List[Dict[str, Any]], ...) -> CrewResult:  # line 1837
        # ... returns at line 2148

    async def run_flow(self, initial_task: str, ..., on_agent_complete=None) -> CrewResult:  # line 2150
        # ... returns at line 2383

# packages/ai-parrot/src/parrot/models/crew.py
@dataclass
class CrewResult:  # line 60
    output: Any                                             # line 80
    responses: Dict[str, ResponseType] = ...                # line 81
    summary: str = ""                                       # line 82
    agents: List[AgentExecutionInfo] = ...                  # line 83
    execution_log: List[Dict[str, Any]] = ...               # line 85
    total_time: float = 0.0                                 # line 87
    status: Literal['completed', 'partial', 'failed'] = 'completed'  # line 88
    errors: Dict[str, str] = ...                            # line 95
    metadata: Dict[str, Any] = ...                          # line 96

# packages/ai-parrot/src/parrot/bots/flows/core/types.py
ActionCallback = Callable[..., Union[None, Awaitable[None]]]  # line 27

# packages/ai-parrot/src/parrot/bots/flows/core/result.py
def determine_run_status(
    success_count: int, failure_count: int
) -> Literal["completed", "partial", "failed"]:  # line 162-165
    # completed: failure_count==0
    # failed: success_count==0
    # partial: both > 0
```

### Hook Insertion Points (exact lines)

All four `run_*()` methods share this identical tail pattern:

```python
# Save result (fire-and-forget, tracked for lifecycle cleanup)
_persist_task = asyncio.get_running_loop().create_task(
    self._save_result(result, 'run_<mode>', ...)
)
self._persist_tasks.add(_persist_task)
_persist_task.add_done_callback(self._persist_tasks.discard)

return result
```

| Method | Persist block starts | Return line | Insert `_fire_hooks` BEFORE persist |
|--------|---------------------|-------------|-------------------------------------|
| `run_sequential` | 1366 | 1378 | Line 1365 (after synthesis) |
| `run_loop` | 1823 | 1835 | Line 1822 (after synthesis) |
| `run_parallel` | 2136 | 2148 | Line 2135 (after synthesis) |
| `run_flow` | 2371 | 2383 | Line 2370 (after synthesis) |

### Reference Pattern: Node.run_post_actions

```python
# packages/ai-parrot/src/parrot/bots/flows/core/node.py:121-135
async def run_post_actions(self, result=None, **ctx):
    for action in self._post_actions:
        res = action(self.name, result, **ctx)
        if asyncio.iscoroutine(res):
            await res
```

### Reference Pattern: AbstractBot._trigger_event

```python
# packages/ai-parrot/src/parrot/bots/abstract.py:824-834
def _trigger_event(self, event_name: str, **kwargs) -> None:
    if event_name in self._listeners:
        for callback in self._listeners[event_name]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(event_name, **kwargs))
                else:
                    callback(event_name, **kwargs)
            except Exception as e:
                self.logger.error(f"Error in event listener for {event_name}: {e}")
```

**Note**: Our `_fire_hooks` should NOT use `asyncio.create_task()` for async
callbacks (unlike `_trigger_event`). We want hooks to complete before returning
the result, so we `await` directly (like `run_post_actions`).

### Does NOT Exist (Anti-Hallucination)

- ~~`AgentCrew.on_complete`~~ — does not exist yet (this spec adds it)
- ~~`AgentCrew.on_error`~~ — does not exist yet (this spec adds it)
- ~~`AgentCrew._fire_hooks`~~ — does not exist yet (this spec adds it)
- ~~`AgentCrew._on_complete_hooks`~~ — does not exist yet
- ~~`AgentCrew._on_error_hooks`~~ — does not exist yet
- ~~`CrewHookCallback`~~ — does not exist yet in types.py
- ~~`AgentCrew.hooks`~~ — no generic hooks property exists
- ~~`CrewResult.on_complete`~~ — CrewResult has no hook methods
- ~~`CrewDefinition.hooks`~~ — CrewDefinition has no hooks field

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Combine** `Node.run_post_actions` iteration (await sync/async) **with**
  `AbstractBot._trigger_event` error isolation (try/except per hook).
- Use `asyncio.iscoroutinefunction(callback)` for pre-check (not
  `asyncio.iscoroutine(result)` after calling) — more correct for detecting
  async callables before invocation.
- Initialize hook lists in `__init__` between the persistence block (line 278)
  and the agents-add loop (line 281).
- Registration methods are simple appends — no deduplication needed.

### Known Risks / Gotchas

- **Hook ordering**: Hooks fire in registration order. If a user depends on
  ordering, they must register in the correct order. Document this.
- **Long-running hooks block return**: `_fire_hooks` awaits each hook before
  returning `CrewResult`. For expensive post-processing, users should wrap
  work in `asyncio.create_task()` inside their hook. Document this.
- **Partial fires both lists**: For `partial` status, both `on_complete` and
  `on_error` hooks fire. This is intentional — `partial` means usable results
  exist but errors also occurred. Users' hooks should check `result.status`
  if they need to distinguish.

### External Dependencies

None — no new packages required.

---

## 8. Open Questions

*All questions resolved during proposal research. No open items.*

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks)
- All three modules (type, implementation, tests) must be implemented in order.
- No parallelizable tasks — Module 2 depends on Module 1, Module 3 depends on
  Module 2.
- **Cross-feature dependencies**: None. FEAT-156 (from_definition) is orthogonal.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-11 | Jesus Lara / Claude Code | Initial draft from FEAT-157 proposal |
