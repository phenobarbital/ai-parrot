---
type: Wiki Overview
title: 'TASK-1061: Extend `FlowContext` with `resolve_agent` + AgentRegistry binding'
id: doc:sdd-tasks-completed-task-1061-flowcontext-resolve-agent-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements Spec §3 Module 2. The new `AgentsFlow` uses `AgentRegistry` (`parrot/registry/registry.py:228`)
  as the single agent-resolution source (spec §8 D5). This task extends `parrot/bots/flows/core/context.py:FlowContext`
  with:'
relates_to:
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.registry.registry
  rel: mentions
---

# TASK-1061: Extend `FlowContext` with `resolve_agent` + AgentRegistry binding

**Feature**: FEAT-163 — AgentsFlow Refactor — DAG Engine on flows.core
**Spec**: `sdd/specs/agentsflow-refactor-spec3.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1060
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 2. The new `AgentsFlow` uses `AgentRegistry` (`parrot/registry/registry.py:228`) as the single agent-resolution source (spec §8 D5). This task extends `parrot/bots/flows/core/context.py:FlowContext` with:
- An optional `agent_registry: AgentRegistry | None` binding on the context.
- A `resolve_agent(agent_ref: AgentRef) -> AgentLike` helper that delegates to the bound registry and raises `AgentNotFoundError` on miss.

The helper is the single access point for any code that needs to resolve an `agent_ref` string at runtime (in node `execute()` calls, in hooks, in user-written helpers). `AgentsFlow.from_definition()` (TASK-1068) uses the registry directly at construction time, but stores it on the context so later runtime lookups also work.

---

## Scope

- Add an `agent_registry: Optional[AgentRegistry] = None` attribute to `FlowContext` (constructor + storage). Use either a Pydantic field if `FlowContext` is a `BaseModel`, or a regular attribute if it is a dataclass / plain class — match the existing class shape (verify by reading `core/context.py` first).
- Add `resolve_agent(self, agent_ref: AgentRef) -> AgentLike` method that:
  - If `agent_ref` is already an `AgentLike` (not a string), return it as-is.
  - If it's a string, call the registry's getter (method name TBD — see OQ-7 below) and return the agent.
  - Raise `AgentNotFoundError` when not found.
- Define `AgentNotFoundError(LookupError)` in `core/context.py` (or `core/__init__.py` — pick the location consistent with existing error classes in the package; default to `context.py` if none).
- Update module docstring to document the new `resolve_agent` capability.

**NOT in scope**:
- Calling `resolve_agent` from `AgentNode.execute()` (TASK-1060 keeps `self.agent` direct usage).
- `from_definition()` eager resolution (TASK-1068).
- Modifying `parrot/registry/registry.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/context.py` | MODIFY | Add `agent_registry` attribute + `resolve_agent` method + `AgentNotFoundError` |
| `packages/ai-parrot/tests/bots/flows/core/test_context.py` | CREATE or MODIFY | Tests for the new method |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Optional, TYPE_CHECKING
from .types import AgentRef, AgentLike   # parrot/bots/flows/core/types.py:100, :55

if TYPE_CHECKING:
    from parrot.registry.registry import AgentRegistry
# Or use a string annotation if forward-refs are easier: agent_registry: "Optional[AgentRegistry]"
```

### Existing Signatures (DEPENDENCIES — confirm before editing)

```python
# packages/ai-parrot/src/parrot/bots/flows/core/context.py:26
class FlowContext:
    # Read the current shape before this task — it may already have agents bound by some other mechanism.
    ...
    def get_input_for_agent(self, agent_name: str, dependencies) -> ...:
        """Existing method used by AgentNode._build_prompt default."""

# packages/ai-parrot/src/parrot/registry/registry.py:228
class AgentRegistry:
    # OQ-7 from spec: exact getter method name to be confirmed.
    # Likely candidates: get_agent(name), get(name), lookup(name), find(name).
    # The implementer MUST grep the class body and choose the correct one.
```

### Does NOT Exist (yet)

- ~~`FlowContext.resolve_agent`~~ — added by this task.
- ~~`AgentNotFoundError`~~ — added by this task.
- ~~`FlowContext.agent_registry` attribute~~ — added by this task.

---

## Implementation Notes

### Pattern to Follow

If `FlowContext` is a dataclass (likely — most `core/` types are), use:

```python
@dataclass
class FlowContext:
    # existing fields...
    agent_registry: Optional["AgentRegistry"] = None

    def resolve_agent(self, agent_ref: AgentRef) -> AgentLike:
        if not isinstance(agent_ref, str):
            return agent_ref  # already an AgentLike instance
        if self.agent_registry is None:
            raise AgentNotFoundError(
                f"Cannot resolve agent_ref={agent_ref!r}: no agent_registry bound on FlowContext"
            )
        agent = self.agent_registry.<get_method>(agent_ref)  # verify method name
        if agent is None:
            raise AgentNotFoundError(f"Agent not registered: {agent_ref!r}")
        return agent
```

If the registry's getter already raises on miss, drop the `if agent is None` branch and let the registry's exception propagate (translate it to `AgentNotFoundError` only if it's a generic `KeyError` or similar — preserve a useful error message).

### Key Constraints

- **OQ-7 verification step (FIRST thing the agent does)**: `grep -n "def " packages/ai-parrot/src/parrot/registry/registry.py` and identify the agent-getter method on `AgentRegistry`. Use that exact name in this task. Do NOT assume `get_agent`.
- Avoid an import cycle: `AgentRegistry` lives in `parrot/registry/registry.py` which may import other things. Use `TYPE_CHECKING` + string annotation, or import lazily inside `resolve_agent()` if necessary.
- `AgentNotFoundError(LookupError)` — inherits from a standard Python lookup error so `except LookupError:` catches it for callers who don't know the specific class.
- Document `resolve_agent` in the module docstring.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/core/context.py` — current shape (read first).
- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:46-62` — imports `FlowContext` from `..core.context` (pattern for the new flow.py).
- `packages/ai-parrot/src/parrot/registry/registry.py:228` — `AgentRegistry` definition.

---

## Acceptance Criteria

- [ ] `FlowContext.agent_registry: Optional[AgentRegistry] = None` exists.
- [ ] `FlowContext.resolve_agent(agent_ref) -> AgentLike` returns the resolved agent.
- [ ] Calling `resolve_agent` with an unregistered string raises `AgentNotFoundError`.
- [ ] Calling `resolve_agent` with an `AgentLike` instance returns it unchanged.
- [ ] Calling `resolve_agent` when `agent_registry is None` raises `AgentNotFoundError` with a clear message.
- [ ] `AgentNotFoundError(LookupError)` is defined and importable from `parrot.bots.flows.core.context`.
- [ ] Unit tests in `tests/bots/flows/core/test_context.py` pass.
- [ ] `python -c "from parrot.bots.flows.core.context import FlowContext, AgentNotFoundError"` succeeds.
- [ ] No linting errors on `core/context.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/core/test_context.py
import pytest

from parrot.bots.flows.core.context import FlowContext, AgentNotFoundError


class StubAgent:
    name = "stub"
    async def ask(self, question="", **kwargs): return question


class StubRegistry:
    """Minimal AgentRegistry stub. Replace the lookup-method name to match
    the real registry's getter (verified in TASK-1061 implementation)."""
    def __init__(self, agents): self._agents = agents
    # Use the SAME method name FlowContext.resolve_agent calls.
    def get_agent(self, name):  # ← replace if real name differs
        return self._agents.get(name)


class TestResolveAgent:
    def test_returns_agent_for_known_ref(self):
        ctx = FlowContext(agent_registry=StubRegistry({"stub": StubAgent()}))
        agent = ctx.resolve_agent("stub")
        assert agent.name == "stub"

    def test_raises_for_unknown_ref(self):
        ctx = FlowContext(agent_registry=StubRegistry({}))
        with pytest.raises(AgentNotFoundError):
            ctx.resolve_agent("missing")

    def test_raises_when_no_registry(self):
        ctx = FlowContext()  # no agent_registry
        with pytest.raises(AgentNotFoundError):
            ctx.resolve_agent("anything")

    def test_passthrough_for_agentlike(self):
        ctx = FlowContext()
        agent = StubAgent()
        assert ctx.resolve_agent(agent) is agent
```

---

## Agent Instructions

1. Read the spec §3 Module 2 and §8 OQ-7.
2. Confirm TASK-1060 is in `sdd/tasks/completed/`.
3. **First action**: `grep -n "def " packages/ai-parrot/src/parrot/registry/registry.py | head -40` and identify the agent-getter method. Update the contract above and the test stub if it differs from `get_agent`.
4. Read `core/context.py` end-to-end to understand the current shape.
5. Implement following the pattern above.
6. Run `pytest packages/ai-parrot/tests/bots/flows/core/test_context.py -v`.
7. Verify acceptance criteria.
8. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
