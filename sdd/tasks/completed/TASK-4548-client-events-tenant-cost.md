# TASK-4548: Fill tenant and cost_usd at the AbstractClient emit sites

**Feature**: FEAT-710 — Parrot telemetry event fan-out
**Spec**: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4544, TASK-4546, TASK-4547
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The origin (`AbstractClient._emit_after_call` / `_emit_failed_call`) is where cost is computed exactly once and where the tenant is captured at construction time (FEAT-228 rule). The computed cost is also written into the response's `CompletionUsage.estimated_cost` when empty, so AgentTalk can persist it (design research S4).

---

## Scope

- `clients/base.py:751`: add `tenant=current_tenant.get()` and `cost_usd=<computed>` to `AfterClientCallEvent(...)`.
- `clients/base.py:801`: add `tenant=current_tenant.get()` to `ClientCallFailedEvent(...)`.
- Compute cost with `get_shared_cost_calculator()`; `None` when no calculator, unknown pricing, or on any exception.
- Return/propagate the cost so the caller can fill `CompletionUsage.estimated_cost` when it is `None`. `# FILL IN` decides the plumbing (return value of `_emit_after_call` vs. a ContextVar) — bounded by AC-3.
- Write tests.

**NOT in scope**: subscriber changes (TASK-4550); bot-level events (TASK-4549).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | tenant + cost_usd on client events; estimated_cost backfill |
| `packages/ai-parrot/tests/unit/observability/test_client_event_tenant_cost.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/dev` @ `cf1888270` (2026-10-21). Re-run every `grep -c` before editing.

### Verified Imports
```python
from parrot.observability.context import current_tenant  # created by TASK-4544
from parrot.observability.cost import get_shared_cost_calculator  # created by TASK-4547
from parrot.observability.attributes import resolve_gen_ai_system  # verified: recorders/subscriber.py:96
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
async def _emit_after_call(self, tc, *, client_name, model, duration_ms, input_tokens=None, output_tokens=None, finish_reason=None) -> None  # ≈:727-750
event = AfterClientCallEvent(                                   # :751
    ..., agent_name=current_agent_name.get(), user_id=current_user_id.get(), session_id=current_session_id.get())
await self._forward_to_global_awaited(event)                   # after :769
async def _emit_failed_call(self, tc, *, client_name, model, duration_ms, exc) -> None   # ≈:779
event = ClientCallFailedEvent(                                  # :801
# packages/ai-parrot/src/parrot/models/basic.py:48  class CompletionUsage; estimated_cost: Optional[float] = None  # :91
```

### Does NOT Exist
- ~~`AbstractClient.cost_calculator`~~ — clients hold no calculator; use the shared holder
- ~~`AIMessage.cost_usd`~~ — no such field; use `usage.estimated_cost`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/clients/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_client_event_tenant_cost.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_after_call",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_failed_call",
    "sym:packages/ai-parrot/src/parrot/models/basic.py#CompletionUsage"
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
1. Add a private `_compute_call_cost(client_name, model, input_tokens, output_tokens)` method — *why*: keeps the try/except out of the event literal.
2. Add the two kwargs to `AfterClientCallEvent(` and one to `ClientCallFailedEvent(` — *why*: read ContextVars at construction time (FEAT-228 comment at :761-763).
3. Backfill `estimated_cost` — *why*: AgentTalk persists it without recomputing (spec §3 M5).

### `packages/ai-parrot/src/parrot/clients/base.py` (MODIFY)
```python
# occurrences: 4 (verified: grep -c 'session_id=current_session_id.get(),' packages/ai-parrot/src/parrot/clients/base.py)
# FILL IN: disambiguate — edit only inside `event = AfterClientCallEvent(` (:751, 1 occurrence) and
#          `event = ClientCallFailedEvent(` (:801, 1 occurrence); the other two are Before/stream events.
# inside AfterClientCallEvent(...):
            tenant=current_tenant.get(),
            cost_usd=self._compute_call_cost(client_name, model, input_tokens, output_tokens),
# inside ClientCallFailedEvent(...):
            tenant=current_tenant.get(),
```
```python
    def _compute_call_cost(
        self, client_name: str, model: "Optional[str]", input_tokens: "Optional[int]", output_tokens: "Optional[int]"
    ) -> "Optional[float]":
        """FEAT-710: one cost computation per call, with the shared calculator. Never raises."""
        calc = get_shared_cost_calculator()
        if calc is None:
            return None
        try:
            return calc.cost_usd(
                provider=resolve_gen_ai_system(client_name),
                model=model or "",
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
            )
        except Exception:  # noqa: BLE001
            self.logger.debug("cost computation failed for %s/%s", client_name, model, exc_info=True)
            return None
```
`# FILL IN: make the computed cost reach the AIMessage's usage.estimated_cost (only when None) — bounded by AC-3; prefer returning it from _emit_after_call and setting it at the call sites that hold the AIMessage, without changing provider-specific clients beyond that.`

### `packages/ai-parrot/tests/unit/observability/test_client_event_tenant_cost.py` (CREATE)
```python
"""FEAT-710 TASK-4548 — client events carry tenant and cost_usd."""
import pytest


@pytest.mark.asyncio
async def test_after_call_has_tenant_and_cost() -> None:
    # FILL IN: shared spy calculator returning 0.01, current_tenant="t1", call _emit_after_call on a minimal
    #          client double (pattern: tests/unit/observability/test_client_global_bridge.py); assert event fields — AC-1
    raise NotImplementedError


@pytest.mark.asyncio
async def test_no_calculator_gives_none_and_raising_calculator_never_breaks() -> None:
    # FILL IN — AC-2
    raise NotImplementedError
```

### FILL IN checklist
- [ ] Disambiguated edits — AC-1
- [ ] `estimated_cost` plumbing — AC-3
- [ ] Test bodies — AC-1, AC-2

---

## Acceptance Criteria

- [ ] `AfterClientCallEvent` carries `tenant` and `cost_usd` computed once with the shared calculator.
- [ ] No calculator / unknown pricing / exception → `cost_usd=None`, never an exception in the call path.
- [ ] The response's `usage.estimated_cost` is set from the same value when it was `None`.
- [ ] `ClientCallFailedEvent` carries `tenant`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_client_event_tenant_cost.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_client_global_bridge.py -q`

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
9. Close with `scripts/sdd/close_task.sh TASK-4548 parrot-telemetry-event-fanout verified`.
10. Fill in the Completion Note and commit the staged SDD state.

---

## Completion Note



**Completed by**: sdd-worker orchestrator (attempt 3; codex terra+sol returned empty_delivery on the under-specified `# FILL IN`)
**Date**: 2026-10-22
**Notes**: AC-1, AC-2 and failed-call tenant delivered in clients/base.py (tests, merge-tier green). AC-3 delivered in a follow-up pass (commit 9b08af6b6) via a central path rather than per-provider call sites: `AbstractClient._emit_after_call` publishes the once-computed cost in `parrot.observability.cost.last_call_cost`; `AbstractBot.execute_llm_call` and the `BaseBot.ask_stream` terminal-chunk path call `backfill_estimated_cost()` so `usage.estimated_cost` is filled only when None. Files beyond the original list (approved by the user): bots/abstract.py, bots/base.py, observability/cost/__init__.py. Unit tests green; bots+clients unit sweep shows the same 12 pre-existing failures before and after. Ledger issue:1874ef259510 covers this gap and can be closed once the PR merges.
