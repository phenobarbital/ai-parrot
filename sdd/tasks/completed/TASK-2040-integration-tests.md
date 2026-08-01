# TASK-2040: End-to-end multi-round usage integration tests

**Feature**: FEAT-397 — Per-Round Token Usage Observability
**Spec**: `sdd/specs/tokens-observability.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2034, TASK-2035, TASK-2036, TASK-2037, TASK-2038, TASK-2039
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests. Validates the whole pipeline — client loop →
events → metrics — through the real event registry and an in-memory
metric reader, plus the FEAT-228 per-agent attribution regression guard.

---

## Scope

- `test_multiround_end_to_end`: one client (Claude mock is fine) with a
  mocked provider returning tool_use twice then stop. Assert, through the
  REAL event registry + in-memory metric reader:
  - N `ClientRoundEvent`s received by a test subscriber.
  - `AIMessage.usage` equals the accumulated sum; `extra_usage["rounds"]` set.
  - `AfterClientCallEvent` totals correct.
  - `parrot.client.round.token.usage` + `parrot.client.rounds` recorded;
    `gen_ai.client.token.usage` recorded ONLY from the After event.
- `test_per_agent_round_attribution`: run the mocked multi-round call
  under `agent_identity("bot-a")`; assert round metrics carry
  `parrot.agent.name == "bot-a"`.
- Final green sweep of the feature's full test surface.

**NOT in scope**: new production code. If an integration test exposes a
bug, fix it in the owning module and note the deviation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/observability/test_multiround_usage.py` | CREATE | Both integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.basic import CompletionUsage                    # models/basic.py:48
from parrot.core.events.lifecycle.events import ClientRoundEvent, AfterClientCallEvent  # TASK-2032 + existing
from parrot.observability.context import agent_identity            # FEAT-228 (observability/context.py)
```

### Existing Signatures to Use
```python
# Fixtures to reuse:
# - in-memory span exporter + metric reader wiring:
#   packages/ai-parrot/tests/integration/observability/ (test_poc.py pattern)
# - mock-SDK concrete client:
#   packages/ai-parrot/tests/unit/clients/test_client_lifecycle.py
#   and the per-client multiround tests from TASK-2034…2038.

# Client events reach the global registry via forward_to_global (the client
# registry is isolated: _init_events(forward_to_global=False) + explicit bridge).
# Subscribe test listeners on the GLOBAL registry, mirroring how the
# observability subscribers register (MetricsSubscriber.register, metrics.py:155).
```

### Does NOT Exist
- ~~`AIMessage.usage_history`~~ — assert totals via `usage` / `total_usage()`
- ~~per-round records on `gen_ai.client.token.usage`~~ — the e2e test must
  PROVE their absence

---

## Implementation Notes

### Key Constraints
- Deterministic mocked usages: (100/10), (150/20), (200/30) → totals (450/60),
  consistent with the unit tests from TASK-2034…2038.
- Use `pytest-asyncio`; give fire-and-forget `emit_nowait` events a chance
  to drain before asserting (await a registry flush/`asyncio.sleep(0)`
  pattern — check how existing lifecycle tests settle nowait emissions and
  copy that).

---

## Acceptance Criteria

- [ ] `test_multiround_end_to_end` passes with all assertions listed in Scope.
- [ ] `test_per_agent_round_attribution` passes.
- [ ] Full feature surface green:
      `pytest packages/ai-parrot/tests/unit/models/test_completion_usage_add.py packages/ai-parrot/tests/unit/events/lifecycle/test_client_round_event.py packages/ai-parrot/tests/unit/clients/ packages/ai-parrot/tests/unit/observability/test_per_round_metrics.py packages/ai-parrot/tests/integration/observability/ -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/integration/observability/test_multiround_usage.py
class TestMultiRoundEndToEnd:
    async def test_multiround_end_to_end(self, metric_reader, global_registry): ...
    async def test_per_agent_round_attribution(self, metric_reader): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2034…2039 must ALL be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/tokens-observability.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill in the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Created
`tests/integration/observability/test_multiround_usage.py` with both
required tests, driving a real `AnthropicClient` (mocked SDK, same 3-round
fixture pattern as TASK-2034's unit tests) through `with scope() as
registry:` (real `EventRegistry` + `InMemoryMetricReader`), subscribing
only on the GLOBAL registry (matching real production wiring —
`MetricsSubscriber.register(global_registry)` at app bootstrap):
- `test_multiround_end_to_end`: asserts 2 `ClientRoundEvent`s (round
  1 & 2, correct tool names/tokens), `AIMessage.usage` = accumulated
  (450/60) with `extra_usage["rounds"] == 3`, `AfterClientCallEvent`
  totals (450/60), `parrot.client.round.token.usage` recording exactly 4
  data points (2 rounds × input/output) with correct per-round values,
  `parrot.client.rounds` summing to 2, and `gen_ai.client.token.usage`
  recording EXACTLY 2 data points (450/60) — proving no per-round
  double-counting.
- `test_per_agent_round_attribution`: under `agent_identity("bot-a")`,
  both `parrot.client.round.token.usage` and `parrot.client.rounds` carry
  `parrot.agent.name == "bot-a"`.

Ran the full acceptance-criteria sweep (`test_completion_usage_add.py` +
`test_client_round_event.py` + `tests/unit/clients/` +
`test_per_round_metrics.py` + `tests/integration/observability/`): 77
passed. Also ran the broader `tests/unit/clients/` + `tests/unit/
observability/` + `tests/integration/observability/`: 176 passed.

**Deviations from spec**: This integration test exposed a real production
bug in TASK-2033's `AbstractClient._emit_round_event()` (`clients/base.py`),
fixed here per this task's explicit authorization ("If an integration
test exposes a bug, fix it in the owning module and note the
deviation"). The short-circuit `if not self.events.has_subscribers(
ClientRoundEvent): return` checked ONLY the client's own isolated
registry (`forward_to_global=False` by design) — but real consumers like
`MetricsSubscriber` subscribe on the GLOBAL registry, reached only via
the explicit `forward_to_global()` bridge that runs AFTER the
short-circuit. Since no production caller subscribes directly on an
individual client instance, `ClientRoundEvent` would have been
silently constructed-and-dropped in every real deployment — the entire
per-round metrics pipeline (Module 10) would have been dead on arrival.
Fixed by also checking `navigator_eventbus.lifecycle.global_registry.
get_global_registry().has_subscribers(ClientRoundEvent)` before
short-circuiting (lazy import inside the method, mirroring existing
deferred-import patterns in this codebase). Re-ran
`tests/unit/clients/test_emit_round_event.py` (TASK-2033's own suite,
including its zero-subscriber short-circuit test) to confirm the fix
doesn't regress it — 4 passed.
