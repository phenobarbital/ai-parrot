# TASK-013: Flow Loader

**Feature**: AgentsFlow Persistency
**Spec**: `sdd/specs/agentsflow-persistency.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-009, TASK-010, TASK-011, TASK-012
**Assigned-to**: antigravity-session

---

## Context

> This is the central integration point for AgentsFlow Persistency. `FlowLoader` handles all persistence (file/Redis) and materialization (JSON → runnable `AgentsFlow`). It combines all prior modules into a cohesive API. Implements Module 4 from the spec.

---

## Scope

> Implement `FlowLoader` with file I/O, Redis I/O, and `to_agents_flow()` materialization.

- Implement `FlowLoader.from_dict()` and `from_json()` constructors
- Implement `load_from_file()` — load from path or `AGENTS_DIR/flows/` default
- Implement `save_to_file()` — persist with timestamp update
- Implement `load_from_redis()` — async Redis load with `parrot:flow:` key prefix
- Implement `save_to_redis()` — async Redis save with optional TTL
- Implement `list_flows_in_redis()` and `delete_from_redis()` helpers
- Implement `to_agents_flow()` — materialize into runnable `AgentsFlow`:
  - Build nodes from `NodeDefinition`
  - Wire edges as `FlowTransition` with CEL predicates
  - Attach pre/post actions from `ACTION_REGISTRY`
  - Resolve agent references from registry or `extra_agents`
- Write integration tests

**NOT in scope**:
- SvelteFlow conversion (TASK-014)
- Modifying `AgentsFlow` internals

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/flow/loader.py` | CREATE | FlowLoader implementation |
| `parrot/bots/flow/__init__.py` | MODIFY | Export `FlowLoader` |
| `tests/test_flow_loader.py` | CREATE | Unit and integration tests |
| `tests/fixtures/flows/` | CREATE | Test flow JSON files |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/bots/flow/loader.py
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .definition import FlowDefinition, NodeDefinition, EdgeDefinition
from .cel_evaluator import CELPredicateEvaluator
from .actions import ACTION_REGISTRY
from .fsm import AgentsFlow, TransitionCondition
from .nodes import StartNode, EndNode


REDIS_KEY_PREFIX = "parrot:flow:"


class FlowLoader:
    """Load, save, and materialize FlowDefinition instances."""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FlowDefinition:
        return FlowDefinition.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> FlowDefinition:
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def load_from_file(cls, path: Union[str, Path]) -> FlowDefinition:
        """Load from file path or AGENTS_DIR/flows/{name}.json."""
        path = Path(path)

        # If not absolute and not existing, try AGENTS_DIR/flows/
        if not path.is_absolute() and not path.exists():
            from parrot.conf import AGENTS_DIR
            path = AGENTS_DIR / "flows" / path
            if not path.suffix:
                path = path.with_suffix(".json")

        if not path.exists():
            raise FileNotFoundError(f"Flow file not found: {path}")

        return cls.from_json(path.read_text(encoding="utf-8"))

    @classmethod
    def to_agents_flow(
        cls,
        definition: FlowDefinition,
        agent_registry: Optional[Any] = None,
        extra_agents: Optional[Dict[str, Any]] = None,
    ) -> AgentsFlow:
        """Materialize FlowDefinition into runnable AgentsFlow."""
        meta = definition.metadata
        extra_agents = extra_agents or {}

        flow = AgentsFlow(
            name=definition.flow,
            max_parallel_tasks=meta.max_parallel_tasks,
            default_max_retries=meta.default_max_retries,
            execution_timeout=meta.execution_timeout,
            # ... other metadata fields
        )

        node_map: Dict[str, Any] = {}

        # Build nodes
        for node_def in definition.nodes:
            flow_node = cls._build_node(node_def, flow, agent_registry, extra_agents)
            node_map[node_def.id] = flow_node

        # Wire edges
        for edge_def in definition.edges:
            cls._wire_edge(edge_def, node_map, flow)

        return flow
```

### Key Constraints
- Redis keys follow pattern: `parrot:flow:{flow_name}`
- Use `AGENTS_DIR` from `parrot.conf` for default file location
- `to_agents_flow()` must resolve `agent_ref` from `extra_agents` first, then `agent_registry`
- CEL predicates compiled via `CELPredicateEvaluator`
- Actions resolved from `ACTION_REGISTRY` and attached via `Node.add_pre_action()`
- Fan-in edges: explicit per spec (all sources must complete)

### References in Codebase
- `parrot/bots/orchestration/crew.py` — Redis persistence patterns
- `parrot/bots/flow/fsm.py` — `AgentsFlow`, `task_flow()` API
- `parrot/conf.py` — `AGENTS_DIR`, `REDIS_URL` configuration

---

## Acceptance Criteria

- [ ] `FlowLoader.from_dict()` and `from_json()` parse valid definitions
- [ ] `load_from_file()` loads from path or `AGENTS_DIR/flows/`
- [ ] `save_to_file()` persists JSON with `updated_at` timestamp
- [ ] `load_from_redis()` / `save_to_redis()` work with async Redis client
- [ ] `to_agents_flow()` produces runnable `AgentsFlow`
- [ ] CEL predicates attached to `ON_CONDITION` transitions
- [ ] Actions resolved from registry and attached to nodes
- [ ] Unknown agent references raise `LookupError`
- [ ] All tests pass: `pytest tests/test_flow_loader.py -v`
- [ ] Import works: `from parrot.bots.flow import FlowLoader`

---

## Test Specification

```python
# tests/test_flow_loader.py
import pytest
import json
from pathlib import Path
from parrot.bots.flow.loader import FlowLoader
from parrot.bots.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition
from parrot.bots.flow import AgentsFlow


@pytest.fixture
def simple_flow_json():
    return json.dumps({
        "flow": "TestFlow",
        "version": "1.0",
        "nodes": [
            {"id": "__start__", "type": "start"},
            {"id": "worker", "type": "agent", "agent_ref": "echo_agent"},
            {"id": "__end__", "type": "end"}
        ],
        "edges": [
            {"from": "__start__", "to": "worker", "condition": "always"},
            {"from": "worker", "to": "__end__", "condition": "on_success"}
        ]
    })


@pytest.fixture
def echo_agent():
    """Mock agent that echoes input."""
    from parrot.bots.agent import BasicAgent

    class EchoAgent(BasicAgent):
        async def ask(self, question: str, **kwargs):
            return question

    return EchoAgent(name="echo_agent")


class TestFlowLoaderParsing:
    def test_from_json(self, simple_flow_json):
        """Parse valid JSON into FlowDefinition."""
        definition = FlowLoader.from_json(simple_flow_json)
        assert definition.flow == "TestFlow"
        assert len(definition.nodes) == 3
        assert len(definition.edges) == 2

    def test_from_dict(self):
        """Parse valid dict into FlowDefinition."""
        data = {
            "flow": "Test",
            "nodes": [{"id": "a", "type": "start"}],
            "edges": []
        }
        definition = FlowLoader.from_dict(data)
        assert definition.flow == "Test"


class TestFileIO:
    def test_load_from_file(self, tmp_path, simple_flow_json):
        """Load flow from file path."""
        flow_file = tmp_path / "test_flow.json"
        flow_file.write_text(simple_flow_json)

        definition = FlowLoader.load_from_file(flow_file)
        assert definition.flow == "TestFlow"

    def test_save_to_file(self, tmp_path):
        """Save flow to file with timestamp."""
        definition = FlowDefinition(
            flow="SaveTest",
            nodes=[NodeDefinition(id="a", type="start")],
            edges=[]
        )

        flow_file = tmp_path / "saved.json"
        FlowLoader.save_to_file(definition, flow_file)

        assert flow_file.exists()
        loaded = FlowLoader.load_from_file(flow_file)
        assert loaded.flow == "SaveTest"
        assert loaded.updated_at is not None

    def test_file_not_found(self):
        """Raise error for missing file."""
        with pytest.raises(FileNotFoundError):
            FlowLoader.load_from_file("/nonexistent/path.json")


class TestRedisIO:
    @pytest.mark.asyncio
    async def test_save_and_load_redis(self, mock_redis):
        """Save and load flow from Redis."""
        definition = FlowDefinition(
            flow="RedisTest",
            nodes=[NodeDefinition(id="a", type="start")],
            edges=[]
        )

        await FlowLoader.save_to_redis(mock_redis, definition)
        loaded = await FlowLoader.load_from_redis(mock_redis, "RedisTest")

        assert loaded.flow == "RedisTest"

    @pytest.mark.asyncio
    async def test_list_flows(self, mock_redis):
        """List all flows in Redis."""
        d1 = FlowDefinition(flow="Flow1", nodes=[], edges=[])
        d2 = FlowDefinition(flow="Flow2", nodes=[], edges=[])

        await FlowLoader.save_to_redis(mock_redis, d1)
        await FlowLoader.save_to_redis(mock_redis, d2)

        flows = await FlowLoader.list_flows_in_redis(mock_redis)
        assert "Flow1" in flows
        assert "Flow2" in flows


class TestMaterialization:
    def test_to_agents_flow(self, simple_flow_json, echo_agent):
        """Materialize definition into runnable AgentsFlow."""
        definition = FlowLoader.from_json(simple_flow_json)

        flow = FlowLoader.to_agents_flow(
            definition,
            extra_agents={"echo_agent": echo_agent}
        )

        assert isinstance(flow, AgentsFlow)
        assert flow.name == "TestFlow"
        assert "__start__" in flow.nodes
        assert "worker" in flow.nodes
        assert "__end__" in flow.nodes

    def test_cel_predicate_wired(self, echo_agent):
        """CEL predicates attached to transitions."""
        definition = FlowDefinition(
            flow="CELTest",
            nodes=[
                NodeDefinition(id="a", type="agent", agent_ref="echo_agent"),
                NodeDefinition(id="b", type="agent", agent_ref="echo_agent"),
            ],
            edges=[
                EdgeDefinition(**{
                    "from": "a",
                    "to": "b",
                    "condition": "on_condition",
                    "predicate": 'result == "yes"'
                })
            ]
        )

        flow = FlowLoader.to_agents_flow(
            definition,
            extra_agents={"echo_agent": echo_agent}
        )

        # Check transition has CEL predicate
        node_a = flow.nodes["a"]
        assert len(node_a.outgoing_transitions) == 1
        assert node_a.outgoing_transitions[0].predicate is not None

    def test_missing_agent_raises(self, simple_flow_json):
        """Raise error when agent_ref not found."""
        definition = FlowLoader.from_json(simple_flow_json)

        with pytest.raises(LookupError, match="echo_agent"):
            FlowLoader.to_agents_flow(definition)  # No agents provided

    @pytest.mark.asyncio
    async def test_full_execution(self, simple_flow_json, echo_agent):
        """Load, materialize, and run flow end-to-end."""
        definition = FlowLoader.from_json(simple_flow_json)
        flow = FlowLoader.to_agents_flow(
            definition,
            extra_agents={"echo_agent": echo_agent}
        )

        result = await flow.run_flow("Hello world")
        assert result.status in ["completed", "partial"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-persistency.spec.md` Section 2 (Public Interfaces)
2. **Check dependencies** — verify TASK-009, 010, 011, 012 are complete
3. **Read existing code**:
   - `parrot/bots/flow/fsm.py` — `AgentsFlow` API
   - `parrot/bots/orchestration/crew.py` — Redis patterns
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Create test fixtures** in `tests/fixtures/flows/`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-013-flow-loader.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Completed)*

**Completed by**: antigravity-session
**Date**: 2026-02-22
**Notes**:
- Created `parrot/bots/flow/loader.py` (~290 lines) with full FlowLoader implementation
- File I/O: `load_from_file()` with AGENTS_DIR fallback, `save_to_file()` with timestamp update and auto-directory creation
- Redis I/O: `save_to_redis()` / `load_from_redis()` with `parrot:flow:` prefix, `list_flows_in_redis()` via scan_iter, `delete_from_redis()`
- Materialization: `to_agents_flow()` builds nodes (start, end, agent, decision, interactive_decision), wires edges with CEL predicates, attaches pre/post actions from ACTION_REGISTRY
- Agent resolution: extra_agents takes priority over agent_registry (dict-like or object with `.get()`)
- Uses `redis.asyncio` per project convention (not legacy `aioredis`)
- 23 tests pass covering parsing, file I/O, Redis I/O (in-memory mock), materialization, action attachment, CEL predicate wiring, agent resolution priority, fan-out edges, and end-to-end execution
- Test fixtures created in `tests/fixtures/flows/` (simple_flow.json, cel_decision_flow.json)
- `FlowLoader` exported from `parrot.bots.flow.__init__`

**Deviations from spec**:
- Used `redis.asyncio.Redis` type hints (as `Any`) instead of `aioredis.Redis` to match project convention
- Redis tests use in-memory `_MockRedis` instead of `fakeredis` (not in project deps)
