---
type: Wiki Overview
title: 'TASK-1678: AgentDispatcher protocol + dispatcher slot on JiraSpecialist'
id: doc:sdd-tasks-completed-task-1678-agent-dispatcher-protocol-slot-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation for FEAT-265 (spec §2, §3 Module 1). `JiraSpecialist` currently
relates_to:
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.bots._types
  rel: mentions
- concept: mod:parrot.bots.jira_specialist
  rel: mentions
---

# TASK-1678: AgentDispatcher protocol + dispatcher slot on JiraSpecialist

**Feature**: FEAT-265 — JiraSpecialist trigger_agent → Orchestrator Dispatch
**Spec**: `sdd/specs/jiraspecialist-trigger-agent-orchestrator.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation for FEAT-265 (spec §2, §3 Module 1). `JiraSpecialist` currently
holds no way to dispatch another agent, so the `TRIGGER_AGENT` transition
action is inert. This task adds the injectable seam **without** importing the
server-side `AutonomousOrchestrator` (core must not import server — spec §1
boundary goal).

It defines a shared, duck-typed `AgentDispatcher` Protocol and adds a slot +
setter on `JiraSpecialist`. It does NOT change `_action_trigger_agent` yet —
that is TASK-1679.

---

## Scope

- Create a new shared module `parrot/bots/_types.py` defining the
  `AgentDispatcher` `typing.Protocol` (async `__call__(agent_name, task, *,
  user_id=None, session_id=None) -> Any`).
- In `JiraSpecialist.__init__`, add
  `self._agent_dispatcher: Optional[AgentDispatcher] = None` (alongside the
  other instance attrs around line 229-236).
- Add `set_agent_dispatcher(self, dispatcher: AgentDispatcher) -> None` to
  `JiraSpecialist` with a Google-style docstring noting that without it,
  `TRIGGER_AGENT` degrades to log-only.
- Import `AgentDispatcher` into `jira_specialist.py` (TYPE_CHECKING-safe is
  fine, but a runtime import is OK since `_types.py` has no heavy deps).
- Add unit tests for the slot/setter and a structural check that
  `AutonomousOrchestrator.execute_agent` satisfies the protocol shape.

**NOT in scope**: changing `_action_trigger_agent` body (TASK-1679); the
startup wiring snippet (TASK-1680).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/_types.py` | CREATE | `AgentDispatcher` Protocol |
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | Add slot in `__init__` + `set_agent_dispatcher()` + import |
| `packages/ai-parrot/tests/test_jira_transition_dispatch.py` | MODIFY | Add tests for slot/setter + protocol shape |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.jira_specialist import JiraSpecialist
# verified: packages/ai-parrot/src/parrot/bots/jira_specialist.py:154

# NEW (created by this task):
# from parrot.bots._types import AgentDispatcher
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):                                   # line 154
    def __init__(self, **kwargs): ...                          # line 204
        # existing attrs set near the end of __init__:
        self._wrapper = None                                   # line 232
        self.jira_toolkit: Optional[JiraToolkit] = None        # line 234
        self._transition_actions: List[TransitionAction] = ... # line 236
        # ADD HERE: self._agent_dispatcher: Optional[AgentDispatcher] = None

# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py
class AutonomousOrchestrator:
    async def execute_agent(                                   # line 406
        self, agent_name: str, task: str, *,
        method_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs) -> ExecutionResult: ...
    # ^ already satisfies AgentDispatcher (extra params keyword-only w/ defaults)
```

### Does NOT Exist
- ~~`parrot.bots._types`~~ — does NOT exist yet; this task creates it.
- ~~`JiraSpecialist.orchestrator` / `JiraSpecialist._orchestrator`~~ — no such
  attribute; this task adds `_agent_dispatcher`, NOT a typed orchestrator handle.
- ~~core importing `parrot.autonomous.*`~~ — MUST NOT be added (layering rule).
- ~~`AutonomousOrchestrator.dispatch_agent`~~ — the method is `execute_agent`.

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/bots/_types.py
from typing import Any, Optional, Protocol


class AgentDispatcher(Protocol):
    """Duck-typed async callable that dispatches a named agent.

    AutonomousOrchestrator.execute_agent satisfies this shape.
    """
    async def __call__(
        self,
        agent_name: str,
        task: str,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Any: ...
```

### Key Constraints
- async-first; the dispatcher is always an async callable.
- Do NOT import anything from `parrot.autonomous` / `ai-parrot-server` into core.
- Use `typing.Protocol` (structural typing) — no inheritance coupling.
- Keep `_types.py` dependency-free (stdlib `typing` only).

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/jira_specialist.py:204-236` — `__init__` attrs
- `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:406` — `execute_agent`

---

## Acceptance Criteria

- [ ] `parrot/bots/_types.py` exists and defines `AgentDispatcher(Protocol)`.
- [ ] `from parrot.bots._types import AgentDispatcher` resolves.
- [ ] `JiraSpecialist` instances start with `_agent_dispatcher is None`.
- [ ] `set_agent_dispatcher()` stores the callable.
- [ ] No `parrot.autonomous` import added to core (grep-clean).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/test_jira_transition_dispatch.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_jira_transition_dispatch.py
from parrot.bots._types import AgentDispatcher


def test_set_agent_dispatcher_sets_attr(specialist):
    async def disp(agent_name, task, *, user_id=None, session_id=None):
        return None
    assert specialist._agent_dispatcher is None
    specialist.set_agent_dispatcher(disp)
    assert specialist._agent_dispatcher is disp


def test_execute_agent_satisfies_protocol():
    """AutonomousOrchestrator.execute_agent matches the AgentDispatcher shape."""
    # Structural: a callable with (agent_name, task, *, user_id, session_id)
    # qualifies. Assert via a duck-typed stub standing in for the orchestrator.
    class _Orch:
        async def execute_agent(self, agent_name, task, *, method_name=None,
                                user_id=None, session_id=None, **kw):
            return {"ok": True}
    disp: AgentDispatcher = _Orch().execute_agent  # must type/assign cleanly
    assert callable(disp)
```

---

## Agent Instructions

1. Read the spec §2/§3 for full context.
2. Verify the Codebase Contract (`read` the `__init__` lines, confirm line nums).
3. Update index → `in-progress`.
4. Implement per scope.
5. Verify acceptance criteria + run the test file.
6. Move this file to `sdd/tasks/completed/`.
7. Update index → `done`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-01
**Notes**: Created `parrot/bots/_types.py` with the `AgentDispatcher` Protocol
(stdlib `typing` only, dependency-free). Added `self._agent_dispatcher:
Optional[AgentDispatcher] = None` to `JiraSpecialist.__init__` next to the
other instance attrs, and `set_agent_dispatcher()` with a Google-style
docstring. Added `TestAgentDispatcherSlot` (3 tests: default-None, setter
stores callable, structural protocol-shape check against an
`AutonomousOrchestrator.execute_agent`-shaped stub) and wired
`_agent_dispatcher = None` into the existing `_make_specialist()` test
helper so other tests in the file remain unaffected. All 40 tests in
`test_jira_transition_dispatch.py` pass; `ruff check` clean;
grep-verified no `parrot.autonomous` / `AutonomousOrchestrator` import was
introduced into core (only docstring/comment mentions).
**Deviations from spec**: none
