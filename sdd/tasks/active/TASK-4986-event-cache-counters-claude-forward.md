# TASK-4986: Event cache/reasoning counters, source_cost_usd, Claude dispatcher forward

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4983, TASK-4984, TASK-4985
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (carriage half), design review S5, AC-3/AC-5. `dispatchers/claude.py`
already extracts `cache_creation_input_tokens`, `cache_read_input_tokens` and
`total_cost_usd` (claude.py:965-967), then drops them because `AfterClientCallEvent` has
no slots. This task adds the slots, forwards the data, and carries it onto `UsageRecord`.
`source_cost_usd` is **reconciliation input only**; it is never the reported cost (FEAT-710 G5).

---

## Scope

- Add `cache_read_tokens`, `cache_creation_tokens`, `reasoning_output_tokens` (`Optional[int] = None`) and `source_cost_usd` (`Optional[float] = None`) to `AfterClientCallEvent`.
- Add the same four fields to `UsageRecord`, and copy them in `UsageRecordingSubscriber._on_client_after`.
- In `ClaudeCodeDispatcher._emit_usage_event`, pass `cache_read_tokens`, `cache_creation_tokens` and `source_cost_usd` from `usage_detail`.
- **Never** let `source_cost_usd` populate `cost_usd`. `resolve_event_cost` is unchanged in this task.
- Tests.

**NOT in scope**: pricing the cache tiers (TASK-4987); the codex emitter (TASK-4993); in-process `AbstractClient` subclasses passing cache counters (follow-up — `clients/base.py` is touched only by TASK-4987).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` | MODIFY | Four fields on `AfterClientCallEvent` |
| `packages/ai-parrot/src/parrot/observability/recorders/models.py` | MODIFY | Four fields on `UsageRecord` |
| `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` | MODIFY | Copy them in `_on_client_after` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | Stop dropping cache/cost |
| `packages/ai-parrot/tests/unit/observability/test_usage_cache_counters_carriage.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.core.events.lifecycle.events import AfterClientCallEvent   # re-export
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher  # verify class name: grep -n '^class ' claude.py
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber
```

### Existing Signatures to Use
```python
# dispatchers/claude.py
    def _extract_result_usage(self, messages) -> Optional[Dict[str, Any]]   # returns keys incl.
        # "cache_creation_input_tokens", "cache_read_input_tokens", "total_cost_usd" (:965-967)
    async def _emit_usage_event(self, usage_detail, *, run_id, node_id, profile) -> None:  # :977
        # builds AfterClientCallEvent(... input_tokens=..., output_tokens=...,
        #   source_type="dispatcher", source_name="claude-code",)   # :1022 — anchor
# observability/cost/__init__.py
def resolve_event_cost(event, fallback) -> Optional[float]:  # :86 — event.cost_usd wins; else computes
```

### Does NOT Exist
- ~~`AfterClientCallEvent.cache_read_tokens`~~ / ~~`.source_cost_usd`~~ — this task creates them
- ~~`UsageRecord.cache_read_tokens`~~ — this task creates it
- ~~`ClientCallFailedEvent` token fields~~ — the failure event carries no tokens by design (privacy contract); do NOT add counters there

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/subscriber.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/observability/test_usage_cache_counters_carriage.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py#AfterClientCallEvent",
    "sym:packages/ai-parrot/src/parrot/observability/recorders/models.py#UsageRecord",
    "sym:packages/ai-parrot/src/parrot/observability/recorders/subscriber.py#UsageRecordingSubscriber",
    "sym:packages/ai-parrot/src/parrot/observability/cost/__init__.py#resolve_event_cost"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `source_cost_usd` is Claude SDK `total_cost_usd`. It is **process/session-cumulative in some SDK versions**, so it is never summed and never reported (AC-5). Document that in the field comment.
- Counters on the event are `Optional[int]` (`None` = not reported) while on `UsageRecord` they are `int = 0`, matching the existing `input_tokens` convention (models.py:66).

---

## Implementation Blueprint

### Steps (in order)
1. Event fields after the `attribution` line TASK-4983 added (after `cost_usd`), so FEAT-710/783 fields stay grouped.
2. Record fields in a new `# ── FEAT-783: four-counter usage ──` block below TASK-4985's attribution block.
3. Copy them in the subscriber's success handler: `cache_read_tokens=event.cache_read_tokens or 0`, etc., and `source_cost_usd=event.source_cost_usd`.
4. Forward in `claude.py`.
5. Tests, including a guard that `record.cost_usd != source_cost_usd` when pricing yields a different value.

### `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'cost_usd: Optional\[float\] = None  # FEAT-710: computed once at the origin' client.py)
# AFTER — insert below the `attribution: ... # FEAT-783` line TASK-4983 placed under
# `    cost_usd: Optional[float] = None  # FEAT-710: computed once at the origin` (client.py:80)
    cache_read_tokens: Optional[int] = None        # FEAT-783
    cache_creation_tokens: Optional[int] = None    # FEAT-783
    reasoning_output_tokens: Optional[int] = None  # FEAT-783
    source_cost_usd: Optional[float] = None
    """FEAT-783: provider-reported cost (Claude SDK total_cost_usd, codex turn cost).
    Reconciliation input ONLY — never the reported value (FEAT-710 G5, AC-5)."""
```

### `packages/ai-parrot/src/parrot/observability/recorders/models.py` (MODIFY)
```python
# AFTER the FEAT-783 attribution block TASK-4985 inserted (above `    # ── FEAT-479: honesty + failure. ──`, models.py:82, 1 occurrence)
    # ── FEAT-783: four-counter usage + provider-reported cost (reconciliation only). ──
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_output_tokens: int = 0
    source_cost_usd: Optional[float] = None
```

### `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            usage_reported=usage_reported,' subscriber.py)
# AFTER — insert below `            usage_reported=usage_reported,` (subscriber.py:130), before TASK-4985's `**_attribution_fields(event),`
            cache_read_tokens=event.cache_read_tokens or 0,
            cache_creation_tokens=event.cache_creation_tokens or 0,
            reasoning_output_tokens=event.reasoning_output_tokens or 0,
            source_cost_usd=event.source_cost_usd,
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '                    source_name="claude-code",' claude.py) — first match is in _emit_usage_event (:1022)
# FILL IN: disambiguate — confirm with `grep -n 'source_name="claude-code"' claude.py`; if the failure
# event (~:1074) also matches, insert ONLY in the one inside `_emit_usage_event`.
# AFTER — insert below `                    source_name="claude-code",` (claude.py:1022)
                    cache_read_tokens=usage_detail.get("cache_read_input_tokens"),
                    cache_creation_tokens=usage_detail.get("cache_creation_input_tokens"),
                    source_cost_usd=usage_detail.get("total_cost_usd"),
```
Update the `_emit_usage_event` docstring: cache/cost are now forwarded (FEAT-783 S5).

### `packages/ai-parrot/tests/unit/observability/test_usage_cache_counters_carriage.py` (CREATE)
```python
"""FEAT-783 TASK-4986 — cache counters + source_cost_usd carriage (AC-3, AC-5)."""
import pytest


@pytest.mark.asyncio
async def test_subscriber_copies_counters_to_record() -> None:
    # FILL IN: event with the three counters + source_cost_usd -> UsageRecord carries them
    ...


@pytest.mark.asyncio
async def test_source_cost_never_becomes_cost_usd() -> None:
    # FILL IN: event cost_usd=None, source_cost_usd=9.99, unpriced model -> record.cost_usd is None (AC-5)
    ...


@pytest.mark.asyncio
async def test_claude_emit_forwards_cache_and_cost() -> None:
    # FILL IN: call ClaudeCodeDispatcher._emit_usage_event with a usage_detail dict and a resolver
    # returning a fake registry that captures the emitted event; follow
    # tests/flows/dev_loop/test_cli_dispatcher_usage_events.py for how the dispatcher is built
    ...
```

### FILL IN checklist
- [ ] `claude.py` anchor disambiguation; bounded by AC-3
- [ ] Three test bodies; bounded by AC-3/AC-5

---

## Acceptance Criteria

- [ ] AC-3: the event and the record carry the counters; `claude.py` no longer drops cache/cost.
- [ ] AC-5: `source_cost_usd` is stored, and never copied into `cost_usd`.
- [ ] `test_cost_computed_once.py` still passes (AC-4).

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/observability/test_usage_cache_counters_carriage.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_cli_dispatcher_usage_events.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_cost_computed_once.py -q`
- `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_usage_event_fields.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Five files only. `PYTHONPATH=packages/ai-parrot/src`.

## Completion Note
_(filled at close)_
