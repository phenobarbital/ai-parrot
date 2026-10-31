# TASK-4985: UsageRecord SDD identity, event-first subscriber read, label whitelist test

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4983
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (second half), goals G1/G2, AC-1/AC-2/AC-9. `UsageRecord` carries no SDD
identity. The subscriber reads run/seat **only** from ContextVars at handling time, which
is wrong for a forwarded event. This task widens the record and makes the subscriber read
the event's snapshot first, using the ContextVar only as a fallback. It also adds the
cardinality regression test asserting that `attempt_uid`/`execution_id` never become metric labels.

---

## Scope

- Add `feat_id`, `task_id`, `attempt_uid`, `execution_id`, `dispatch_kind`, `roster_seat` to `UsageRecord` (all `Optional[str] = None`). `run_id`/`seat` stay unchanged.
- In `UsageRecordingSubscriber._on_client_after` and `_on_client_failed`, resolve the attribution as `event.attribution or current_usage_attribution.get()` and copy its fields onto the record.
- Write a test that a record built from a forwarded event keeps the event's attribution even when a different ContextVar value is bound at handling time (AC-2).
- Write a metrics label-whitelist test: emit an attributed event through `MetricsSubscriber` with mocked instruments, and assert that no recorded attribute key is in `{attempt_uid, execution_id, task_id}` (AC-9). `feat_id` is allowed as the bounded `parrot.feat_id` label that TASK-4996 adds.

**NOT in scope**: cache counters/cost on the record (TASK-4986/4987); the durable sink (TASK-4990); modifying `subscribers/metrics.py` (it must stay untouched; the test only asserts).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/recorders/models.py` | MODIFY | Six SDD identity fields |
| `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` | MODIFY | Event-first attribution read |
| `packages/ai-parrot/tests/observability/test_usage_record_sdd_attribution.py` | CREATE | AC-1 / AC-2 tests |
| `packages/ai-parrot/tests/unit/observability/test_metrics_label_whitelist.py` | CREATE | AC-9 cardinality test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.recorders.models import UsageRecord                 # models.py:22
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber  # subscriber.py:47
from parrot.observability.context import current_run_id, current_seat         # subscriber.py:23 (existing)
from parrot.observability.context import current_usage_attribution            # created by TASK-4983
from parrot.observability.attribution import UsageAttribution                 # created by TASK-4983
from parrot.observability.subscribers.metrics import MetricsSubscriber        # metrics.py (class with _on_client_after at :215)
```

### Existing Signatures to Use
```python
# recorders/models.py — FEAT-479 block ends with:
    # ── FEAT-479: honesty + failure. ──      # :82
    usage_reported: bool = True
    status: Literal["completed", "failed"] = "completed"
    error_type: Optional[str] = None          # :85
# recorders/subscriber.py
    async def _on_client_after(self, event: AfterClientCallEvent) -> None:   # :94; record built :115-131
    async def _on_client_failed(self, event: ClientCallFailedEvent) -> None:  # :135; record built :148-161
    async def _fan_out(self, record: UsageRecord) -> None:                     # :165
# AfterClientCallEvent.attribution / ClientCallFailedEvent.attribution — added by TASK-4983
```

### Does NOT Exist
- ~~`UsageRecord.feat_id`~~ — this task creates it
- ~~`UsageRecord.accounting_seat`~~ — do NOT add; the existing `seat` field IS the accounting seat
- ~~`MetricsSubscriber` label for attempt/execution ids~~ — must never exist (AC-9)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/subscriber.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/observability/test_usage_record_sdd_attribution.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/observability/test_metrics_label_whitelist.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/recorders/models.py#UsageRecord",
    "sym:packages/ai-parrot/src/parrot/observability/recorders/subscriber.py#UsageRecordingSubscriber",
    "sym:packages/ai-parrot/src/parrot/observability/subscribers/metrics.py#MetricsSubscriber"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `run_id`/`seat` stay sourced from `current_run_id`/`current_seat` exactly as today. Only the SDD fields come from the attribution, so FEAT-479 behaviour is unchanged.
- Keep `UsageRecord` PII-free. These identifiers are SDD ids, not user data; mention that in the docstring.

---

## Implementation Blueprint

### Steps (in order)
1. Add the record fields as a new commented block above the FEAT-479 honesty block, so the field groups stay readable.
2. Add a private helper `_attribution_fields(event)` in `subscriber.py`, so both handlers share one rule (event first, ContextVar fallback).
3. Pass `**_attribution_fields(event)` into both `UsageRecord(...)` constructions.
4. Write both test files.

### `packages/ai-parrot/src/parrot/observability/recorders/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    # ── FEAT-479: honesty + failure. ──' models.py)
# BEFORE — insert above `    # ── FEAT-479: honesty + failure. ──` (verified: models.py:82)
    # ── FEAT-783: SDD attribution (from the event snapshot; ContextVar fallback). ──
    # Durable-store / span data ONLY — never metric labels (unbounded cardinality, AC-9).
    feat_id: Optional[str] = None
    task_id: Optional[str] = None
    attempt_uid: Optional[str] = None
    execution_id: Optional[str] = None
    dispatch_kind: Optional[str] = None
    roster_seat: Optional[str] = None

```
Add matching entries to the class docstring's Attributes list.

### `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.observability.context import current_run_id, current_seat' subscriber.py)
# REPLACE `from parrot.observability.context import current_run_id, current_seat` (verified: subscriber.py:23)
from parrot.observability.context import current_run_id, current_seat, current_usage_attribution
```
```python
# AFTER `_node_id_from_seat` (ends subscriber.py:44) — new module-level helper
def _attribution_fields(event: "AfterClientCallEvent | ClientCallFailedEvent") -> "dict[str, Optional[str]]":
    """FEAT-783: SDD ids from the event snapshot; the ContextVar is a fallback only."""
    attribution = getattr(event, "attribution", None) or current_usage_attribution.get()
    if attribution is None:
        return {}
    return {
        "feat_id": attribution.feat_id,
        "task_id": attribution.task_id,
        "attempt_uid": attribution.attempt_uid,
        "execution_id": attribution.execution_id,
        "dispatch_kind": attribution.dispatch_kind,
        "roster_seat": attribution.roster_seat,
    }
```
```python
# FILL IN: disambiguate — `usage_reported=...` differs per handler; add `**_attribution_fields(event),`
# as the LAST kwarg of BOTH UsageRecord(...) calls:
#   success: below `            usage_reported=usage_reported,` (subscriber.py:130, 1 occurrence)
#   failure: below `            error_type=event.error_type or None,` (subscriber.py:160, 1 occurrence)
```

### `packages/ai-parrot/tests/observability/test_usage_record_sdd_attribution.py` (CREATE)
```python
"""FEAT-783 TASK-4985 — UsageRecord SDD identity (AC-1, AC-2)."""
import pytest

from parrot.core.events.lifecycle import TraceContext
from parrot.core.events.lifecycle.events import AfterClientCallEvent, ClientCallFailedEvent
from parrot.observability.attribution import UsageAttribution
from parrot.observability.context import usage_attribution
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber


class _Capture:
    name = "capture"

    def __init__(self) -> None:
        self.records = []

    async def record(self, record) -> None:
        self.records.append(record)

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_record_carries_sdd_fields_and_keeps_run_seat() -> None:
    # FILL IN: AC-1 — six fields populated; run_id/seat still from current_run_id/current_seat
    ...


@pytest.mark.asyncio
async def test_forwarded_event_keeps_original_attribution() -> None:
    # FILL IN: AC-2 — build event under attribution A, handle it under a binding of B -> record has A
    ...


@pytest.mark.asyncio
async def test_contextvar_fallback_when_event_has_none() -> None:
    # FILL IN: event constructed outside any binding, handled inside binding B -> record has B
    ...


@pytest.mark.asyncio
async def test_failed_event_attributed() -> None:
    # FILL IN: ClientCallFailedEvent path copies the same fields
    ...
```

### `packages/ai-parrot/tests/unit/observability/test_metrics_label_whitelist.py` (CREATE)
```python
"""FEAT-783 AC-9 — SDD ids never become metric labels."""
# feat_id is ALLOWED as the bounded `parrot.feat_id` label (added by TASK-4996, user decision 2026-10-31).
FORBIDDEN = {"attempt_uid", "execution_id", "task_id", "parrot.attempt_uid", "parrot.execution_id", "parrot.task_id"}


async def test_attributed_event_adds_no_unbounded_labels() -> None:
    # FILL IN: construct MetricsSubscriber with mocked instruments (follow test_metrics_subscriber.py's
    # fixture style), emit an attributed AfterClientCallEvent, collect every `attributes=` dict passed
    # to .add/.record and assert no key intersects FORBIDDEN
    ...
```

### FILL IN checklist
- [ ] Insert `**_attribution_fields(event)` in both handlers; bounded by AC-1/AC-2
- [ ] Test bodies; the whitelist test reuses the mocking style in `tests/unit/observability/test_metrics_subscriber.py`, bounded by AC-9

---

## Acceptance Criteria

- [ ] AC-1: the six fields exist; `run_id`/`seat` unchanged.
- [ ] AC-2: the event snapshot wins over the ContextVar; the ContextVar is used only when the event has none.
- [ ] AC-9: whitelist test passes; `subscribers/metrics.py` is not modified.

## Validation Commands
- `pytest packages/ai-parrot/tests/observability/test_usage_record_sdd_attribution.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_metrics_label_whitelist.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_usage_subscriber.py -q`
- `pytest packages/ai-parrot/tests/observability/test_usage_record_attribution.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Four files only. `PYTHONPATH=packages/ai-parrot/src`.

## Completion Note
_(filled at close)_
