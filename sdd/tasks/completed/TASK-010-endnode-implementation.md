# TASK-010: EndNode Implementation

**Feature**: AgentsFlow Persistency
**Spec**: `sdd/specs/agentsflow-persistency.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: fdc88691-08f0-4537-968c-cbf4a40a46a6

---

## Context

> The spec requires `EndNode` to be a first-class citizen in the FSM, exactly like `StartNode`. This ensures explicit terminal states in persisted flows and makes JSON definitions clearer. Implements Module 6 from the spec.

---

## Scope

> Add `EndNode` as a dedicated node type alongside `StartNode`.

- Implement `EndNode` class in `parrot/bots/flow/nodes/__init__.py`
- `EndNode` should inherit from same base as `StartNode`
- `EndNode` has no outgoing transitions (terminal by definition)
- `EndNode.ask()` should pass through input unchanged (like `StartNode`)
- Update exports in `parrot/bots/flow/__init__.py`
- Write unit tests

**NOT in scope**:
- Modifying existing `AgentsFlow` logic (it already handles terminal nodes correctly)
- JSON serialization (TASK-009)
- Flow materialization (TASK-013)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/flow/nodes/__init__.py` | MODIFY | Add `EndNode` class |
| `parrot/bots/flow/__init__.py` | MODIFY | Export `EndNode` |
| `tests/test_endnode.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow existing StartNode pattern in parrot/bots/flow/nodes/__init__.py
class StartNode(AbstractBot):
    """Virtual node representing the entry point of a flow."""

    def __init__(self, name: str = "__start__", metadata: Optional[Dict[str, Any]] = None):
        super().__init__(name=name)
        self.metadata = metadata or {}

    async def ask(self, question: str = "", **kwargs) -> str:
        """Pass-through: returns the input unchanged."""
        return question

# EndNode follows same pattern
class EndNode(AbstractBot):
    """Virtual node representing the terminal point of a flow."""
    ...
```

### Key Constraints
- Must inherit from `AbstractBot` like `StartNode`
- Default name: `"__end__"`
- `ask()` returns input unchanged (pass-through)
- Should have `metadata` dict for optional annotations

### References in Codebase
- `parrot/bots/flow/nodes/__init__.py` — `StartNode` implementation
- `parrot/bots/flow/fsm.py:466-482` — `add_end_node()` method (already exists, uses `EndNode`)

---

## Acceptance Criteria

- [ ] `EndNode` class created with same interface as `StartNode`
- [ ] `EndNode` exported from `parrot.bots.flow`
- [ ] `EndNode.ask()` passes input through unchanged
- [ ] All tests pass: `pytest tests/test_endnode.py -v`
- [ ] Import works: `from parrot.bots.flow import EndNode`

---

## Test Specification

```python
# tests/test_endnode.py
import pytest
from parrot.bots.flow import EndNode, StartNode


class TestEndNode:
    def test_default_name(self):
        """EndNode has default name __end__."""
        node = EndNode()
        assert node.name == "__end__"

    def test_custom_name(self):
        """EndNode accepts custom name."""
        node = EndNode(name="my_end")
        assert node.name == "my_end"

    def test_metadata(self):
        """EndNode stores metadata."""
        node = EndNode(metadata={"label": "Final Output"})
        assert node.metadata["label"] == "Final Output"

    @pytest.mark.asyncio
    async def test_ask_passthrough(self):
        """EndNode.ask() returns input unchanged."""
        node = EndNode()
        result = await node.ask("Final result text")
        assert result == "Final result text"

    def test_same_interface_as_startnode(self):
        """EndNode has same interface as StartNode."""
        end = EndNode(name="end", metadata={"k": "v"})
        start = StartNode(name="start", metadata={"k": "v"})

        # Same attributes
        assert hasattr(end, "name")
        assert hasattr(end, "metadata")
        assert hasattr(end, "ask")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-persistency.spec.md` Section 7 (Open Questions - EndNode)
2. **Check dependencies** — this task has no dependencies
3. **Read existing code** at `parrot/bots/flow/nodes/__init__.py` for `StartNode` pattern
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-010-endnode-implementation.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: fdc88691-08f0-4537-968c-cbf4a40a46a6
**Date**: 2026-02-22
**Notes**: EndNode was already fully implemented in `parrot/bots/flow/nodes/end.py` with correct exports. Created 15 unit tests covering construction, passthrough, pre/post actions, FSM integration, and public imports.

**Deviations from spec**: none — implementation follows StartNode pattern exactly as specified.
