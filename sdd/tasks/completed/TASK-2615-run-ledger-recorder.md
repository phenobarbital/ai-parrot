# TASK-2615: RunLedgerRecorder — the per-run usage ledger sink

**Feature**: FEAT-479 — Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus
**Spec**: `sdd/specs/devflow-telemetry-accounting.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2614
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4b and §2 Data Models B. This is where spec §1
Findings 2 and 3 are actually fixed.

The per-run ledger is an **`AbstractLogger` sink** — the usage pipeline's
designed extension point — not a new subscriber. `UsageRecordingSubscriber`
(extended by TASK-2614) owns the subscription and fans records out; this class
just accumulates them.

Being **append-only** is what fixes Finding 2: session state's `_with_dispatch`
merges into one `DispatchState` per node, so a retry cycle overwrites the
previous round's tokens. Appending never overwrites, so cycles accumulate.

Because `seat` is a free string (TASK-2612), `development.w1` is a first-class
seat — fixing Finding 3 without widening the closed `NodeId` `Literal`.

---

## Scope

- Create `RunLedgerRecorder(AbstractLogger)` with `record()` / `aclose()`.
- Assign `cycle` at record time via `next_cycle(seat)` — 1-based per
  `(run_id, seat)`.
- Implement `by_seat()` returning `list[SeatUsage]`, rolling `development.w1`
  under `development` while keeping worker seats as their own rows.
- Implement `partial` / `partial_reason` / `mark_partial()` (spec §8 Q1).
- Add the `SeatUsage` Pydantic model.
- Export both from `recorders/__init__.py` and mention the module in the
  package docstring.
- Write the unit tests below.

**NOT in scope**: subscribing to any event (the subscriber does that — this
class has no `register()`); the per-run registry wiring (TASK-2616); rendering
(TASK-2618/2619); persisting the ledger (explicitly out of scope per §8 Q1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/recorders/run_ledger.py` | CREATE | `RunLedgerRecorder` + `SeatUsage` |
| `packages/ai-parrot/src/parrot/observability/recorders/__init__.py` | MODIFY | Export both names |
| `packages/ai-parrot/tests/observability/test_run_ledger_recorder.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/observability/recorders/base.py:16
from parrot.observability.recorders.base import AbstractLogger
# verified: packages/ai-parrot/src/parrot/observability/recorders/models.py:22
from parrot.observability.recorders.models import UsageRecord
# verified: packages/ai-parrot/src/parrot/observability/recorders/subscriber.py:30
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/observability/recorders/base.py
class AbstractLogger(ABC):                                 # line 16
    async def record(self, record: UsageRecord) -> None: ...  # line 31 (ABSTRACT — must override)
    async def aclose(self) -> None: ...                       # line 39

# packages/ai-parrot/src/parrot/observability/recorders/models.py
class UsageRecord(BaseModel):                              # line 22
    provider: str
    client_name: str = ""
    model: str = ""
    input_tokens: int = 0        # int, NOT Optional — coerced at subscriber.py:79
    output_tokens: int = 0
    duration_ms: float = 0.0
    # -- added by TASK-2614 --
    run_id: Optional[str] = None
    seat: Optional[str] = None
    node_id: Optional[str] = None
    cycle: Optional[int] = None          # THIS TASK assigns it
    usage_reported: bool = True          # False => render as "—", never 0
    status: Literal["completed", "failed"] = "completed"
    error_type: Optional[str] = None

# A minimal sink to model the class on:
# packages/ai-parrot/src/parrot/observability/recorders/logging_recorder.py
class LoggingUsageRecorder(AbstractLogger):                # line 17
    def __init__(self, ...) -> None: ...                   # line 27
    async def record(self, record: UsageRecord) -> None: ...  # line 36
```

### Does NOT Exist

- ~~`RunLedgerRecorder.register()`~~ — must NOT exist. This is a **sink**, not
  an `EventProvider`. Adding `register()` would create the duplicate subscriber
  v0.3 explicitly rejected.
- ~~`RunUsageLedger`~~ — renamed. The ledger IS `RunLedgerRecorder`.
- ~~`UsageRecord.rounds`~~ — no such field. Round counts come from
  `len(cycles)` in `SeatUsage`, or from `extra_usage["rounds"]` upstream.
- ~~A persisted/Redis-backed ledger~~ — out of scope (§8 Q1). In-memory only.
- ~~`AbstractLogger.flush()`~~ — the lifecycle methods are `record()` and
  `aclose()` only.

---

## Implementation Notes

### Seat roll-up rule

`node_id` is set by the subscriber (TASK-2614). If it is missing, derive it:
`seat.split(".", 1)[0]` — so `"development.w1"` → `"development"`, and a plain
`"qa"` → `"qa"`. `by_seat()` returns **one `SeatUsage` per distinct seat**;
worker seats stay separate rows, and `node_id` is what lets the renderer group
them under their parent.

### Cycle numbering

```python
def next_cycle(self, seat: str) -> int:
    return sum(1 for r in self._records if r.seat == seat) + 1
```

Assign it in `record()` when `record.cycle is None`. `UsageRecord` is a
Pydantic model — use `record.model_copy(update={"cycle": n})`; do not mutate
the incoming instance, which other sinks in the same fan-out also hold.

**Concurrency**: a pool wave dispatches workers concurrently, but each worker
is a *distinct seat*, so they never contend on the same counter. Retries of the
same seat are sequential by construction. A `threading.Lock` around the append
is still cheap insurance and matches `UsageRecordingSubscriber`'s own use of
one (`subscriber.py:52`).

### Never fabricate `0` (spec criterion)

Sums must skip unreported values rather than coercing:

```python
reported = [r for r in records if r.usage_reported]
input_tokens = sum(r.input_tokens for r in reported) if reported else None
```

All-unreported ⇒ `None` ⇒ the renderer prints `—`.

### Key Constraints

- Append-only. Never overwrite, never dedupe, never cap — that is the whole
  point (Finding 2).
- `record()` must never raise. The subscriber isolates sink errors
  (`subscriber.py:117`), but a ledger that throws would be logged as a broken
  backend on every call and silently lose everything.
- `aclose()` is a no-op (nothing to flush) but must be implemented —
  `AbstractLogger` declares it.
- `mark_partial(reason)` is idempotent; keep the first reason.
- Pricing is a Non-Goal: do not read or expose `cost_usd` / `cumulative_cost_usd`.

### References in Codebase

- `packages/ai-parrot/src/parrot/observability/recorders/logging_recorder.py:17` — minimal sink shape
- `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py:52` — lock usage precedent

---

## Acceptance Criteria

- [ ] `RunLedgerRecorder` subclasses `AbstractLogger` and implements
      `record()` + `aclose()`.
- [ ] It has **no** `register()` method.
- [ ] Two records for the same seat get `cycle` 1 then 2, and **both are
      retained** — `by_seat()` sums them (Finding 2 guard).
- [ ] A `development.w1` record is kept as its own seat with
      `node_id == "development"` (Finding 3 guard).
- [ ] Sums skip `usage_reported=False` records; all-unreported yields `None`,
      never `0`.
- [ ] Failed records are retained, counted in `SeatUsage.failures`, and their
      tokens still contribute.
- [ ] `mark_partial("...")` sets `partial=True` and keeps the first reason.
- [ ] The incoming `UsageRecord` is not mutated (other sinks share it).
- [ ] `record()` does not raise on a malformed record.
- [ ] `from parrot.observability.recorders import RunLedgerRecorder, SeatUsage` works.
- [ ] `pytest packages/ai-parrot/tests/observability/test_run_ledger_recorder.py -v` passes.
- [ ] `ruff check` and `mypy` clean on the new file.

---

## Test Specification

```python
# packages/ai-parrot/tests/observability/test_run_ledger_recorder.py
import pytest

from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.run_ledger import RunLedgerRecorder


def _rec(seat, node_id, inp, out, *, reported=True, status="completed"):
    return UsageRecord(
        provider="anthropic", model="claude-opus-5", seat=seat, node_id=node_id,
        input_tokens=inp, output_tokens=out, usage_reported=reported, status=status,
    )


async def test_ledger_accumulates_across_cycles():
    """Regression guard for FEAT-479 Finding 2 — session state overwrote:
        after round 1: in=1000 out=500
        after round 2: in=2000 out=700   <- round 1 erased
    Appending must instead total 3000/1200."""
    led = RunLedgerRecorder(run_id="run-1")
    await led.record(_rec("development", "development", 1000, 500))
    await led.record(_rec("development", "development", 2000, 700))
    (seat,) = led.by_seat()
    assert [c.cycle for c in seat.cycles] == [1, 2]
    assert seat.input_tokens == 3000
    assert seat.output_tokens == 1200


async def test_ledger_records_pool_worker_seat():
    """Regression guard for Finding 3 — 'development.w1' could not exist as a
    NodeId, so pool telemetry was silently dropped."""
    led = RunLedgerRecorder(run_id="run-1")
    await led.record(_rec("development.w1", "development", 100, 50))
    await led.record(_rec("development.w2", "development", 200, 60))
    seats = {s.seat: s for s in led.by_seat()}
    assert set(seats) == {"development.w1", "development.w2"}
    assert all(s.node_id == "development" for s in seats.values())


async def test_ledger_never_fabricates_zero():
    led = RunLedgerRecorder(run_id="run-1")
    await led.record(_rec("qa", "qa", 0, 0, reported=False))
    (seat,) = led.by_seat()
    assert seat.input_tokens is None      # not 0
    assert seat.output_tokens is None


async def test_failed_record_retained_and_counted():
    led = RunLedgerRecorder(run_id="run-1")
    await led.record(_rec("qa", "qa", 900, 100, status="failed"))
    (seat,) = led.by_seat()
    assert seat.failures == 1
    assert seat.input_tokens == 900       # tokens burned before failing


async def test_does_not_mutate_incoming_record():
    led = RunLedgerRecorder(run_id="run-1")
    rec = _rec("qa", "qa", 1, 1)
    await led.record(rec)
    assert rec.cycle is None              # the sink copied, not mutated


async def test_mark_partial_is_idempotent():
    led = RunLedgerRecorder(run_id="run-1")
    led.mark_partial("resumed in a new process")
    led.mark_partial("something else")
    assert led.partial is True
    assert led.partial_reason == "resumed in a new process"


async def test_has_no_register_method():
    """v0.3: this is a SINK. A register() would recreate the duplicate
    subscriber the spec rejected."""
    assert not hasattr(RunLedgerRecorder(run_id="r"), "register")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 Data Models B and §3 Module 4b
2. **Check dependencies** — TASK-2614 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `AbstractLogger`'s abstract
   methods and the fields TASK-2614 added
4. **Update status** in `sdd/tasks/index/devflow-telemetry-accounting.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2615-run-ledger-recorder.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-31
**Notes**: Created `RunLedgerRecorder(AbstractLogger)` and `SeatUsage`
(frozen, `extra="forbid"` Pydantic model) in new
`recorders/run_ledger.py`. `record()` assigns `cycle` via `next_cycle(seat)`
only when the incoming record's `cycle is None`, copies via
`record.model_copy(update=...)` (never mutates the shared incoming
instance), appends under a `threading.Lock` (matching
`UsageRecordingSubscriber`'s own lock precedent), and never raises —
wrapped in `try/except Exception` with `logger.exception` (no bare
`pass`, since `ruff` doesn't have `BLE001` enabled project-wide but
silent swallowing without logging is still worse practice). `by_seat()`
groups by seat, rolls up `node_id` (from the record's own `node_id`,
falling back to `seat.split(".", 1)[0]`), sums `input_tokens`/
`output_tokens` skipping `usage_reported=False` records (`None` when the
seat's cycles are entirely unreported — never a fabricated `0`), and
counts `status="failed"` cycles into `failures`. `mark_partial()` is
idempotent (keeps the first reason). No `register()` method exists — this
is a sink, not an `EventProvider`, confirmed by
`test_has_no_register_method`. Exported `RunLedgerRecorder`/`SeatUsage`
from `recorders/__init__.py` (also fixed the pre-existing unsorted
`__all__` while adding the two new names, since `ruff`'s `RUF022`
flagged the block I was editing anyway). Wrote 11 unit tests in
`test_run_ledger_recorder.py` — the 7 from the task's Test Specification
verbatim, plus 4 extra covering a record without any seat at all,
`next_cycle`'s 1-based/seat-scoped counting in isolation, that the public
`records` property returns a defensive copy, and that `aclose()` is a
genuine no-op — all pass. Since this is a brand-new file with no
pre-existing style debt to match, wrote it fully `ruff`-clean (modern
`list`/`X | None` typing throughout, sorted `__all__`, no unused `noqa`)
rather than importing `Optional`/`List` the way older files in this
package do — a deliberate departure from the "match existing convention"
precedent set in TASK-2612/2613/2614, justified because there IS no
existing convention *in this specific file* to match; `mypy` and `ruff`
both clean. Full `tests/observability/` + `tests/unit/observability/`
suite (198 tests) passes.

**Deviations from spec**: none.
