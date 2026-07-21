---
type: Wiki Overview
title: 'TASK-1284: Orchestrator policy_id short-circuit hardening'
id: doc:sdd-tasks-completed-task-1284-orchestrator-policyid-shortcircuit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 module **C11**. Defence-in-depth for the `HandoffTool`
relates_to:
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
- concept: mod:parrot.core.exceptions
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
---

# TASK-1284: Orchestrator policy_id short-circuit hardening

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1283
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C11**. Defence-in-depth for the `HandoffTool`
dedup. Even with the 500ms polling window in TASK-1283, a slow tier
action (e.g., Zammad API at 600ms) can resolve *after* the tool gave
up and raised the interrupt. The orchestrator already catches the
interrupt; this task teaches it to consult `manager.get_result` once
before re-entering suspend/resume.

---

## Scope

- In `parrot/autonomous/orchestrator.py`, in BOTH catch blocks
  (`orchestrator.py:541-564` and the mirror at `:824`):
  - When `isinstance(e, HumanInteractionInterrupt)` AND
    `e.policy_id is not None` AND `e.interaction_id is not None`:
    1. Look up the process-wide manager via
       `parrot.human.get_default_human_manager()`.
    2. If a manager is found, `await manager.get_result(e.interaction_id)`.
    3. If a result exists with a non-empty
       `action_metadata["message"]` or `consolidated_value`, build an
       `ExecutionResult(success=True, ..., output=<message-or-value>)`
       and return it WITHOUT suspending the agent.
    4. If no result is found (or no manager), fall through to the
       existing suspend/resume path.
- Add a feature flag check or env guard if necessary so the short-
  circuit can be disabled at runtime — recommended but not blocking;
  document the decision in the completion note.

**NOT in scope**: Changes to the HandoffTool (TASK-1283).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/autonomous/orchestrator.py` | MODIFY | Short-circuit policy_id-flagged interrupts when a manager result already exists |
| `packages/ai-parrot/tests/autonomous/test_orchestrator_handoff.py` | MODIFY | Add tests for the short-circuit path and for the legacy fallback |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing in orchestrator.py (inside catch block, already lazy-imported):
from parrot.core.exceptions import HumanInteractionInterrupt   # orchestrator.py:541, :824
# New (lazy inside the short-circuit branch):
from parrot.human import get_default_human_manager
```

### Existing Signatures to Use

```python
# parrot/autonomous/orchestrator.py:541-564 — catch block (PAUSED)
except Exception as e:
    from parrot.core.exceptions import HumanInteractionInterrupt
    if isinstance(e, HumanInteractionInterrupt):
        # ... currently builds ExecutionResult with status="paused"
        # and metadata containing the prompt + state ...

# parrot/autonomous/orchestrator.py:824 — mirror catch block in another method
# Same shape; both must get the short-circuit.

# parrot/human/__init__.py:60-62
def get_default_human_manager() -> Optional[HumanInteractionManager]: ...

# parrot/human/manager.py:354-362
async def get_result(self, interaction_id) -> Optional[InteractionResult]: ...

# parrot/human/models.py:238-248
class InteractionResult(BaseModel):
    consolidated_value: Any = None
    action_metadata: Dict[str, Any] = Field(default_factory=dict)
    # ...
```

### Does NOT Exist

- ~~A `bypass_suspend` flag on `HumanInteractionInterrupt`~~ — decision
  is data-driven by `(policy_id, interaction_id, manager.get_result)`.
- ~~Synchronous `manager.wait_for_result`~~ — only `get_result` exists.

---

## Implementation Notes

### Pattern to Follow

```python
except Exception as e:
    from parrot.core.exceptions import HumanInteractionInterrupt
    if isinstance(e, HumanInteractionInterrupt):
        # NEW: policy_id-driven short-circuit
        if e.policy_id and e.interaction_id:
            try:
                from parrot.human import get_default_human_manager
                mgr = get_default_human_manager()
                if mgr is not None:
                    result = await mgr.get_result(e.interaction_id)
                    if result is not None:
                        msg = (result.action_metadata or {}).get("message")
                        out = msg if msg is not None else result.consolidated_value
                        if out is not None:
                            execution_time = (datetime.now() - start_time).total_seconds() * 1000
                            exec_result = ExecutionResult(
                                request_id=request_id,
                                target_type=ExecutionTarget.AGENT,
                                target_id=agent_name,
                                success=True,
                                output=str(out),
                                execution_time_ms=execution_time,
                                metadata={"hitl_short_circuit": True, "interaction_id": e.interaction_id},
                            )
                            self._add_to_history(exec_result)
                            return exec_result
            except Exception:
                self.logger.exception("HITL short-circuit failed; falling back to suspend")

        # EXISTING: build paused ExecutionResult ...
```

### Key Constraints

- Short-circuit must be **opt-in by data**: ONLY fires when both
  `policy_id` and `interaction_id` are set on the interrupt. Legacy
  HandoffTool calls (which set neither) take the suspend path unchanged.
- A failure inside the short-circuit branch (e.g., manager.get_result
  raises) must NOT crash the orchestrator — log and fall through to
  the existing suspend behaviour.
- Apply to BOTH catch blocks (`:541-564` and `:824`); they handle
  different flows but the contract is identical.

### References in Codebase

- `parrot/autonomous/orchestrator.py:540-580` — first catch block.
- `parrot/autonomous/orchestrator.py:820-870` — second catch block.
- Spec §7 "HandoffTool dual-path race" gotcha.

---

## Acceptance Criteria

- [ ] When `HumanInteractionInterrupt` carries `policy_id` and
  `interaction_id` AND a result is already in Redis, the orchestrator
  returns a successful `ExecutionResult` with the action message and
  does NOT push a "paused" state.
- [ ] When `policy_id` is set but no result is found, the orchestrator
  falls through to the existing suspend path.
- [ ] When `policy_id` is `None` (legacy HandoffTool), the catch block
  behaviour is byte-identical to today.
- [ ] An exception inside the short-circuit logic logs an error and
  falls through to the existing suspend path (no crash).
- [ ] Both catch blocks (`:541-564` and `:824`) receive the
  short-circuit.
- [ ] Existing orchestrator tests pass without modification.
- [ ] New tests pass:
  `pytest packages/ai-parrot/tests/autonomous/test_orchestrator_handoff.py -v`.

---

## Test Specification

```python
# tests/autonomous/test_orchestrator_handoff.py — new
class TestPolicyIdShortCircuit:
    async def test_returns_message_when_result_exists(self): ...
    async def test_falls_back_to_suspend_when_no_result(self): ...
    async def test_legacy_interrupt_without_policy_id_still_suspends(self): ...
    async def test_short_circuit_exception_does_not_crash(self, caplog): ...
    async def test_both_catch_blocks_apply_short_circuit(self): ...
```

---

## Agent Instructions

1. Read spec §3 C11 + §7 race-condition gotcha.
2. Verify TASK-1283 completed.
3. Apply change to BOTH catch sites; keep logic identical.
4. Test, lint.
5. Move to completed.

---

## Completion Note

Implemented 2026-05-22 by sdd-worker (FEAT-194).

- Applied identical short-circuit block to BOTH catch sites in `orchestrator.py`: `resume_agent` (~line 540) and `_execute` (~line 823).
- Short-circuit condition: `e.policy_id and e.interaction_id` — skipped for legacy interrupts without policy_id.
- On result: builds `ExecutionResult(success=True, result=str(out), metadata={"hitl_short_circuit": True, ...})` and returns without suspending.
- On no result or exception: logs and falls through to existing suspend path.
- Feature flag decision: no separate env guard needed — the condition is data-driven by `(policy_id, interaction_id)` presence; legacy HandoffTool calls (without these fields) always take the suspend path unchanged.
- Patching note: `get_default_human_manager` is imported lazily inside the except block, so tests patch `parrot.human.get_default_human_manager` (the source), not `parrot.autonomous.orchestrator.get_default_human_manager`.
- 9 tests all pass: 4 legacy + 5 new short-circuit tests.
