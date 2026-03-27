# TASK-435: Orchestrator Pause & Resume Support

**Feature**: Handoff Tool for Integrations Agents
**Spec**: `sdd/specs/handoff-tool-for-integrations-agents.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-051
**Assigned-to**: jesuslara

---

## Context

> Enables the core `AutonomousOrchestrator` to catch human interaction interrupts, suspend the current agent's execution, and resume it once the user provides their input.
> Implements spec Section 3.2.

---

## Scope

- Modify the main step loop in `parrot/autonomous/orchestrator.py` (e.g. `execute_agent`).
- Catch `HumanInteractionInterrupt` when an agent's tool execution fails with it.
- Suspend the execution task and yield control, effectively placing the conversation turn into a `requires_action` / suspended state.
- Create a `resume_agent(session_id, user_input)` entrypoint in the orchestrator that retrieves the suspended memory state of instructions and tool calls, injects the user's input as the Tool Output / Message, and resumes the LLM execution seamlessly.

**NOT in scope**: Managing the session persistence logic at the chat integration level (TASK-053).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/autonomous/orchestrator.py` | MODIFY | Update agent execution to handle the pause-resume lifecycle and `HumanInteractionInterrupt`. |

---

## Implementation Notes

- Study how existing exceptions inside the agent run are handled securely.
- If the agent is using LangChain or similar under the hood, injecting tool call results requires formatting the `user_input` as a matching `ToolMessage` or similar callback response format.
- Returning the suspended state must include enough routing payload (the prompt requested by the agent) so the integration layers know what to send to the human.

---

## Acceptance Criteria

- [ ] `AutonomousOrchestrator` catches `HumanInteractionInterrupt`.
- [ ] The orchestrator returns a state object containing the prompt instead of failing the task outright.
- [ ] A `resume_agent` or equivalent method accepts a session ID and text input.
- [ ] When resumed, the orchestrator successfully injects the user text as the tool response to the previous `HandoffTool` call.
- [ ] Tests simulate an interrupted flow and a subsequent resume, proving text reaches the LLM.

---

## Test Specification

```python
# tests/autonomous/test_orchestrator_handoff.py
import pytest
# ... imports ...

@pytest.mark.asyncio
async def test_orchestrator_pause_resume_flow():
    # 1. Setup mock agent equipped with HandoffTool
    # 2. Start execute_agent
    # 3. Assert execution returns 'requires_action' state with correct prompt
    # 4. Resume execution via resume_agent(session_id, user_input="User answer")
    # 5. Assert execution finishes successfully
    pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/handoff-tool-for-integrations-agents.spec.md`) for full context.
2. **Update status** in `tasks/.index.json` → `"in-progress"`.
3. **Implement** following the scope and notes above.
4. **Verify** all acceptance criteria are met using robust async tests.
5. **Move this file** to `sdd/tasks/completed/TASK-435-orchestrator-pause-resume.md`.
6. **Update index** → `"done"`.
7. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**:
**Notes**: 

**Deviations from spec**: 
