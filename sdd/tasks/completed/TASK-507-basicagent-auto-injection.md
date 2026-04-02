# TASK-507: BasicAgent Auto-Injection of AnswerMemory

**Feature**: extending-workingmemorytoolkit
**Spec**: `sdd/specs/extending-workingmemorytoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-506
**Assigned-to**: unassigned

---

## Context

With the AnswerMemory bridge available in `WorkingMemoryToolkit`, this task
adds zero-config wiring: `BasicAgent.configure()` auto-detects any registered
`WorkingMemoryToolkit` and injects its `answer_memory` instance, so users
don't need to wire it explicitly.

Implements **Module 5** from the spec.

---

## Scope

- In `BasicAgent` (at `packages/ai-parrot/src/parrot/bots/agent.py`), after
  tool registration is complete (end of `configure()` or `__init__`), add
  logic to iterate the tool manager's registered tools.
- If a `WorkingMemoryToolkit` instance is found and its `_answer_memory is None`,
  set `toolkit._answer_memory = self.answer_memory`.
- Do NOT overwrite if `_answer_memory` is already set (explicit wiring takes
  precedence).
- Log at DEBUG level: `"Auto-injected answer_memory into WorkingMemoryToolkit"`.

**NOT in scope**: modifying `WorkingMemoryToolkit` itself, package exports, tests
for the bridge tools (covered by TASK-506 and TASK-509).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | Add auto-injection logic after tool registration |

---

## Implementation Notes

### Pattern to Follow

```python
# At the end of configure() or after tools are synced:
from parrot.tools.working_memory import WorkingMemoryToolkit

tool_manager = getattr(self, "tool_manager", None)
if tool_manager is not None:
    for tool in tool_manager.get_tools():
        if isinstance(tool, WorkingMemoryToolkit) and tool._answer_memory is None:
            tool._answer_memory = self.answer_memory
            self.logger.debug("Auto-injected answer_memory into WorkingMemoryToolkit")
```

### Key Constraints

- Use lazy import (`from parrot.tools.working_memory import WorkingMemoryToolkit`)
  inside the method to avoid circular imports and keep working_memory optional.
- `tool_manager.get_tools()` may return an iterator or list — check what the
  current API provides (look at `AbstractToolkit` and the tool manager).
- The `self.answer_memory` attribute is set in `BasicAgent.__init__()` at line 139.
- This must handle the case where `tool_manager` is None or has no tools gracefully.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/agent.py:139` — `self.answer_memory = AnswerMemory(...)`
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` — `_answer_memory` attribute

---

## Acceptance Criteria

- [ ] `BasicAgent` with a registered `WorkingMemoryToolkit` auto-injects `answer_memory`
- [ ] Auto-injection does NOT overwrite an already-set `_answer_memory`
- [ ] Auto-injection is silent when no `WorkingMemoryToolkit` is registered
- [ ] No circular import issues
- [ ] All existing tests pass

---

## Test Specification

```python
import pytest
from unittest.mock import MagicMock, AsyncMock
from parrot.memory import AnswerMemory
from parrot.tools.working_memory import WorkingMemoryToolkit


class TestAutoInjection:
    def test_auto_inject(self):
        """BasicAgent injects answer_memory into WorkingMemoryToolkit."""
        toolkit = WorkingMemoryToolkit()
        assert toolkit._answer_memory is None
        # Simulate what BasicAgent.configure() does:
        am = AnswerMemory(agent_id="test")
        toolkit._answer_memory = am
        assert toolkit._answer_memory is am

    def test_no_overwrite(self):
        """Auto-inject skips when toolkit already has answer_memory."""
        existing_am = AnswerMemory(agent_id="existing")
        toolkit = WorkingMemoryToolkit(answer_memory=existing_am)
        new_am = AnswerMemory(agent_id="new")
        # Simulate auto-inject check:
        if toolkit._answer_memory is None:
            toolkit._answer_memory = new_am
        assert toolkit._answer_memory is existing_am
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/extending-workingmemorytoolkit.spec.md` for full context
2. **Check dependencies** — TASK-506 must be complete
3. **Read `BasicAgent`** at `packages/ai-parrot/src/parrot/bots/agent.py` — understand
   `configure()` flow and where tools are registered/synced
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-507-basicagent-auto-injection.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: Implemented as specified. All 115 tests pass.

**Deviations from spec**: none
