# TASK-2614: Extend UsageRecord with flow attribution + record failed calls

**Feature**: FEAT-479 — Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus
**Spec**: `sdd/specs/devflow-telemetry-accounting.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2612
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4a and §2 Data Models A.

The usage pipeline already exists — `AfterClientCallEvent` →
`UsageRecordingSubscriber` → `UsageRecord` → fan-out to `AbstractLogger`
sinks. This task makes two additive changes so a per-run ledger (TASK-2615)
can consume it:

1. `UsageRecord` carries no **flow attribution** — nothing ties a call to a
   run, a seat, or a retry cycle.
2. `UsageRecordingSubscriber` subscribes **only** `AfterClientCallEvent`, so a
   **failed** LLM call is recorded nowhere. The spec requires reporting the
   tokens burned by a failed cycle.

> **Reuse, do not rebuild.** An earlier spec draft proposed a new
> `RunUsageSubscriber` and a new `UsageRecord`. Both were withdrawn in v0.3 —
> `UsageRecord` is a direct **name collision** with the existing model, and a
> second subscriber would duplicate cost calculation, provider normalization
> and error-isolated fan-out. Extend; do not shadow.

---

## Scope

- Add to the **existing** `UsageRecord` (`recorders/models.py:22`), all
  optional/defaulted so existing recorders are unaffected:
  `run_id`, `seat`, `node_id`, `cycle`, `usage_reported`, `status`, `error_type`.
- In `UsageRecordingSubscriber._on_client_after`: populate `run_id`/`seat`/
  `node_id` from the TASK-2612 ContextVars, and set `usage_reported=False`
  when the event reported neither token count.
- In `UsageRecordingSubscriber.register`: **also** subscribe
  `ClientCallFailedEvent`, with a new `_on_client_failed` handler that builds
  a `UsageRecord` with `status="failed"` and `error_type`.
- Write the unit tests below, including the back-compat guard.

**NOT in scope**: the `RunLedgerRecorder` sink (TASK-2615); assigning `cycle`
(the sink does that — the subscriber leaves it `None`); any per-run registry
wiring (TASK-2616); touching the global registration at `bootstrap.py:138`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/recorders/models.py` | MODIFY | Add the additive fields |
| `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` | MODIFY | Attribution + failed-call handler |
| `packages/ai-parrot/tests/observability/test_usage_record_attribution.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/observability/recorders/subscriber.py:18
from parrot.core.events.lifecycle.events import AfterClientCallEvent
# ClientCallFailedEvent lives beside it — verified:
#   packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py:80
from parrot.core.events.lifecycle.events import ClientCallFailedEvent

# verified: packages/ai-parrot/src/parrot/observability/recorders/subscriber.py:19
from parrot.observability.attributes import resolve_gen_ai_system
# verified: packages/ai-parrot/src/parrot/observability/recorders/models.py:20
from parrot.observability.recorders.models import UsageRecord
# from TASK-2612:
from parrot.observability.context import current_run_id, current_seat
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/observability/recorders/models.py
class UsageRecord(BaseModel):                              # line 22
    provider: str                                          # line 45
    client_name: str = ""                                  # line 46
    model: str = ""                                        # line 47
    input_tokens: int = 0                                  # line 48  (int, NOT Optional)
    output_tokens: int = 0                                 # line 49  (int, NOT Optional)
    cost_usd: Optional[float] = None                       # line 50
    cumulative_cost_usd: Optional[float] = None            # line 51
    duration_ms: float = 0.0                               # line 52
    finish_reason: Optional[str] = None                    # line 53
    trace_id: Optional[str] = None                         # line 54
    service_name: str = "ai-parrot"                        # line 55
    timestamp: datetime = Field(default_factory=...)       # line 56
    @computed_field
    @property
    def total_tokens(self) -> int:                         # line 62
        return self.input_tokens + self.output_tokens
    # PRIVACY CONTRACT, docstring lines 8-11: NO prompt/completion content,
    # NO user_id/session_id. Only identifiers, counts, cost, timing, trace_id.

# packages/ai-parrot/src/parrot/observability/recorders/subscriber.py
class UsageRecordingSubscriber:                            # line 30
    def __init__(self, *, recorders: "list[AbstractLogger]",
                 cost_calculator: "Optional[CostCalculator]" = None,
                 service_name: str = "ai-parrot") -> None:  # line 40
    def register(self, registry: "EventRegistry") -> None:  # line 63
        registry.subscribe(AfterClientCallEvent, self._on_client_after)  # line 70
        # ^^^ ONLY this one today. Add ClientCallFailedEvent here.
    async def _on_client_after(self, event: AfterClientCallEvent) -> None:  # line 76
        provider = resolve_gen_ai_system(event.client_name)  # line 78
        input_tokens = event.input_tokens or 0               # line 79  <-- coercion
        output_tokens = event.output_tokens or 0             # line 80  <-- coercion
        ...
        trace_id = event.trace_context.trace_id if event.trace_context else None  # line 97
        record = UsageRecord(...)                            # line 100
        for recorder in self._recorders:                     # line 114
            try:
                await recorder.record(record)
            except Exception:  # noqa: BLE001 — one bad backend must not break others
                logger.exception(...)

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True)
class ClientCallFailedEvent(LifecycleEvent):               # line 80
    client_name: str
    model: str = ""                                        # line 100
    # carries error_type / error_message / duration_ms — VERIFY the exact
    # field names with dataclasses.fields() before use.
```

### Does NOT Exist

- ~~`UsageRecord.run_id` / `.seat` / `.node_id` / `.cycle`~~ — this task adds them.
- ~~`UsageRecordingSubscriber._on_client_failed`~~ — this task adds it.
- ~~A `RunUsageSubscriber` class~~ — **rejected in v0.3.** Do not create one.
- ~~`AfterClientCallEvent.provider`~~ — no such field; it is `client_name`,
  normalized through `resolve_gen_ai_system()`.
- ~~`event.model_dump()`~~ — lifecycle events are frozen **dataclasses**, not
  Pydantic. Use attribute access or `to_dict()`.

---

## Implementation Notes

### The `0`-coercion tension — read this before changing types

`subscriber.py:79-80` coerces unreported tokens to `0`. **Do not "fix" that**:
`PrometheusUsageRecorder` and `OpenLitUsageRecorder` need real `int`s, and
`total_tokens` (a `computed_field`) sums them. Changing the fields to
`Optional[int]` would break all three sinks.

Instead preserve the distinction with a flag:

```python
usage_reported = not (
    event.input_tokens is None and event.output_tokens is None
)
```

The report (TASK-2619) renders `—` when `usage_reported is False`, satisfying
the spec's "never fabricate `0`" criterion without changing the shared type.

### Failure records and the privacy contract

`models.py:8-11` forbids content on this record. An exception **message** can
contain prompt text, so:

- `error_type` — the exception **class name** only. Allowed.
- error **message** — NOT on `UsageRecord`. It already lives in session state
  (`NodeState.error` / `DispatchState.last_error`) and the run bundle renders
  it. The report joins the two.

For a failed call, token counts are whatever the event reported (often
nothing) — set `usage_reported` the same way, and do not invent zeros.

### Key Constraints

- Every new field must be optional/defaulted. A `UsageRecord` constructed with
  none of them must still validate — that is the back-compat guard.
- `status` is `Literal["completed", "failed"]` defaulting to `"completed"`, so
  existing construction sites need no change.
- The failed-call handler must mirror `_on_client_after`'s error-isolated
  fan-out loop (`subscriber.py:114-121`) — one bad sink must not break others.
- Do **not** compute cost on the failure path.
- `ClientCallFailedEvent` ends in `Failed`, so `EventRegistry` dispatches its
  subscribers in **reverse** registration order (`registry.py:260`). Harmless
  here, but do not rely on ordering between the two handlers.

### References in Codebase

- `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py:76-121` — the handler to mirror
- `packages/ai-parrot/src/parrot/observability/recorders/logging_recorder.py:17` — a minimal sink, useful in tests

---

## Acceptance Criteria

- [ ] `UsageRecord` gains `run_id`, `seat`, `node_id`, `cycle`,
      `usage_reported`, `status`, `error_type` — all optional/defaulted.
- [ ] `UsageRecord(provider="openai")` still validates (back-compat).
- [ ] `input_tokens`/`output_tokens` remain `int = 0`; `total_tokens` still works.
- [ ] A call emitted inside `usage_attribution("run-1", "development.w1")`
      produces a record with that `run_id`/`seat`, and `node_id == "development"`.
- [ ] An event with both token counts `None` yields `usage_reported=False`.
- [ ] `register()` subscribes both `AfterClientCallEvent` and
      `ClientCallFailedEvent`, and never `ClientStreamChunkEvent`.
- [ ] A `ClientCallFailedEvent` produces a record with `status="failed"` and
      `error_type` set; no error **message** appears on the record.
- [ ] Logging / OpenLit / Prometheus recorders accept the extended record unchanged.
- [ ] `pytest packages/ai-parrot/tests/observability/ -v` passes.
- [ ] `ruff check` clean on both modified files.

---

## Test Specification

```python
# packages/ai-parrot/tests/observability/test_usage_record_attribution.py
import pytest

from parrot.observability.context import usage_attribution
from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber


class _CapturingSink:
    """Minimal AbstractLogger double."""
    def __init__(self): self.records = []
    async def record(self, record): self.records.append(record)
    async def aclose(self): pass


def test_usagerecord_backcompat_minimal_construction():
    """Back-compat guard: none of the new fields are required."""
    r = UsageRecord(provider="openai")
    assert r.run_id is None and r.seat is None and r.cycle is None
    assert r.status == "completed"
    assert r.usage_reported is True
    assert r.total_tokens == 0


async def test_attribution_from_contextvars(isolated_registry):
    sink = _CapturingSink()
    isolated_registry.add_provider(
        UsageRecordingSubscriber(recorders=[sink], cost_calculator=None)
    )
    with usage_attribution("run-1", "development.w1"):
        await isolated_registry.emit(_after_call_event(input_tokens=10, output_tokens=5))
    (rec,) = sink.records
    assert rec.run_id == "run-1"
    assert rec.seat == "development.w1"
    assert rec.node_id == "development"        # rolled up
    assert rec.usage_reported is True


async def test_usage_reported_false_when_provider_reported_nothing(isolated_registry):
    """The 0-coercion stays for Prometheus/OpenLit; the flag preserves truth."""
    sink = _CapturingSink()
    isolated_registry.add_provider(
        UsageRecordingSubscriber(recorders=[sink], cost_calculator=None)
    )
    await isolated_registry.emit(_after_call_event(input_tokens=None, output_tokens=None))
    (rec,) = sink.records
    assert rec.usage_reported is False
    assert rec.input_tokens == 0               # coerced, but flagged as unreported


async def test_failed_call_recorded(isolated_registry):
    sink = _CapturingSink()
    isolated_registry.add_provider(
        UsageRecordingSubscriber(recorders=[sink], cost_calculator=None)
    )
    await isolated_registry.emit(_failed_call_event(error_type="TimeoutError"))
    (rec,) = sink.records
    assert rec.status == "failed"
    assert rec.error_type == "TimeoutError"


def test_no_error_message_field_on_record():
    """Privacy contract (models.py:8-11): no content on this record."""
    assert "error_message" not in UsageRecord.model_fields
```

**Fixtures**: use `isolated_registry` (an `EventRegistry(forward_to_global=False)`)
from spec §4 so tests never touch the global singleton. Build the event
helpers (`_after_call_event`, `_failed_call_event`) as frozen-dataclass
constructions — inspect `dataclasses.fields(ClientCallFailedEvent)` for the
exact required arguments.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 Data Models A and §3 Module 4a
2. **Check dependencies** — TASK-2612 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — especially `ClientCallFailedEvent`'s real
   field names via `dataclasses.fields()`
4. **Update status** in `sdd/tasks/index/devflow-telemetry-accounting.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2614-extend-usagerecord-and-failed-calls.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
