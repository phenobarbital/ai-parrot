---
type: Wiki Overview
title: 'TASK-913: Types Module — AgentLike Protocol, Type Aliases, FlowStatus'
id: doc:sdd-tasks-completed-task-913-flow-primitives-types-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundation task for the flow-primitives feature. It creates the
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.agent
  rel: mentions
---

# TASK-913: Types Module — AgentLike Protocol, Type Aliases, FlowStatus

**Feature**: FEAT-134 — Flow Primitives — Shared Core for AgentCrew & AgentsFlow
**Spec**: `sdd/specs/flow-primitives.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for the flow-primitives feature. It creates the
`parrot/bots/flows/core/types.py` module containing the `AgentLike` Protocol,
shared type aliases (`AgentRef`, `DependencyResults`, `PromptBuilder`,
`ActionCallback`), and the `FlowStatus` enum.

These types are currently duplicated across `parrot.bots.orchestration.crew`
and `parrot.bots.flow.fsm`. This task consolidates them into a single
canonical location.

Implements Spec §3 Module 1.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/` directory structure with
  `__init__.py` placeholders.
- Create `packages/ai-parrot/src/parrot/bots/flows/core/` directory with
  `__init__.py` placeholder.
- Create `packages/ai-parrot/src/parrot/bots/flows/core/types.py` containing:
  - `AgentLike` — `@runtime_checkable` Protocol with `name` property and
    `async def invoke(self, prompt: str, **kwargs) -> Any` method.
  - `AgentRef = Union[str, AgentLike]` — replaces
    `Union[str, BasicAgent, AbstractBot]` in both engines.
  - `DependencyResults = Dict[str, str]`
  - `PromptBuilder = Callable[[Any, DependencyResults], Union[str, Awaitable[str]]]`
  - `ActionCallback = Callable[..., Union[None, Awaitable[None]]]`
  - `FlowStatus(str, Enum)` with values: `COMPLETED = "completed"`,
    `PARTIAL = "partial"`, `FAILED = "failed"`.
- Write unit tests in `packages/ai-parrot/tests/test_flow_primitives/test_types.py`.

**NOT in scope**: FSM, Node hierarchy, result models, context, transitions,
storage, re-exports.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/__init__.py` | CREATE | Package init (empty placeholder) |
| `packages/ai-parrot/src/parrot/bots/flows/core/__init__.py` | CREATE | Package init (empty placeholder) |
| `packages/ai-parrot/src/parrot/bots/flows/core/types.py` | CREATE | Type definitions |
| `packages/ai-parrot/tests/test_flow_primitives/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot/tests/test_flow_primitives/test_types.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# These are the EXISTING duplicated type aliases to consolidate:
# packages/ai-parrot/src/parrot/bots/orchestration/crew.py:55-57
AgentRef = Union[str, BasicAgent, AbstractBot]
DependencyResults = Dict[str, str]
PromptBuilder = Callable[[AgentContext, DependencyResults], Union[str, Awaitable[str]]]

# packages/ai-parrot/src/parrot/bots/flow/fsm.py:46-48
AgentRef = Union[str, BasicAgent, AbstractBot]
DependencyResults = Dict[str, str]
PromptBuilder = Callable[[AgentContext, DependencyResults], Union[str, Awaitable[str]]]

# packages/ai-parrot/src/parrot/bots/flow/node.py:11
ActionCallback = Callable[..., Union[None, Awaitable[None]]]
```

### Existing Signatures to Use
```python
# The new AgentLike Protocol should be satisfiable by existing bot classes.
# Verify these classes have `name` property and an async invocation method:

# packages/ai-parrot/src/parrot/bots/agent.py — BasicAgent
# Has: name property, async def ask(self, question: str, **kwargs)

# packages/ai-parrot/src/parrot/bots/abstract.py — AbstractBot
# Has: name property, async def ask(self, question: str, **kwargs)

# packages/ai-parrot/src/parrot/bots/flow/nodes/start.py:6 — StartNode
# Has: name property, async def ask(self, question: str, **ctx) -> str
```

### Does NOT Exist
- ~~`parrot.bots.flows`~~ — does not exist yet; this task creates it
- ~~`parrot.bots.flows.core`~~ — does not exist yet; this task creates it
- ~~`AgentLike`~~ — does not exist anywhere yet
- ~~`FlowStatus`~~ — does not exist anywhere yet
- ~~`parrot.bots.flows.core.types`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
from __future__ import annotations
from typing import (
    Any, Awaitable, Callable, Dict, Protocol, Union,
    runtime_checkable,
)
from enum import Enum


ActionCallback = Callable[..., Union[None, Awaitable[None]]]


class FlowStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@runtime_checkable
class AgentLike(Protocol):
    @property
    def name(self) -> str: ...
    async def invoke(self, prompt: str, **kwargs) -> Any: ...


AgentRef = Union[str, AgentLike]
DependencyResults = Dict[str, str]
PromptBuilder = Callable[[Any, DependencyResults], Union[str, Awaitable[str]]]
```

### Key Constraints
- NO imports from `parrot.bots.*` — types.py must be import-cycle-free.
- `AgentLike` must use `@runtime_checkable` so `isinstance()` works.
- `PromptBuilder` first argument is `Any` (not `AgentContext`) to avoid
  coupling to `parrot.tools.agent`.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/bots/flows/core/types.py` exists
- [ ] `AgentLike` Protocol defined with `name` property and `invoke()` method
- [ ] `AgentLike` is `@runtime_checkable`
- [ ] `FlowStatus` enum has exactly `COMPLETED`, `PARTIAL`, `FAILED` values
- [ ] `AgentRef`, `DependencyResults`, `PromptBuilder`, `ActionCallback` defined
- [ ] No imports from `parrot.bots.*` or `parrot.tools.*`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_flow_primitives/test_types.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_flow_primitives/test_types.py
import pytest
from parrot.bots.flows.core.types import (
    AgentLike, AgentRef, DependencyResults, PromptBuilder,
    ActionCallback, FlowStatus,
)


class MockAgent:
    @property
    def name(self) -> str:
        return "mock"
    async def invoke(self, prompt: str, **kwargs):
        return f"response: {prompt}"


class BadAgent:
    pass


class TestAgentLikeProtocol:
    def test_conforming_object_is_instance(self):
        assert isinstance(MockAgent(), AgentLike)

    def test_non_conforming_object_is_not_instance(self):
        assert not isinstance(BadAgent(), AgentLike)

    def test_string_is_not_agent_like(self):
        assert not isinstance("agent-name", AgentLike)


class TestFlowStatus:
    def test_values(self):
        assert FlowStatus.COMPLETED == "completed"
        assert FlowStatus.PARTIAL == "partial"
        assert FlowStatus.FAILED == "failed"

    def test_enum_has_exactly_three_members(self):
        assert len(FlowStatus) == 3
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/flow-primitives.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm the existing type aliases at
   `crew.py:55-57` and `fsm.py:46-48` still match
4. **Create the directory structure** first (`flows/`, `flows/core/`)
5. **Implement** `types.py` and tests
6. **Run tests**: `pytest packages/ai-parrot/tests/test_flow_primitives/test_types.py -v`
7. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` / `"done"`
8. **Move this file** to `sdd/tasks/completed/`

---

## Completion Note

*(Agent fills this in when done)*
