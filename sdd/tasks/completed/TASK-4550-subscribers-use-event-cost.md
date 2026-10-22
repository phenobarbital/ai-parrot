# TASK-4550: Subscribers consume event.cost_usd (single cost computation)

**Feature**: FEAT-710 — Parrot telemetry event fan-out
**Spec**: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-4547
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 / Goal G5. Today `UsageRecordingSubscriber`, `MetricsSubscriber` and the trace subscriber each call `CostCalculator.cost_usd()` for the same event. After this task they use `resolve_event_cost(event, self._cost)`.

---

## Scope

- `recorders/subscriber.py:103-114`: replace the direct `self._cost.cost_usd(...)` call with `resolve_event_cost(event, self._cost)`; keep the cumulative logic.
- `subscribers/metrics.py:243-250`: same, keeping the counter update.
- `subscribers/trace.py:276-282`: same.
- Keep the `cost_calculator=` constructor parameters.
- Write the 'computed once' test.

**NOT in scope**: the origin computation (TASK-4548).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` | MODIFY | Use resolve_event_cost |
| `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py` | MODIFY | Use resolve_event_cost |
| `packages/ai-parrot/src/parrot/observability/subscribers/trace.py` | MODIFY | Use resolve_event_cost |
| `packages/ai-parrot/tests/unit/observability/test_cost_computed_once.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/dev` @ `cf1888270` (2026-10-21). Re-run every `grep -c` before editing.

### Verified Imports
```python
from parrot.observability.cost import resolve_event_cost  # created by TASK-4547
```

### Existing Signatures to Use
```python
# recorders/subscriber.py — _on_client_after: `if self._cost is not None: cost_usd = self._cost.cost_usd(` :103-104; cumulative :110-114
# subscribers/metrics.py — `if self._cost is not None: cost = self._cost.cost_usd(` :243-244; `self._client_cost_total.add(cost, attributes=base)` :250
# subscribers/trace.py — _on_client_end: `if self._cost is not None: cost = self._cost.cost_usd(` :276-277; build_after_client_attrs(event, cost_usd=cost) :283
```

### Does NOT Exist
- ~~`MetricsSubscriber.cost_usd`~~ — no such attribute

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/observability/recorders/subscriber.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/observability/subscribers/metrics.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/observability/subscribers/trace.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_cost_computed_once.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/recorders/subscriber.py#UsageRecordingSubscriber",
    "sym:packages/ai-parrot/src/parrot/observability/subscribers/metrics.py#MetricsSubscriber"
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
1. Replace each guarded `self._cost.cost_usd(...)` block with one `resolve_event_cost` call — *why*: the helper returns the origin's value and only computes as a fallback.
2. Write the test that counts calculator calls.

### `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'cost_usd = self._cost.cost_usd(' recorders/subscriber.py)
# REPLACE the `if self._cost is not None:` block at :103-114 with:
        cost_usd = resolve_event_cost(event, self._cost)
        if cost_usd is not None or self._cost is not None:
            with self._lock:
                if cost_usd is not None:
                    self._cumulative_cost_usd += cost_usd
                    self._has_cost = True
                cumulative = self._cumulative_cost_usd if self._has_cost else None
```
`# FILL IN: confirm the cumulative semantics match test_usage_subscriber.py expectations` — AC-2.

### `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'cost = self._cost.cost_usd(' subscribers/metrics.py)
# REPLACE :243-250 with:
        cost = resolve_event_cost(event, self._cost)
        if cost is not None:
            self._client_cost_total.add(cost, attributes=base)
```

### `packages/ai-parrot/src/parrot/observability/subscribers/trace.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'cost = self._cost.cost_usd(' subscribers/trace.py)
# REPLACE :275-282 with:
        cost: Optional[float] = resolve_event_cost(event, self._cost)
```

### `packages/ai-parrot/tests/unit/observability/test_cost_computed_once.py` (CREATE)
```python
"""FEAT-710 TASK-4550 — one cost computation per LLM call."""
import pytest


@pytest.mark.asyncio
async def test_three_subscribers_zero_recompute_when_event_priced() -> None:
    # FILL IN: register UsageRecordingSubscriber + MetricsSubscriber + GenAIOpenTelemetrySubscriber with a spy
    #          calculator; emit AfterClientCallEvent(cost_usd=0.02); assert spy.calls == 0 and every sink saw 0.02 — AC-1
    raise NotImplementedError


@pytest.mark.asyncio
async def test_unpriced_event_still_priced_by_fallback() -> None:
    # FILL IN: cost_usd=None (dispatcher-style event) → subscribers still record a cost — AC-3
    raise NotImplementedError
```

### FILL IN checklist
- [ ] Cumulative semantics — AC-2
- [ ] Test bodies — AC-1, AC-3

---

## Acceptance Criteria

- [ ] With `event.cost_usd` set, none of the three subscribers calls `cost_usd()`; all report the same value.
- [ ] Existing subscriber tests pass unchanged.
- [ ] Events without `cost_usd` (dev-loop dispatcher) are still priced.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_cost_computed_once.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_usage_subscriber.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_metrics_subscriber.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_trace_subscriber.py -q`

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
9. Close with `scripts/sdd/close_task.sh TASK-4550 parrot-telemetry-event-fanout verified`.
10. Fill in the Completion Note and commit the staged SDD state.

---

## Completion Note



**Completed by**: sdd-worker orchestrator (coder: nova/qwen3-coder-480b (review fix b02b4b4c: unbound `cumulative`, kw-only spy))
**Date**: 2026-10-22
**Notes**: Merged by hand after engine reported task-tier validation unavailable (no execution_id); observability+bots unit tests green.

**Deviations from spec**: none
