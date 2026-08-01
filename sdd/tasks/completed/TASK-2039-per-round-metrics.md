# TASK-2039: MetricsSubscriber — per-round OTel instruments

**Feature**: FEAT-397 — Per-Round Token Usage Observability
**Spec**: `sdd/specs/tokens-observability.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2032
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10. Per-round OTel metrics in v1 (resolved spec Q&A):
`MetricsSubscriber` subscribes to `ClientRoundEvent` and records on
DEDICATED per-round instruments. The existing total histogram
(`gen_ai.client.token.usage`) must NEVER receive per-round records —
that would double-count against the `AfterClientCallEvent` totals.

---

## Scope

- In `observability/subscribers/metrics.py`:
  - Create instruments in `__init__`:
    - `parrot.client.round.token.usage` — histogram, reuse the existing
      token-space bucket boundaries constant.
    - `parrot.client.rounds` — counter (one increment per round event).
  - Subscribe in `register()`: `registry.subscribe(ClientRoundEvent, self._on_client_round)`.
  - Implement `async def _on_client_round(self, event)`:
    - attrs: `gen_ai.system` (via `resolve_gen_ai_system`),
      `gen_ai.provider.name`, `gen_ai.request.model`,
      `parrot.agent.name` (`event.agent_name or "unknown"`),
      `parrot.round.number` (int).
    - Record input/output tokens with `gen_ai.token.type` = "input"/"output"
      ONLY when the event's token fields are not None.
    - Increment `parrot.client.rounds` always.
  - Docstring note on `parrot.round.number` cardinality (bounded by
    max_turns 10–15).
- Unit tests including the double-count guard.

**NOT in scope**: trace/span subscribers (`GenAIOpenTelemetrySubscriber`
per-round spans are a follow-up), client loops, cost computation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py` | MODIFY | New instruments + handler + subscription |
| `packages/ai-parrot/tests/unit/observability/test_per_round_metrics.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.core.events.lifecycle.events.client import AfterClientCallEvent  # existing import in metrics.py
from parrot.core.events.lifecycle.events import ClientRoundEvent   # created by TASK-2032
from parrot.observability.attributes import resolve_gen_ai_system  # metrics.py:30 (already imported)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/subscribers/metrics.py
class MetricsSubscriber:
    # token-space bucket boundaries constant near line 41 — REUSE for the new histogram
    _client_cost_total   = meter.create_counter("gen_ai.client.cost.total")        # line 103
    _client_op_duration  = meter.create_histogram("gen_ai.client.operation.duration")  # line 122
    _client_token_usage  = meter.create_histogram("gen_ai.client.token.usage")     # line 127
    def register(self, registry) -> None:            # line 155
        # registry.subscribe(AfterClientCallEvent, self._on_client_after)  # line 162 — pattern
    async def _on_client_after(self, event) -> None:  # line 190
        # base attrs pattern (lines ~192-200):
        #   system = resolve_gen_ai_system(event.client_name)
        #   {"gen_ai.system": system, "gen_ai.provider.name": system,
        #    "gen_ai.response.model": event.model,
        #    "parrot.agent.name": event.agent_name or "unknown"}
        # token records lines ~211-218 with "gen_ai.token.type": "input"/"output"
```

### Does NOT Exist
- ~~`MetricsSubscriber._on_client_round`~~ — created by THIS task
- ~~`parrot.client.round.token.usage` / `parrot.client.rounds` instruments~~ — created by THIS task
- ~~recording per-round tokens on `_client_token_usage`~~ — FORBIDDEN
  (double-count); acceptance criterion enforces it
- ~~`event.usage`~~ — `ClientRoundEvent` carries FLAT token ints, no nested object

---

## Implementation Notes

### Key Constraints
- Follow the `_on_client_after` attr-building pattern verbatim (FEAT-228
  `"unknown"` fallback included).
- Skip token records (not the counter) when `event.input_tokens is None`.
- PII contract unchanged: no user_id/session_id/prompt content in labels.
- Open question from spec §8: instrument naming may shift to a
  `gen_ai.`-prefixed SemConv name if one fits — check current OTel GenAI
  SemConv before finalizing; default to the `parrot.`-prefixed names above.

---

## Acceptance Criteria

- [ ] `ClientRoundEvent` → `parrot.client.round.token.usage` records with
      `parrot.round.number` + `parrot.agent.name` + `gen_ai.token.type` dims.
- [ ] `parrot.client.rounds` increments once per event.
- [ ] `gen_ai.client.token.usage` receives ZERO records from `_on_client_round`
      (explicit double-count guard test).
- [ ] Token fields None → no token records, counter still increments.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/observability/test_per_round_metrics.py -v`
- [ ] Existing observability suite passes: `pytest packages/ai-parrot/tests/integration/observability/ -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_per_round_metrics.py
# Reuse the in-memory metric reader fixture pattern from
# packages/ai-parrot/tests/integration/observability/ (test_poc.py).
class TestPerRoundMetrics:
    async def test_round_histogram_records(self): ...
    async def test_rounds_counter_increments(self): ...
    async def test_no_double_count_on_total_histogram(self): ...
    async def test_none_tokens_skip_histogram(self): ...
    async def test_agent_name_unknown_fallback(self): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2032 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/tokens-observability.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill in the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Added `ClientRoundEvent` import, the dedicated
`parrot.client.round.token.usage` histogram + `parrot.client.rounds`
counter, subscription in `register()`, and `_on_client_round` handler
(records input/output tokens only when not None; always increments the
rounds counter; `parrot.agent.name` falls back to `"unknown"`). Kept the
`parrot.`-prefixed instrument names per the spec's default (open question
in spec §8 left the final SemConv naming to the implementer; no existing
`gen_ai.*` SemConv fits a per-round token histogram today). Created
`tests/unit/observability/test_per_round_metrics.py` (5 tests incl. the
explicit double-count guard) — all pass. Ran
`tests/unit/observability/` + `tests/integration/observability/`: 130 passed.

**Deviations from spec**: none
