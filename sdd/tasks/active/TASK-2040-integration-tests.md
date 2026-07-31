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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
