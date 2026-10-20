# TASK-4549: Fill tenant / user_id / session_id on the bot invoke events

**Feature**: FEAT-710 — Parrot telemetry event fan-out
**Spec**: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-4545, TASK-4546
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 / design research S7. The nine `AfterInvokeEvent(`/`InvokeFailedEvent(` construction sites in `bots/base.py` must carry tenant, user and session so the consumer can attribute invoke errors per user and tenant.

---

## Scope

- At every `AfterInvokeEvent(` (:584, :1757, :2244) and `InvokeFailedEvent(` (:603, :620, :1775, :1794, :2260, :2277) in `bots/base.py`, add `tenant=current_tenant.get()`, `user_id=current_user_id.get()`, `session_id=current_session_id.get()`.
- Write tests for one success and one failure path.

**NOT in scope**: event field definitions (TASK-4546).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | Attribution kwargs on the 9 invoke-event sites |
| `packages/ai-parrot/tests/unit/bots/test_invoke_event_attribution.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/dev` @ `cf1888270` (2026-10-21). Re-run every `grep -c` before editing.

### Verified Imports
```python
from parrot.observability.context import current_tenant  # created by TASK-4544
from parrot.observability.context import current_user_id, current_session_id  # verified: bots/base.py:61-65 (re-check the exact names imported)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/base.py
AfterInvokeEvent(  # :584 (conversation), :1757 (ask), :2244 (ask_stream)
InvokeFailedEvent( # :603, :620 (conversation), :1775, :1794 (ask), :2260, :2277 (ask_stream)
# ContextVars are bound before these sites: conversation :221-223, ask :1145-1147, ask_stream (same pattern)
```

### Does NOT Exist
- ~~`AfterInvokeEvent.cost_usd`~~ — not a field; do not add

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/bots/test_invoke_event_attribution.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask_stream",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.conversation"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async-first; never block the event loop; `self.logger`, never `print`.
- Telemetry must never raise into the request path.
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Add the three kwargs to each of the nine constructions — *why*: ContextVars are already bound there, and reading them at construction time is the FEAT-228 rule.
2. Write the tests.

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY)
```python
# occurrences: 3 (verified: grep -c 'AfterInvokeEvent(' packages/ai-parrot/src/parrot/bots/base.py) and 6 (grep -c 'InvokeFailedEvent(')
# FILL IN: disambiguate — apply to ALL nine sites; each ends with `source_name=self.name,`. Add after it:
                    tenant=current_tenant.get(),
                    user_id=current_user_id.get(),
                    session_id=current_session_id.get(),
```
**Why**: identical kwargs everywhere; re-run both `grep -c` after editing — every site must have them (AC-1).

### `packages/ai-parrot/tests/unit/bots/test_invoke_event_attribution.py` (CREATE)
```python
"""FEAT-710 TASK-4549 — invoke events carry tenant/user/session."""
import pytest


@pytest.mark.asyncio
async def test_after_invoke_carries_attribution() -> None:
    # FILL IN: bot double, subscribe to AfterInvokeEvent, ask(user_id="u", session_id="s", tenant="t") — AC-1
    raise NotImplementedError


@pytest.mark.asyncio
async def test_invoke_failed_carries_attribution() -> None:
    # FILL IN — AC-1
    raise NotImplementedError
```

### FILL IN checklist
- [ ] All nine sites — AC-1
- [ ] Two test bodies — AC-1

---

## Acceptance Criteria

- [ ] All nine invoke-event constructions carry `tenant`, `user_id`, `session_id`.
- [ ] Values match the call's arguments in tests.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/bots/test_invoke_event_attribution.py -q`

---

## Test Specification

See the test-file block in the Implementation Blueprint; every `FILL IN` test must pass.

---

## Agent Instructions

1. Work in the feature worktree, never on `dev`:
   `python -m scripts.sdd.ensure_worktree --slug parrot-telemetry-event-fanout --feature-id FEAT-710`
2. Read the spec `sdd/specs/parrot-telemetry-event-fanout.spec.md` (rev 0.4) for context.
3. Check that every `Depends-on` task is `done` in `sdd/tasks/index/parrot-telemetry-event-fanout.json`.
4. Verify the Codebase Contract before writing code (re-run `grep -c` on every anchor); fix the contract first if it drifted.
5. Set this task `in-progress` in the index and commit only that file.
6. Implement from the Blueprint, completing every `# FILL IN:`; never change a fixed signature or path.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
8. Commit only the files listed in this task.
9. Close with `scripts/sdd/close_task.sh TASK-4549 parrot-telemetry-event-fanout verified`.
10. Fill in the Completion Note and commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
