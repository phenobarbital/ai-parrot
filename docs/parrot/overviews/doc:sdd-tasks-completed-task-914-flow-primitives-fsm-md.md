---
type: Wiki Overview
title: 'TASK-914: FSM Module — AgentTaskMachine and TransitionCondition'
id: doc:sdd-tasks-completed-task-914-flow-primitives-fsm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extracts `AgentTaskMachine` and `TransitionCondition` from
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.fsm
  rel: mentions
---

# TASK-914: FSM Module — AgentTaskMachine and TransitionCondition

**Feature**: FEAT-134 — Flow Primitives — Shared Core for AgentCrew & AgentsFlow
**Spec**: `sdd/specs/flow-primitives.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-913
**Assigned-to**: unassigned

---

## Context

Extracts `AgentTaskMachine` and `TransitionCondition` from
`parrot.bots.flow.fsm` into the shared `parrot.bots.flows.core.fsm` module.
These are the FSM primitives that both engines will consume.

Implements Spec §3 Module 2.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/core/fsm.py` containing:
  - `TransitionCondition(str, Enum)` — extracted from `parrot.bots.flow.fsm:51-57`
  - `AgentTaskMachine(StateMachine)` — extracted from `parrot.bots.flow.fsm:60-112`
    with identical states and transitions.
- Write unit tests in `packages/ai-parrot/tests/test_flow_primitives/test_fsm.py`.

**NOT in scope**: `FlowTransition`, `FlowNode` — those stay in their
respective modules for now (transition.py and the engine).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/fsm.py` | CREATE | FSM definitions |
| `packages/ai-parrot/tests/test_flow_primitives/test_fsm.py` | CREATE | FSM unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# The existing FSM implementation to extract from:
# packages/ai-parrot/src/parrot/bots/flow/fsm.py:24
from statemachine import State, StateMachine

# packages/ai-parrot/src/parrot/bots/flow/fsm.py:25
from navconfig.logging import logging
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flow/fsm.py:51-57
class TransitionCondition(str, Enum):
    ON_SUCCESS = "on_success"
    ON_ERROR = "on_error"
    ON_TIMEOUT = "on_timeout"
    ON_CONDITION = "on_condition"
    ALWAYS = "always"

# packages/ai-parrot/src/parrot/bots/flow/fsm.py:60-112
class AgentTaskMachine(StateMachine):
    idle = State("idle", initial=True)          # line 82
    ready = State("ready")                      # line 83
    running = State("running")                  # line 84
    completed = State("completed", final=True)  # line 85
    failed = State("failed")                    # line 86 — NOT final
    blocked = State("blocked")                  # line 87
    schedule = idle.to(ready)                   # line 90
    start = ready.to(running)                   # line 91
    succeed = running.to(completed)             # line 92
    fail = running.to(failed) | ready.to(failed) | idle.to(failed)  # line 93
    block = idle.to(blocked) | ready.to(blocked)                     # line 94
    unblock = blocked.to(ready)                 # line 95
    retry = failed.to(ready)                    # line 96
    def __init__(self, agent_name: str, **kwargs): ...  # line 98
    def on_enter_running(self): ...     # line 102
    def on_enter_completed(self): ...   # line 106
    def on_enter_failed(self): ...      # line 110
```

### Does NOT Exist
- ~~`parrot.bots.flows.core.fsm`~~ — does not exist yet; this task creates it
- ~~`AgentTaskMachine` in flows/core~~ — does not exist yet; only in `parrot.bots.flow.fsm`

---

## Implementation Notes

### Key Constraints
- Copy `TransitionCondition` and `AgentTaskMachine` verbatim from the existing
  `parrot.bots.flow.fsm` — preserve all states, transitions, and hooks.
- Import `State`, `StateMachine` from `statemachine` (python-statemachine v2.x).
- The new module should NOT import anything from `parrot.bots.flow.fsm` (to
  avoid circular deps). It is a fresh copy.
- `TransitionCondition` is also used by the transition module (TASK-918), so
  it lives here in fsm.py alongside the state machine.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/flow/fsm.py:51-112` — source to extract from

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/bots/flows/core/fsm.py` exists
- [ ] `TransitionCondition` has all 5 enum values matching the original
- [ ] `AgentTaskMachine` has all 6 states and 7 transition groups
- [ ] `completed` is the only `final=True` state
- [ ] `failed` is NOT final (allows `retry` transition)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_flow_primitives/test_fsm.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_flow_primitives/test_fsm.py
import pytest
from statemachine.exceptions import TransitionNotAllowed
from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition


class TestTransitionCondition:
    def test_all_values(self):
        assert TransitionCondition.ON_SUCCESS == "on_success"
        assert TransitionCondition.ON_ERROR == "on_error"
        assert TransitionCondition.ON_TIMEOUT == "on_timeout"
        assert TransitionCondition.ON_CONDITION == "on_condition"
        assert TransitionCondition.ALWAYS == "always"

    def test_has_five_members(self):
        assert len(TransitionCondition) == 5


class TestAgentTaskMachine:
    @pytest.fixture
    def fsm(self):
        return AgentTaskMachine(agent_name="test-agent")

    def test_initial_state_is_idle(self, fsm):
        assert fsm.current_state == fsm.idle

    def test_happy_path(self, fsm):
        fsm.schedule()
        assert fsm.current_state == fsm.ready
        fsm.start()
        assert fsm.current_state == fsm.running
        fsm.succeed()
        assert fsm.current_state == fsm.completed

    def test_retry_path(self, fsm):
        fsm.schedule()
        fsm.start()
        fsm.fail()
        assert fsm.current_state == fsm.failed
        fsm.retry()
        assert fsm.current_state == fsm.ready

    def test_blocked_path(self, fsm):
        fsm.block()
        assert fsm.current_state == fsm.blocked
        fsm.unblock()
        assert fsm.current_state == fsm.ready

    def test_completed_is_final(self, fsm):
        fsm.schedule()
        fsm.start()
        fsm.succeed()
        with pytest.raises(TransitionNotAllowed):
            fsm.schedule()

    def test_failed_is_not_final(self, fsm):
        fsm.schedule()
        fsm.start()
        fsm.fail()
        fsm.retry()  # should NOT raise
        assert fsm.current_state == fsm.ready

    def test_invalid_idle_to_running(self, fsm):
        with pytest.raises(TransitionNotAllowed):
            fsm.start()

    def test_invalid_idle_to_completed(self, fsm):
        with pytest.raises(TransitionNotAllowed):
            fsm.succeed()

    def test_fail_from_idle(self, fsm):
        fsm.fail()
        assert fsm.current_state == fsm.failed

    def test_fail_from_ready(self, fsm):
        fsm.schedule()
        fsm.fail()
        assert fsm.current_state == fsm.failed
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/flow-primitives.spec.md` for full context
2. **Check dependencies** — verify TASK-913 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `packages/ai-parrot/src/parrot/bots/flow/fsm.py:51-112`
   to confirm states and transitions match
4. **Implement** `fsm.py` and tests
5. **Run tests**: `pytest packages/ai-parrot/tests/test_flow_primitives/test_fsm.py -v`
6. **Update status** in `sdd/tasks/.index.json` → `"done"`
7. **Move this file** to `sdd/tasks/completed/`

---

## Completion Note

*(Agent fills this in when done)*
