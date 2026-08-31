# TASK-2616: Per-run EventRegistry ownership and injection

**Feature**: FEAT-479 — Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus
**Spec**: `sdd/specs/devflow-telemetry-accounting.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2615
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5. **This task carries the feature's single most
important correctness constraint.**

`EventRegistry.emit()` awaits each subscriber sequentially and never raises
(`registry.py:235-295`), so a sink subscribed on **the emitting registry** is
guaranteed complete when the emitting call returns. `AbstractClient._emit_after_call`
uses `await self.events.emit(event)` (`clients/base.py:630`) — awaited, exact.

But `forward_to_global()` (`registry.py:392`) and `emit_nowait()`
(`registry.py:366`) both schedule via `loop.create_task` — **fire-and-forget**.
A ledger reachable only through those paths races the report.

Therefore the run's ledger must hang off a registry the run **owns** and that
the run's clients/dispatchers **emit on**. That is this task.

---

## Scope

- `DevLoopRunner` creates one `EventRegistry` per run.
- Register `UsageRecordingSubscriber(recorders=[RunLedgerRecorder(run_id)],
  cost_calculator=None)` on it via `add_provider` — **that per-run registry
  only, never the global one**.
- Keep the `RunLedgerRecorder` reachable from the run's `SessionHost` registry
  entry so `_close_host` can read it.
- Inject the per-run registry into the clients/dispatchers built for the run
  (`EventEmitterMixin` eager init).
- **Resolve spec §8's open question**: read `_create_client` /
  `_client_factory` and determine whether the registry actually reaches the
  constructed client. If it does not, thread it explicitly. Record the finding
  in the Completion Note.
- Write the two unit tests below.

**NOT in scope**: the ledger itself (TASK-2615); rendering (TASK-2618/2619);
CLI dispatcher emission (TASK-2617); any change to `bootstrap.py`'s global
registration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | Per-run registry + subscriber + injection |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | Thread the registry into `_create_client` if needed |
| `packages/ai-parrot/tests/flows/dev_loop/test_per_run_registry.py` | CREATE | Exactness + scope tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: navigator_eventbus/lifecycle/registry.py:90, re-exported via the facade
from parrot.core.events.lifecycle import EventRegistry, get_global_registry
# verified: packages/ai-parrot/src/parrot/observability/recorders/subscriber.py:30
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber
# from TASK-2615:
from parrot.observability.recorders.run_ledger import RunLedgerRecorder
```

### Existing Signatures to Use

```python
# navigator_eventbus/lifecycle/registry.py
class EventRegistry:
    def __init__(self, *, event_bus=None, bus_channel_prefix="lifecycle",
                 forward_to_global: bool = True) -> None: ...    # line 104
    def add_provider(self, provider: Any) -> list[str]: ...      # line 200
        # raises TypeError if provider has no register(registry)
    async def emit(self, event) -> None: ...                     # line 235  AWAITED, exact
    def emit_nowait(self, event) -> None: ...                    # line 366  fire-and-forget
    def forward_to_global(self, event) -> None: ...              # line 392  fire-and-forget

# navigator_eventbus/lifecycle/mixin.py — THE INJECTION POINT
class EventEmitterMixin:
    _events_registry: Optional[EventRegistry]                    # line 66
    # eager initialiser, lines 74-82:
    #   self._events_registry = EventRegistry(forward_to_global=<flag>)
    @property
    def events(self) -> EventRegistry: ...                       # line 98
        # line 113: LAZILY creates EventRegistry(forward_to_global=True)
        #           when _events_registry is unset  <-- the degradation risk

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
class DevLoopRunner:
    async def _close_host(self, host, result, ctx) -> None: ...   # line 1460
        # Order: RunClosed -> terminal snapshot -> run bundle -> retention
        #        -> final RunSummaryChanged -> discard host.
        # usage.json / report written around lines 733-747.

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
    def _create_client(self, profile: LLMCodeDispatchProfile) -> Any:   # line 326
        model_args = {"temperature": profile.temperature,
                      "max_tokens": profile.max_tokens}
        return self._client_factory(profile.llm, model_args=model_args)
        # ^^^ §8 OPEN QUESTION: does the produced client receive the per-run
        #     registry, or does it lazily self-create one (mixin.py:113)?
        #     READ the factory. Do not assume.

# packages/ai-parrot/src/parrot/observability/bootstrap.py
#   line 129: constructs the GLOBAL UsageRecordingSubscriber
#   line 138: get_global_registry().add_provider(subscriber)
#   ^^^ MUST NOT be modified or bypassed by this task.
```

### Does NOT Exist

- ~~`get_global_registry().add_provider(RunLedgerRecorder(...))`~~ — forbidden
  (spec §8 Q2). Two failure modes at once: a sink is not an `EventProvider`
  (`add_provider` raises `TypeError`), and global scope was explicitly rejected.
- ~~`SessionHost.registry` / `SessionHost.ledger`~~ — verify what the runner's
  per-run host registry entry actually looks like before assuming an attribute.
  `_register_host` is the function to read.
- ~~`EventRegistry.drain()` / `.flush()`~~ — no such method. Exactness comes
  from subscribing on the emitting registry, not from draining.
- ~~`AbstractClient(events=...)` constructor kwarg~~ — verify before use; the
  documented injection point is `EventEmitterMixin`'s eager
  `_events_registry` init (`mixin.py:74-82`), not a client kwarg.

---

## Implementation Notes

### The wiring

```python
recorder = RunLedgerRecorder(run_id=rid)
subscriber = UsageRecordingSubscriber(
    recorders=[recorder],
    cost_calculator=None,      # pricing is a Non-Goal — see below
)
run_registry = EventRegistry(forward_to_global=True)
run_registry.add_provider(subscriber)
# keep `recorder` reachable from the host entry for _close_host
```

`forward_to_global=True` keeps OTel fed exactly as today. What must NOT happen
is the reverse — relying on the *global* registry to reach the ledger.

### `cost_calculator=None` is deliberate

Pricing is a spec Non-Goal. Passing a calculator would populate `cost_usd` /
`cumulative_cost_usd` and invite cost figures into the report.

### Two live subscribers is intended

The global `UsageRecordingSubscriber` (`bootstrap.py:138`) and this per-run one
both handle events reaching their own registry. Not double-counting: each fans
out to its own `recorders` list, so global sinks and the run ledger each see a
call once. **Do not "optimize"** by reusing the global subscriber — its
delivery to the ledger would be fire-and-forget, destroying the guarantee.

### Resolving the §8 open question

Read `self._client_factory`. Determine whether the constructed client's
`_events_registry` is set from the run's registry, or whether it falls through
to `mixin.py:113`'s lazy `EventRegistry(forward_to_global=True)`. If the
latter, thread the registry explicitly — otherwise `_emit_after_call` awaits
on the *wrong* registry and the ledger only ever sees fire-and-forget
forwards. **`test_recorder_receives_before_call_returns` is what proves you
got this right**; if it needs a sleep to pass, the wiring is wrong.

### Key Constraints

- One registry per run; never a module-level or class-level singleton.
- The runner already holds per-run state keyed by `rid` (`_run_completion`,
  `_active`, the host registry) — follow that existing shape.
- Park/resume: a resumed run whose recorder is missing must call
  `mark_partial(...)` (§8 Q1), not silently report a short total.
- Clean up per-run state on run close, alongside the existing
  `_run_completion.pop(rid, None)` / `_pending_gate_count.pop(rid, None)`.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:1460` — `_close_host`
- `packages/ai-parrot/src/parrot/observability/bootstrap.py:129-138` — global registration to leave alone
- `navigator_eventbus/lifecycle/mixin.py:74-82` — the injection point

---

## Acceptance Criteria

- [ ] Each run owns one `EventRegistry` with a `UsageRecordingSubscriber`
      carrying a `RunLedgerRecorder`.
- [ ] The recorder is reachable from the run's host entry at `_close_host` time.
- [ ] **Exactness**: after `await client._emit_after_call(...)` on the per-run
      registry, the ledger already holds the record — verified with **no sleep
      and no drain** in the test.
- [ ] No `RunLedgerRecorder` is reachable from the global registry.
- [ ] The global `UsageRecordingSubscriber` from `bootstrap.py:138` is intact
      and unmodified after a run.
- [ ] The per-run subscriber is constructed with `cost_calculator=None`.
- [ ] The §8 open question is answered in the Completion Note, with the file
      and line that settles it.
- [ ] Per-run state is released on run close (no leak across runs).
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes.
- [ ] `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_per_run_registry.py
import pytest

from parrot.core.events.lifecycle import EventRegistry, get_global_registry
from parrot.observability.recorders.run_ledger import RunLedgerRecorder
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber


async def test_recorder_receives_before_call_returns():
    """THE exactness constraint. emit() awaits subscribers sequentially
    (registry.py:264-266), so the ledger must be populated the instant the
    emitting call returns — no sleep, no drain. If this test needs either,
    the ledger is on the wrong registry and accounting will race the report."""
    ledger = RunLedgerRecorder(run_id="run-1")
    registry = EventRegistry(forward_to_global=False)
    registry.add_provider(
        UsageRecordingSubscriber(recorders=[ledger], cost_calculator=None)
    )

    await registry.emit(_after_call_event(input_tokens=10, output_tokens=5))

    assert len(ledger.records) == 1      # NO await asyncio.sleep(0) here


async def test_subscriber_not_registered_globally(dev_loop_runner, brief):
    """Spec §8 Q2: per-run scope only, and the global pipeline untouched."""
    before = len(get_global_registry()._subscriptions)
    await dev_loop_runner.run(brief)
    after = get_global_registry()._subscriptions

    assert len(after) == before, "a per-run subscription leaked to the global registry"
    for sub in after:
        target = getattr(sub.callback, "__self__", None)
        recorders = getattr(target, "recorders", []) or []
        assert not any(isinstance(r, RunLedgerRecorder) for r in recorders), \
            "a RunLedgerRecorder is reachable from the global registry"
```

**Note**: the second test reaches into `EventRegistry._subscriptions` — private,
but there is no public introspection API, and asserting per-run scope is worth
the coupling. If a public accessor exists by implementation time, prefer it.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 Exactness and §3 Module 5
2. **Check dependencies** — TASK-2615 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — especially `_client_factory` and
   `_register_host`; this task's correctness turns on them
4. **Update status** in `sdd/tasks/index/devflow-telemetry-accounting.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met — the exactness test in particular
7. **Move this file** to `sdd/tasks/completed/TASK-2616-per-run-event-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** — including the §8 open-question answer

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**§8 open question — does `_client_factory` propagate the injected registry?**
*(answer here, with file:line evidence)*

**Deviations from spec**: none | describe if any
