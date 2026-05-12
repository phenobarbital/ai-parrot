# TASK-1062: Migrate `parrot/bots/flows/crew/` to the new AgentNode shape

**Feature**: FEAT-163 — AgentsFlow Refactor — DAG Engine on flows.core
**Spec**: `sdd/specs/agentsflow-refactor-spec3.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1060
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 3. TASK-1060 changed `core.node.AgentNode` from `@dataclass` to frozen Pydantic and changed its `execute()` signature. `CrewAgentNode` (`parrot/bots/flows/crew/nodes.py`) subclasses `_CoreAgentNode` and inherits this contract; the instantiation site at `parrot/bots/flows/crew/crew.py:223` constructs it with keyword args. This task migrates both files to match the new Pydantic shape so AgentCrew tests pass again.

**Critical scope guard**: `.fsm` access sites in `crew.py` (lines 567–570, 586–587, 649–650, 1102–1104, 1202–1203, 1212–1213) are **not** touched — FSM stays as a field on the node and `node.fsm.<method>()` calls continue to work unchanged. This is the B-lite contract (spec §1 Goals + §8 OQ-8).

**`parrot/bots/orchestration/` is explicitly out of scope** — separate deletion track per spec §1 Non-Goals.

---

## Scope

- Convert `CrewAgentNode(_CoreAgentNode)` in `parrot/bots/flows/crew/nodes.py` from `@dataclass` to Pydantic `BaseModel` subclass (inherits frozen + arbitrary_types_allowed from the new `core.node.AgentNode`).
- Move the `_format_prompt(input_data)` logic into a `_build_prompt(self, ctx: FlowContext, deps: DependencyResults) -> str` override:
  - Inside `_build_prompt`, derive `input_data` by calling `ctx.get_input_for_agent(self.agent.name, self.dependencies)` (mirrors the old `execute_in_context` behavior).
  - Then format using the same logic the legacy `_format_prompt` used (task + dependency results concatenation).
- Remove the `execute_in_context(self, context, timeout=None)` method. Callers will now call `node.execute(ctx, deps)` directly, which internally calls `_build_prompt(ctx, deps)` and then `agent.ask(...)`. If `timeout` is needed by an existing caller, pass via `**kwargs` (verify usage sites in crew.py).
- Update the instantiation site at `parrot/bots/flows/crew/crew.py:223` (`self.workflow_graph[agent.name] = CrewAgentNode(...)`) if Pydantic constructor kwargs differ from the dataclass kwargs (they should not — both accept named fields). Verify by reading the surrounding context.
- Search the rest of `crew.py` and `nodes.py` for any direct calls to `execute_in_context` and migrate to `execute(ctx, deps)`.
- **Untouched**: every `node.fsm.<method>()` site in `crew.py` (12 lines listed above).

**NOT in scope**:
- `parrot/bots/orchestration/crew.py` and its `_CrewAgentNode` — entire `orchestration/` package on separate deletion track (spec non-goal).
- Reshaping `core.node` itself (TASK-1060 already done).
- Removing `SynthesisMixin` from `AgentCrew` (future spec).
- Adding `from_definition()` to `AgentCrew` (out of scope).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py` | MODIFY | Convert `CrewAgentNode` to Pydantic; replace `_format_prompt` + `execute_in_context` with `_build_prompt` override |
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY | Update instantiation at line 223; remove any `execute_in_context` callers if present |
| `packages/ai-parrot/tests/bots/flows/crew/test_nodes.py` | CREATE or MODIFY | Verify Pydantic construction + `_build_prompt` parity with legacy `_format_prompt` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations

from typing import Any, Dict, Optional

from ..core.node import AgentNode as _CoreAgentNode    # MODIFIED in TASK-1060 to Pydantic frozen
from ..core.context import FlowContext
from ..core.types import DependencyResults             # core/types.py:30
# Pydantic imports inherited via _CoreAgentNode's base; explicit imports only if subclass adds fields.
```

### Existing Signatures (CURRENT — to be replaced)

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py
@dataclass
class CrewAgentNode(_CoreAgentNode):
    def _format_prompt(self, input_data: Dict[str, Any]) -> str:
        """Format the input data dictionary into a string prompt."""
        ...

    async def execute_in_context(
        self, context: FlowContext, timeout: Optional[float] = None
    ) -> Any:
        """Execute the agent with context from previous agents."""
        input_data = context.get_input_for_agent(self.agent.name, self.dependencies)
        prompt = self._format_prompt(input_data)
        return await self.execute(prompt, timeout=timeout)
```

### Existing Signatures (AFTER TASK-1060 — what subclass inherits)

```python
# packages/ai-parrot/src/parrot/bots/flows/core/node.py (after TASK-1060)
class AgentNode(Node):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    agent: AgentLike
    node_id: str
    dependencies: set[str] = Field(default_factory=set)
    successors: set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def _build_prompt(self, ctx: FlowContext, deps: DependencyResults) -> str:
        return ctx.get_input_for_agent(self.agent.name, self.dependencies)

    async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs) -> Any:
        prompt = self._build_prompt(ctx, deps)
        # ...
```

### Caller sites in `crew.py` (DO NOT TOUCH `.fsm` lines)

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
# Line 223: instantiation
self.workflow_graph[agent.name] = CrewAgentNode(
    agent=agent,
    node_id=...,
    dependencies=...,
    successors=...,
)
# These KEYWORD args work for both @dataclass and Pydantic. Verify they're all listed
# and that no positional args are used.

# Lines 567-570, 586-587, 649-650, 1102-1104, 1202-1203, 1212-1213 — node.fsm.<method>():
#   UNCHANGED — FSM remains a field on the Pydantic node, .start()/.succeed()/.fail() still work.
```

### Does NOT Exist (after this task)

- ~~`CrewAgentNode._format_prompt`~~ — replaced by `_build_prompt`.
- ~~`CrewAgentNode.execute_in_context`~~ — removed; callers use `node.execute(ctx, deps)`.
- ~~`CrewAgentNode` as a dataclass~~ — now a Pydantic BaseModel subclass.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py
from typing import Any, Dict

from ..core.node import AgentNode as _CoreAgentNode
from ..core.context import FlowContext
from ..core.types import DependencyResults


class CrewAgentNode(_CoreAgentNode):
    """Crew-specific node wrapping an agent with dependency metadata.

    Overrides `_build_prompt` to apply crew-specific formatting that combines
    the task description with results from upstream agents.
    """

    def _build_prompt(self, ctx: FlowContext, deps: DependencyResults) -> str:
        """Build a crew-style prompt: task + context from upstream agents."""
        input_data = ctx.get_input_for_agent(self.agent.name, self.dependencies)
        return self._format(input_data)

    @staticmethod
    def _format(input_data: Dict[str, Any]) -> str:
        """Format input_data dict into a string prompt.

        (This is the renamed/private version of the legacy `_format_prompt`.)
        """
        if not input_data:
            return ""
        task = input_data.get("task", "")
        dependencies = input_data.get("dependencies", {})
        if not dependencies:
            return task
        parts = [f"Task: {task}\n", "\nContext from previous agents:\n"]
        for dep_agent, dep_result in dependencies.items():
            parts.extend((f"\n--- From {dep_agent} ---", str(dep_result), ""))
        return "\n".join(parts)
```

### Migration Steps in `crew.py`

1. `grep -n "execute_in_context\|_format_prompt" packages/ai-parrot/src/parrot/bots/flows/crew/` — list all call sites.
2. Replace `await node.execute_in_context(ctx, timeout=t)` with `await node.execute(ctx, deps_dict)` where `deps_dict` is the dependency results already accumulated by the AgentCrew scheduler. Pass `timeout=t` as a `**kwargs` keyword.
3. Confirm with `grep` that no `_format_prompt` callers remain outside the subclass.
4. **DO NOT** touch any `.fsm` access lines — they stay byte-for-byte identical.

### Key Constraints

- The `agent: AgentLike` field expects the agent object directly. AgentCrew already passes the resolved agent at line 223 — no change to argument values.
- Pydantic v2 dataclass-style subclassing of a `BaseModel` works without `@dataclass`. Just `class CrewAgentNode(_CoreAgentNode):` and add fields if any.
- If `CrewAgentNode` needs `__post_init__`-style setup, override `model_post_init(self, __context)` instead — Pydantic v2 hook (TASK-1060 sets the precedent).
- Existing `node.fsm.start()` etc. in `crew.py` work as-is because `.start()` is method-call mutation on a nested object, which Pydantic frozen permits.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py` — current shape.
- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:223, 567-650, 1102-1213` — call sites.
- TASK-1060 completed file in `sdd/tasks/completed/` — for the new core.node shape.

---

## Acceptance Criteria

- [ ] `CrewAgentNode` is a Pydantic `BaseModel` subclass (not `@dataclass`).
- [ ] `CrewAgentNode._build_prompt(ctx, deps)` exists and produces output identical to the legacy `_format_prompt(input_data)` for the same `input_data` (regression test: `test_crew_agent_node_build_prompt_override` — feed the same dict, compare strings).
- [ ] `CrewAgentNode.execute_in_context` no longer exists; `grep -n "execute_in_context" packages/ai-parrot/src/parrot/bots/flows/crew/` returns no results.
- [ ] All `.fsm` access sites in `crew.py` unchanged — verify with `git diff` that the lines listed in the Codebase Contract are untouched.
- [ ] Instantiation at `crew.py:223` still works with the new Pydantic constructor.
- [ ] All existing AgentCrew tests pass (regression check): `pytest packages/ai-parrot/tests/bots/flows/crew/ -v` (or wherever crew tests live — confirm at impl time).
- [ ] `parrot/bots/orchestration/` is untouched — `git diff` confirms no files in that path changed.
- [ ] No linting errors on the modified files.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/crew/test_nodes.py
import pytest

from parrot.bots.flows.crew.nodes import CrewAgentNode


class FakeAgent:
    name = "researcher"
    async def ask(self, question="", **kwargs): return f"echo: {question}"


class TestCrewAgentNode:
    def test_pydantic_construction(self):
        node = CrewAgentNode(
            agent=FakeAgent(),
            node_id="researcher-1",
            dependencies={"analyst"},
            successors={"writer"},
        )
        assert node.node_id == "researcher-1"
        assert node.dependencies == {"analyst"}

    def test_build_prompt_parity_no_deps(self):
        """`_build_prompt` with no dependencies returns the task verbatim — parity
        with the legacy `_format_prompt`."""
        node = CrewAgentNode(agent=FakeAgent(), node_id="r1")

        class StubCtx:
            def get_input_for_agent(self, name, deps):
                return {"task": "Research X", "dependencies": {}}

        result = node._build_prompt(StubCtx(), {})
        assert result == "Research X"

    def test_build_prompt_parity_with_deps(self):
        """`_build_prompt` formats task + dependency results — parity with legacy."""
        node = CrewAgentNode(agent=FakeAgent(), node_id="r1")

        class StubCtx:
            def get_input_for_agent(self, name, deps):
                return {
                    "task": "Summarize",
                    "dependencies": {"analyst": "data points"},
                }

        result = node._build_prompt(StubCtx(), {})
        assert "Task: Summarize" in result
        assert "--- From analyst ---" in result
        assert "data points" in result

    def test_no_execute_in_context_attribute(self):
        node = CrewAgentNode(agent=FakeAgent(), node_id="r1")
        assert not hasattr(node, "execute_in_context")
```

---

## Agent Instructions

1. Confirm TASK-1060 is in `sdd/tasks/completed/`.
2. Run AgentCrew tests BEFORE changing anything: capture the current pass/fail state so post-change regressions are unambiguous.
3. `grep -n "execute_in_context\|_format_prompt" packages/ai-parrot/src/parrot/bots/flows/crew/ packages/ai-parrot/src/parrot/bots/orchestration/` — note the call sites (orchestration/ is informational only — do NOT modify).
4. Read `nodes.py` end-to-end; verify the new Pydantic-base class is consistent with TASK-1060's output.
5. Implement the migration. Migrate any in-crew callers of `execute_in_context` to `node.execute(ctx, deps)`.
6. Run `pytest packages/ai-parrot/tests/bots/flows/crew/ -v` — all tests must pass.
7. Verify with `git diff packages/ai-parrot/src/parrot/bots/orchestration/` is empty.
8. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
