---
type: Wiki Overview
title: 'TASK-1061: Add AgentCrew.from_definition() classmethod'
id: doc:sdd-tasks-completed-task-1061-agentcrew-from-definition-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: and `BotManager._create_crew_from_definition()`. This task adds a
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.models.crew_definition
  rel: mentions
---

# TASK-1061: Add AgentCrew.from_definition() classmethod

**Feature**: FEAT-156 — AgentCrew.from_definition classmethod
**Spec**: `sdd/proposals/agentcrew-from-definition.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1060
**Assigned-to**: unassigned

---

## Context

`AgentCrew` has no factory methods. The logic to create an `AgentCrew` from a
`CrewDefinition` is duplicated in `CrewHandler._create_crew_from_definition()`
and `BotManager._create_crew_from_definition()`. This task adds a
`@classmethod from_definition()` directly on `AgentCrew` that accepts resolver
callables for class and tool resolution, making it usable from any context
without coupling to a specific manager.

---

## Scope

- Add `AgentCrew.from_definition(cls, crew_def, *, class_resolver, tool_resolver)` as a
  `@classmethod` on `AgentCrew`.
- `class_resolver: Callable[[str], Optional[Type]]` — resolves agent class name to class.
- `tool_resolver: Optional[Callable[[str], Optional[AbstractTool]]] = None` — resolves
  shared tool name to tool instance. Defaults to `None` (skip shared tool resolution).
- The method must:
  1. Iterate `crew_def.agents`, resolve each agent class via `class_resolver`.
  2. Instantiate each agent with `name`, `tools`, `system_prompt`, and `**config`.
  3. Create the `AgentCrew` with `name`, `agents`, `max_parallel_tasks`.
  4. Add shared tools via `tool_resolver` (if provided).
  5. Set up flow relations if `execution_mode == ExecutionMode.FLOW`.
  6. Return the configured `AgentCrew`.
- Add a `@staticmethod _resolve_agents_by_ids(agents_dict, agent_ids)` helper for
  looking up agents by ID in the crew's `self.agents` dict.
- Fallback to `BasicAgent` when `class_resolver` returns `None`.

**NOT in scope**:
- `to_definition()` serialization (follow-up feature).
- Modifying the execution methods (`run_sequential`, etc.).
- Changing the `AgentCrew.__init__` signature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | MODIFY | Add `from_definition` classmethod and `_resolve_agents_by_ids` static helper |
| `tests/unit/test_agentcrew_from_definition.py` | CREATE | Unit tests for the new factory method |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/bots/orchestration/crew.py:28
from ..agent import BasicAgent

# packages/ai-parrot/src/parrot/bots/orchestration/crew.py:29
from ..abstract import AbstractBot

# packages/ai-parrot/src/parrot/bots/orchestration/crew.py:35
from ...tools.abstract import AbstractTool

# After TASK-1060 relocates models:
from parrot.models.crew_definition import CrewDefinition, AgentDefinition, FlowRelation, ExecutionMode
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/orchestration/crew.py:148
class AgentCrew(PersistenceMixin, SynthesisMixin):
    # line 187
    def __init__(
        self,
        name: str = "AgentCrew",
        agents: List[Union[BasicAgent, AbstractBot]] = None,
        shared_tool_manager: ToolManager = None,
        max_parallel_tasks: int = 10,
        llm: Optional[Union[str, AbstractClient]] = None,
        auto_configure: bool = True,
        ...
        **kwargs
    ):

    # line 328
    def add_agent(self, agent: Union[BasicAgent, AbstractBot], agent_id: str = None) -> None:

    # line 399
    def add_shared_tool(self, tool: AbstractTool, tool_name: str = None) -> None:

    # line 549
    def task_flow(self, source_agent: Any, target_agents: Any):

    # self.agents is Dict[str, Union[BasicAgent, AbstractBot]] — keyed by name (line 216)
```

### Does NOT Exist
- ~~`AgentCrew.from_definition`~~ — does not exist yet (this task creates it)
- ~~`AgentCrew.from_config`~~ — no such method
- ~~`AgentCrew.from_dict`~~ — no such method
- ~~`AgentCrew._resolve_agents_by_ids`~~ — does not exist yet (this task creates it)
- ~~`AgentCrew.to_definition`~~ — not in scope

---

## Implementation Notes

### Pattern to Follow
```python
# Place the classmethod after __init__ and before add_agent (around line 325)
@classmethod
def from_definition(
    cls,
    crew_def: "CrewDefinition",
    *,
    class_resolver: Callable[[str], Optional[type]],
    tool_resolver: Optional[Callable[[str], Optional["AbstractTool"]]] = None,
    **kwargs,
) -> "AgentCrew":
    agents = []
    for agent_def in crew_def.agents:
        agent_class = class_resolver(agent_def.agent_class)
        if agent_class is None:
            agent_class = BasicAgent
        agent = agent_class(
            name=agent_def.name or agent_def.agent_id,
            tools=list(agent_def.tools),
            **agent_def.config,
        )
        if agent_def.system_prompt:
            agent.system_prompt = agent_def.system_prompt
        agents.append(agent)

    crew = cls(
        name=crew_def.name,
        agents=agents,
        max_parallel_tasks=crew_def.max_parallel_tasks,
        **kwargs,
    )

    if tool_resolver:
        for tool_name in crew_def.shared_tools:
            if tool := tool_resolver(tool_name):
                crew.add_shared_tool(tool, tool_name)

    if crew_def.execution_mode == ExecutionMode.FLOW and crew_def.flow_relations:
        for relation in crew_def.flow_relations:
            source_ids = relation.source if isinstance(relation.source, list) else [relation.source]
            target_ids = relation.target if isinstance(relation.target, list) else [relation.target]
            source_agents = cls._resolve_agents_by_ids(crew.agents, source_ids)
            target_agents = cls._resolve_agents_by_ids(crew.agents, target_ids)
            if source_agents and target_agents:
                crew.task_flow(
                    source_agents if len(source_agents) > 1 else source_agents[0],
                    target_agents if len(target_agents) > 1 else target_agents[0],
                )
    return crew
```

### Key Constraints
- Import `CrewDefinition` and `ExecutionMode` with `TYPE_CHECKING` guard to avoid
  circular imports at runtime. Use string annotations in the method signature.
- The method is sync (agent constructors are sync; tool resolution is sync).
- Pass `**kwargs` through to `cls()` to allow callers to set `llm`, `auto_configure`, etc.
- Use `add_agent()` indirectly through the `agents` constructor param (which triggers
  `add_agent` internally in `__init__`), NOT by calling `add_agent()` in a loop after
  creation — this matches the existing pattern.

### References in Codebase
- `handlers/crew/handler.py:76-158` — logic being consolidated (duplicate 1)
- `manager/manager.py:2050-2144` — logic being consolidated (duplicate 2)
- `manager/manager.py:172-213` — `get_bot_class()` (example class_resolver)

---

## Acceptance Criteria

- [ ] `AgentCrew.from_definition(crew_def, class_resolver=resolver)` returns a valid `AgentCrew`
- [ ] Agents are created with correct names, tools, config, and system_prompt
- [ ] Shared tools are added when `tool_resolver` is provided
- [ ] Flow relations are wired when `execution_mode == FLOW`
- [ ] Falls back to `BasicAgent` when `class_resolver` returns `None`
- [ ] Extra `**kwargs` are forwarded to `AgentCrew.__init__`
- [ ] All tests pass: `pytest tests/unit/test_agentcrew_from_definition.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/orchestration/crew.py`

---

## Test Specification

```python
# tests/unit/test_agentcrew_from_definition.py
import pytest
from unittest.mock import MagicMock
from parrot.models.crew_definition import (
    CrewDefinition, AgentDefinition, FlowRelation, ExecutionMode
)
from parrot.bots.orchestration.crew import AgentCrew
from parrot.bots.agent import BasicAgent


def make_crew_def(**overrides):
    defaults = dict(
        name="test-crew",
        agents=[
            AgentDefinition(agent_id="agent-1", name="Agent One"),
            AgentDefinition(agent_id="agent-2", name="Agent Two"),
        ],
    )
    defaults.update(overrides)
    return CrewDefinition(**defaults)


def dummy_resolver(class_name: str):
    return BasicAgent


class TestFromDefinition:
    def test_basic_creation(self):
        crew_def = make_crew_def()
        crew = AgentCrew.from_definition(crew_def, class_resolver=dummy_resolver)
        assert crew.name == "test-crew"
        assert len(crew.agents) == 2

    def test_agent_names(self):
        crew_def = make_crew_def()
        crew = AgentCrew.from_definition(crew_def, class_resolver=dummy_resolver)
        assert "Agent One" in crew.agents
        assert "Agent Two" in crew.agents

    def test_fallback_to_basic_agent(self):
        crew_def = make_crew_def()
        crew = AgentCrew.from_definition(
            crew_def,
            class_resolver=lambda _: None,
        )
        assert len(crew.agents) == 2

    def test_system_prompt_set(self):
        crew_def = make_crew_def(
            agents=[AgentDefinition(
                agent_id="a1", name="A1",
                system_prompt="You are helpful."
            )]
        )
        crew = AgentCrew.from_definition(crew_def, class_resolver=dummy_resolver)
        agent = crew.agents["A1"]
        assert agent.system_prompt == "You are helpful."

    def test_shared_tools_resolved(self):
        mock_tool = MagicMock()
        mock_tool.name = "search"
        crew_def = make_crew_def(shared_tools=["search"])
        crew = AgentCrew.from_definition(
            crew_def,
            class_resolver=dummy_resolver,
            tool_resolver=lambda name: mock_tool if name == "search" else None,
        )
        assert crew.shared_tool_manager.get_tool("search") is not None

    def test_no_tool_resolver_skips_shared_tools(self):
        crew_def = make_crew_def(shared_tools=["search"])
        crew = AgentCrew.from_definition(crew_def, class_resolver=dummy_resolver)
        assert crew.shared_tool_manager.get_tool("search") is None

    def test_kwargs_forwarded(self):
        crew_def = make_crew_def()
        crew = AgentCrew.from_definition(
            crew_def,
            class_resolver=dummy_resolver,
            max_parallel_tasks=5,
        )
        # max_parallel_tasks from crew_def is used, but extra kwargs get forwarded
        assert crew is not None

    def test_flow_relations(self):
        crew_def = make_crew_def(
            execution_mode=ExecutionMode.FLOW,
            flow_relations=[
                FlowRelation(source="Agent One", target="Agent Two")
            ],
        )
        crew = AgentCrew.from_definition(crew_def, class_resolver=dummy_resolver)
        assert "Agent One" in crew.workflow_graph

    def test_resolve_agents_by_ids(self):
        agents = {"a1": MagicMock(), "a2": MagicMock()}
        result = AgentCrew._resolve_agents_by_ids(agents, ["a1", "a2"])
        assert len(result) == 2

    def test_resolve_agents_by_ids_missing(self):
        agents = {"a1": MagicMock()}
        result = AgentCrew._resolve_agents_by_ids(agents, ["a1", "missing"])
        assert len(result) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1060 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm all imports and signatures
4. **Update status** in `sdd/tasks/index/FEAT-156.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1061-agentcrew-from-definition.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-11
**Notes**: Added `AgentCrew.from_definition()` classmethod and `AgentCrew._resolve_agents_by_ids()`
static method to `packages/ai-parrot/src/parrot/bots/orchestration/crew.py`. The classmethod is
inserted between `__init__` and `add_agent` (around line 330). `TYPE_CHECKING` guard was added
to the typing imports, with `CrewDefinition` and `ExecutionMode` imported under it to avoid
circular imports. `ExecutionMode` is also imported inside the method body at call-time. Added
`max_parallel_tasks` pop logic so callers can override via **kwargs without conflict.
All 11 unit tests pass.

**Deviations from spec**: Minor — added `max_parallel_tasks` pop from kwargs so callers can
override it (test_kwargs_forwarded required it). The spec test used `MagicMock()` for shared tools
but ToolManager rejects non-AbstractTool objects; updated test to use `create_autospec(AbstractTool)`.
