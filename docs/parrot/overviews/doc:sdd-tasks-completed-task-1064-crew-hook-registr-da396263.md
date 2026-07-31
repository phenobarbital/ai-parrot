---
type: Wiki Overview
title: 'TASK-1064: Hook registration and dispatch in AgentCrew'
id: doc:sdd-tasks-completed-task-1064-crew-hook-registration-dispatch-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This is the core task for FEAT-157. It implements Module 2 from the spec
  (§3):'
relates_to:
- concept: mod:parrot
  rel: mentions
---

# TASK-1064: Hook registration and dispatch in AgentCrew

**Feature**: FEAT-157 — AgentCrew Lifecycle Hooks
**Spec**: `sdd/specs/agentcrew-hooks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1063
**Assigned-to**: unassigned

---

## Context

This is the core task for FEAT-157. It implements Module 2 from the spec (§3):
hook storage, registration methods, the dispatch method, and integration into
all four `run_*()` execution modes.

---

## Scope

- Add `_on_complete_hooks` and `_on_error_hooks` lists to `AgentCrew.__init__`
- Add `on_complete(callback)` public registration method
- Add `on_error(callback)` public registration method
- Add `_fire_hooks(result: CrewResult)` private async dispatch method
- Insert `await self._fire_hooks(result)` call in all four `run_*()` methods
- Import `CrewHookCallback` from `flows.core.types`

**NOT in scope**: Tests (TASK-1065), type alias definition (TASK-1063),
modifying `on_agent_complete` in `run_flow()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | MODIFY | Add hook lists, registration methods, dispatch, and run_* integration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already in crew.py — DO NOT duplicate:
from ...models.crew import CrewResult  # verified: crew.py:42-47
from ..flows.core.types import (
    AgentRef,
    DependencyResults,
    PromptBuilder,
)  # verified: crew.py:55-59

# MUST ADD to the existing import block at crew.py:55-59:
from ..flows.core.types import CrewHookCallback  # NEW — from TASK-1063
# Merge into the existing import group, e.g.:
# from ..flows.core.types import (
#     AgentRef, CrewHookCallback, DependencyResults, PromptBuilder,
# )
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/orchestration/crew.py

class AgentCrew(PersistenceMixin, SynthesisMixin):  # line 148
    def __init__(self, name: str = "AgentCrew", ...):  # line 187
        self.name = name or 'AgentCrew'                # line 215
        self.logger = logging.getLogger(f"parrot.crews.{self.name}")  # line 223
        self._persist_tasks: set[asyncio.Task] = set()  # line 278
        # >>> INSERT hook lists after line 278, before agent-add loop at line 281

    async def run_sequential(self, query: str, ...) -> CrewResult:  # line 1059
        # Tail: persist block at lines 1366-1376, return at line 1378
        # >>> INSERT await self._fire_hooks(result) BEFORE line 1366

    async def run_loop(self, initial_task: str, ...) -> CrewResult:  # line 1380
        # Tail: persist block at lines 1823-1833, return at line 1835
        # >>> INSERT await self._fire_hooks(result) BEFORE line 1823

    async def run_parallel(self, tasks: List[...], ...) -> CrewResult:  # line 1837
        # Tail: persist block at lines 2136-2146, return at line 2148
        # >>> INSERT await self._fire_hooks(result) BEFORE line 2136

    async def run_flow(self, initial_task: str, ...) -> CrewResult:  # line 2150
        # Tail: persist block at lines 2371-2381, return at line 2383
        # >>> INSERT await self._fire_hooks(result) BEFORE line 2371

# packages/ai-parrot/src/parrot/models/crew.py
@dataclass
class CrewResult:  # line 60
    status: Literal['completed', 'partial', 'failed'] = 'completed'  # line 88
```

### Reference Patterns

```python
# Pattern 1: Node.run_post_actions (iteration + async handling)
# packages/ai-parrot/src/parrot/bots/flows/core/node.py:121-135
async def run_post_actions(self, result=None, **ctx):
    for action in self._post_actions:
        res = action(self.name, result, **ctx)
        if asyncio.iscoroutine(res):
            await res

# Pattern 2: AbstractBot._trigger_event (error isolation)
# packages/ai-parrot/src/parrot/bots/abstract.py:824-834
def _trigger_event(self, event_name, **kwargs):
    for callback in self._listeners[event_name]:
        try:
            if asyncio.iscoroutinefunction(callback):
                asyncio.create_task(callback(event_name, **kwargs))
            else:
                callback(event_name, **kwargs)
        except Exception as e:
            self.logger.error(f"Error in event listener for {event_name}: {e}")
```

**IMPORTANT**: Combine both patterns — iterate and support async (Pattern 1) but
wrap each callback in try/except (Pattern 2). Do NOT use `asyncio.create_task()`
for async hooks — `await` them directly so hooks complete before returning.

### Does NOT Exist

- ~~`AgentCrew.on_complete`~~ — does not exist yet; this task creates it
- ~~`AgentCrew.on_error`~~ — does not exist yet; this task creates it
- ~~`AgentCrew._fire_hooks`~~ — does not exist yet; this task creates it
- ~~`AgentCrew._on_complete_hooks`~~ — does not exist yet
- ~~`AgentCrew._on_error_hooks`~~ — does not exist yet
- ~~`AgentCrew.hooks`~~ — no generic hooks property exists
- ~~`AgentCrew.add_hook()`~~ — no such method exists

---

## Implementation Notes

### 1. Initialize hook lists in `__init__` (after line 278)

```python
        # Lifecycle hooks (FEAT-157)
        self._on_complete_hooks: List[CrewHookCallback] = []
        self._on_error_hooks: List[CrewHookCallback] = []
```

### 2. Registration methods (add as public methods on AgentCrew)

```python
    def on_complete(self, callback: CrewHookCallback) -> None:
        """Register a callback to fire when crew execution completes.

        Fires for status 'completed' and 'partial'. Callbacks receive
        (crew_name, result) and may be sync or async.

        Args:
            callback: Callable with signature (crew_name: str, result: CrewResult).
        """
        self._on_complete_hooks.append(callback)

    def on_error(self, callback: CrewHookCallback) -> None:
        """Register a callback to fire when crew execution has errors.

        Fires for status 'failed' and 'partial'. Callbacks receive
        (crew_name, result) and may be sync or async.

        Args:
            callback: Callable with signature (crew_name: str, result: CrewResult).
        """
        self._on_error_hooks.append(callback)
```

### 3. Dispatch method

```python
    async def _fire_hooks(self, result: CrewResult) -> None:
        """Dispatch lifecycle hooks based on result status.

        - 'completed': on_complete hooks only
        - 'partial': both on_complete AND on_error hooks
        - 'failed': on_error hooks only
        """
        hooks_to_fire: List[CrewHookCallback] = []
        if result.status in ('completed', 'partial'):
            hooks_to_fire.extend(self._on_complete_hooks)
        if result.status in ('failed', 'partial'):
            hooks_to_fire.extend(self._on_error_hooks)

        for hook in hooks_to_fire:
            try:
                ret = hook(self.name, result)
                if asyncio.iscoroutine(ret):
                    await ret
            except Exception as e:
                self.logger.error(
                    f"Error in crew lifecycle hook {hook!r}: {e}"
                )
```

### 4. Insert `_fire_hooks` in all four run_* methods

In each method, add this line BEFORE the persist block (the `# Save result`
comment and `asyncio.get_running_loop().create_task(...)` call):

```python
        # Fire lifecycle hooks (FEAT-157)
        await self._fire_hooks(result)
```

Insert at:
- `run_sequential`: before line 1366
- `run_loop`: before line 1823
- `run_parallel`: before line 2136
- `run_flow`: before line 2371

### Key Constraints

- Do NOT modify the `on_agent_complete` parameter in `run_flow()`
- Do NOT add hooks to `CrewResult` or `CrewDefinition`
- Registration methods must be simple appends — no deduplication
- `_fire_hooks` must catch exceptions per-hook and log with `self.logger.error`
- `_fire_hooks` must `await` async hooks directly (NOT `create_task`)

---

## Acceptance Criteria

- [ ] `_on_complete_hooks` and `_on_error_hooks` initialized in `__init__`
- [ ] `on_complete(callback)` appends to `_on_complete_hooks`
- [ ] `on_error(callback)` appends to `_on_error_hooks`
- [ ] `_fire_hooks(result)` dispatches based on `result.status`
- [ ] `_fire_hooks` called in `run_sequential` before persist block
- [ ] `_fire_hooks` called in `run_loop` before persist block
- [ ] `_fire_hooks` called in `run_parallel` before persist block
- [ ] `_fire_hooks` called in `run_flow` before persist block
- [ ] Both sync and async callbacks handled
- [ ] Exceptions in hooks caught and logged, do not prevent return
- [ ] No modification to existing `on_agent_complete` in `run_flow`
- [ ] `CrewHookCallback` imported from `..flows.core.types`

---

## Test Specification

Tests are handled in TASK-1065.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentcrew-hooks.spec.md` for full context
2. **Check dependencies** — TASK-1063 must be completed first
3. **Verify the Codebase Contract** — confirm line numbers are still accurate
4. **Implement** following the scope and implementation notes above
5. **Verify** with a quick manual import test
6. **Update status** in per-spec index → `"done"`
7. **Move this file** to `sdd/tasks/completed/`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-05-11
**Notes**: Implemented in `parrot/bots/flows/crew/crew.py` (NOT
`orchestration/crew.py` — AgentCrew was moved to `flows/crew/` in FEAT-143).
Added `CrewHookCallback` import, `_on_complete_hooks`/`_on_error_hooks` lists
in `__init__`, `on_complete()`/`on_error()` registration methods, and
`_fire_hooks()` dispatch. Inserted `await self._fire_hooks(result)` before the
persist block in `run_sequential`, `run_loop`, `run_parallel`, and `run_flow`.

**Deviations from spec**: Task spec listed `orchestration/crew.py` as the
target — actual target is `flows/crew/crew.py` (corrected at user's direction).
Result type is `FlowResult` (not `CrewResult`) — `FlowStatus` is `str, Enum`
so string comparisons in `_fire_hooks` work correctly.
