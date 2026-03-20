# TASK-009: Flow Definition Pydantic Models

**Feature**: AgentsFlow Persistency
**Spec**: `sdd/specs/agentsflow-persistency.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> This is the foundational task for AgentsFlow Persistency. All other modules depend on these Pydantic models for validation and serialization. Implements Module 1 from the spec.

---

## Scope

> Create the complete Pydantic model hierarchy for `FlowDefinition`.

- Implement all action definition models: `LogActionDef`, `NotifyActionDef`, `WebhookActionDef`, `MetricActionDef`, `SetContextActionDef`, `ValidateActionDef`, `TransformActionDef`
- Implement `ActionDefinition` discriminated union type
- Implement `NodePosition`, `NodeDefinition` with validation (agent nodes require `agent_ref`)
- Implement `EdgeDefinition` with validation (`on_condition` requires `predicate`)
- Implement `FlowMetadata` with sensible defaults
- Implement `FlowDefinition` root model with node ID validation
- Write unit tests for all validation rules

**NOT in scope**:
- Action implementation classes (TASK-011)
- CEL predicate evaluation (TASK-012)
- File/Redis persistence (TASK-013)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/flow/definition.py` | CREATE | All Pydantic models |
| `parrot/bots/flow/__init__.py` | MODIFY | Export `FlowDefinition`, `NodeDefinition`, `EdgeDefinition` |
| `tests/test_flow_definition.py` | CREATE | Unit tests for validation |

---

## Implementation Notes

### Pattern to Follow
```python
# Use Pydantic v2 patterns from existing codebase
from pydantic import BaseModel, Field, model_validator
from typing import Literal, Union, Optional

class ActionDef(BaseModel):
    type: Literal["action_type"] = "action_type"
    # fields with descriptions for schema generation
    field: str = Field(..., description="What this field does")

# Discriminated union for action types
ActionDefinition = Union[LogActionDef, NotifyActionDef, ...]
```

### Key Constraints
- Use `model_config = {"populate_by_name": True}` for `EdgeDefinition` (handles `from` → `from_`)
- Use `Field(alias="schema")` for `ValidateActionDef.schema_` (avoid Python keyword)
- All node types: `start`, `end`, `agent`, `decision`, `interactive_decision`, `human`
- All condition types: `always`, `on_success`, `on_error`, `on_timeout`, `on_condition`

### References in Codebase
- `parrot/models/crew.py` — Pydantic model patterns
- `parrot/bots/flow/fsm.py` — `TransitionCondition` enum for condition values

---

## Acceptance Criteria

- [ ] All Pydantic models created and validated
- [ ] `NodeDefinition` with `type="agent"` requires `agent_ref`
- [ ] `EdgeDefinition` with `condition="on_condition"` requires `predicate`
- [ ] `FlowDefinition` validates all edge references point to existing node IDs
- [ ] All tests pass: `pytest tests/test_flow_definition.py -v`
- [ ] Models serialize to JSON correctly: `definition.model_dump_json(by_alias=True)`
- [ ] Import works: `from parrot.bots.flow import FlowDefinition`

---

## Test Specification

```python
# tests/test_flow_definition.py
import pytest
from pydantic import ValidationError
from parrot.bots.flow.definition import (
    FlowDefinition, NodeDefinition, EdgeDefinition,
    FlowMetadata, LogActionDef, ActionDefinition
)


class TestNodeDefinition:
    def test_agent_node_requires_agent_ref(self):
        """Agent nodes must have agent_ref."""
        with pytest.raises(ValidationError, match="agent_ref"):
            NodeDefinition(id="test", type="agent")

    def test_start_node_no_agent_ref(self):
        """Start nodes don't require agent_ref."""
        node = NodeDefinition(id="__start__", type="start")
        assert node.agent_ref is None

    def test_node_with_actions(self):
        """Nodes can have pre/post actions."""
        node = NodeDefinition(
            id="worker",
            type="agent",
            agent_ref="my_agent",
            pre_actions=[{"type": "log", "level": "info", "message": "Starting"}]
        )
        assert len(node.pre_actions) == 1
        assert node.pre_actions[0].type == "log"


class TestEdgeDefinition:
    def test_on_condition_requires_predicate(self):
        """on_condition edges must have predicate."""
        with pytest.raises(ValidationError, match="predicate"):
            EdgeDefinition(**{"from": "a", "to": "b", "condition": "on_condition"})

    def test_on_success_no_predicate(self):
        """on_success edges don't require predicate."""
        edge = EdgeDefinition(**{"from": "a", "to": "b", "condition": "on_success"})
        assert edge.predicate is None

    def test_edge_fan_out(self):
        """Edge can target multiple nodes."""
        edge = EdgeDefinition(**{"from": "a", "to": ["b", "c"]})
        assert edge.to == ["b", "c"]


class TestFlowDefinition:
    def test_valid_flow(self):
        """Complete valid flow parses successfully."""
        flow = FlowDefinition(
            flow="TestFlow",
            nodes=[
                NodeDefinition(id="start", type="start"),
                NodeDefinition(id="worker", type="agent", agent_ref="echo"),
                NodeDefinition(id="end", type="end"),
            ],
            edges=[
                EdgeDefinition(**{"from": "start", "to": "worker", "condition": "always"}),
                EdgeDefinition(**{"from": "worker", "to": "end", "condition": "on_success"}),
            ]
        )
        assert flow.flow == "TestFlow"

    def test_edge_references_unknown_node(self):
        """Edge referencing unknown node raises error."""
        with pytest.raises(ValidationError, match="unknown node"):
            FlowDefinition(
                flow="BadFlow",
                nodes=[NodeDefinition(id="a", type="start")],
                edges=[EdgeDefinition(**{"from": "a", "to": "nonexistent"})]
            )

    def test_json_serialization(self):
        """Flow serializes to JSON with aliases."""
        flow = FlowDefinition(
            flow="Test",
            nodes=[NodeDefinition(id="a", type="start")],
            edges=[EdgeDefinition(**{"from": "a", "to": "a", "condition": "always"})]
        )
        json_str = flow.model_dump_json(by_alias=True)
        assert '"from": "a"' in json_str  # alias applied


class TestActionDefinitions:
    def test_log_action(self):
        """Log action parses correctly."""
        action = LogActionDef(level="debug", message="Test {node_name}")
        assert action.type == "log"

    def test_webhook_action_defaults(self):
        """Webhook action has correct defaults."""
        from parrot.bots.flow.definition import WebhookActionDef
        action = WebhookActionDef(url="https://example.com/hook")
        assert action.method == "POST"
        assert action.headers == {}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-persistency.spec.md` Section 2 (Data Models)
2. **Check dependencies** — this task has no dependencies, can start immediately
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-009-flow-definition-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-22
**Notes**:
- Created `parrot/bots/flow/definition.py` with all Pydantic models
- Implemented 7 action definition models (Log, Notify, Webhook, Metric, SetContext, Validate, Transform)
- Implemented NodeDefinition with validation (agent type requires agent_ref)
- Implemented EdgeDefinition with validation (on_condition requires predicate)
- Implemented FlowDefinition with edge reference validation
- Updated `parrot/bots/flow/__init__.py` to export all new models
- Created 56 unit tests in `tests/test_flow_definition.py` - all passing

**Deviations from spec**: none
