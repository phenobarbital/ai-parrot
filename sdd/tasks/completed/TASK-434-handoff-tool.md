# TASK-434: Implement HandoffTool & Exception

**Feature**: Handoff Tool for Integrations Agents
**Spec**: `sdd/specs/handoff-tool-for-integrations-agents.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: jesuslara

---

## Context

> Foundation task for FEAT-045. Defines the `HandoffTool` tool and the `HumanInteractionInterrupt` exception that will be raised when an agent needs human input to continue solving a complex task.
> Implements spec Section 3.1.

---

## Scope

- Add `HumanInteractionInterrupt` custom exception to `parrot/core/exceptions.py` or create the file if needed.
- Implement `HandoffTool` in `parrot/core/tools/handoff.py`.
- The tool needs one required input: `prompt` (string).
- The `_run` (synchronous) and `_arun` (asynchronous) methods of the tool should both simply raise the `HumanInteractionInterrupt` exception, passing the `prompt` as the exception message.
- Ensure the `HandoffTool` is properly exported and discoverable.

**NOT in scope**: Catching the exception in the orchestrator (TASK-052).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/core/exceptions.py` | MODIFY/CREATE | Add `HumanInteractionInterrupt` class |
| `parrot/core/tools/handoff.py` | CREATE | Create the `HandoffTool` class inherited from `BaseTool` |

---

## Implementation Notes

### Key Constraints
- Provide a clear, robust docstring for `HandoffTool` describing its purpose, so the LLM uses it appropriately.
- The exception should hold the prompt payload so upper layers can retrieve it without string parsing.

---

## Acceptance Criteria

- [ ] `HumanInteractionInterrupt` exception is defined and can store a prompt text.
- [ ] `HandoffTool` subclass of `BaseTool` or `ParrotTool` exists.
- [ ] `HandoffTool` expects `prompt` as a required parameter.
- [ ] Executing `HandoffTool.run()` raises `HumanInteractionInterrupt` containing the given prompt.
- [ ] Test coverage exists for the tool's expected raising behavior.

---

## Test Specification

```python
# tests/core/tools/test_handoff_tool.py
import pytest
from parrot.core.tools.handoff import HandoffTool
from parrot.core.exceptions import HumanInteractionInterrupt

def test_handoff_tool_raises_interrupt():
    tool = HandoffTool()
    prompt_msg = "Please provide your project ID."
    with pytest.raises(HumanInteractionInterrupt) as exc_info:
        tool._run(prompt=prompt_msg)
    
    assert prompt_msg in str(exc_info.value)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/handoff-tool-for-integrations-agents.spec.md`) for full context.
2. **Update status** in `tasks/.index.json` → `"in-progress"`.
3. **Implement** following the scope and notes above.
4. **Verify** all acceptance criteria are met using pytest.
5. **Move this file** to `sdd/tasks/completed/TASK-434-handoff-tool.md`.
6. **Update index** → `"done"`.
7. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Antigravity Agent
**Date**: 2026-03-12
**Notes**: Implemented `HandoffTool` inheriting from `AbstractTool` and created `HumanInteractionInterrupt` in `parrot/core/exceptions.py`. Added unit tests in `tests/core/tools/test_handoff_tool.py` testing both synchronous and asynchronous execution. All acceptance criteria met and tests pass.

**Deviations from spec**: Created `parrot/core/exceptions.py` inside `core` as requested instead of adapting the primary `parrot/exceptions.py` to maintain exact alignment with spec requirements mapping.
