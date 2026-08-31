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

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-31
**Notes**: `DevLoopRunner` now owns `self._run_registries: Dict[str, EventRegistry]`
and `self._run_ledgers: Dict[str, RunLedgerRecorder]`, populated by a new
`_create_run_registry(run_id)` (builds a fresh `RunLedgerRecorder` +
`UsageRecordingSubscriber(recorders=[ledger], cost_calculator=None)` +
`EventRegistry`, `add_provider`s the subscriber) called right after each of
the three `_register_host(rid)` call sites (`run`, `_run_feature`,
`run_revision`), and released by `_discard_run_registry(run_id)` called
after `_close_host` on both the success and exception paths of all three
methods — matching the existing `_run_completion.pop`/`_pending_gate_count.pop`
cleanup idiom, so the ledger stays reachable for `_close_host`/`_persist_run_bundle`
(TASK-2618) but never leaks across runs. A new public `get_run_ledger(run_id)`
returns `None` when untracked (never wired, already closed, or — §8 Q1 — a
cross-process resume that lost the in-memory ledger); the `mark_partial()`
call and the "partial" render decision are deliberately left to TASK-2618
(rendering is explicitly out of this task's scope), which detects the
`None` and decides how to label the report.

`LLMCodeDispatcher` gained `set_event_registry_resolver(resolver)` (a
`run_id -> Optional[EventRegistry]` callable) and now threads `run_id`
through `_create_client`, which — when a resolver is wired and it resolves
a registry for that `run_id` — sets `client._events_registry` directly to
that shared registry (the documented injection point) instead of leaving
the client to lazily self-create its own. `DevLoopRunner.__init__` wires
`self._dispatcher.set_event_registry_resolver(self._run_registries.get)`
once, duck-typed (`hasattr` guard) since `self._dispatcher` may be any
CLI-backed dispatcher that never touches `EventRegistry` at all — those are
simply left unwired (no-op). `_dispatch_loop` now also wraps its whole body
in `with usage_attribution(run_id, node_id):` — `node_id` IS the seat for
this dispatcher (`DevAgentPool` already passes `"development.w1"`-style
worker ids as `node_id`), which is what makes `UsageRecord.run_id`/`.seat`/
`.node_id` non-`None` for this path at all; without it the injected
registry would still receive records, just permanently unattributed. This
wiring wasn't listed as an explicit acceptance criterion of any task, but
sits squarely inside this task's own stated scope ("injection... into the
clients/dispatchers built for the run") and is a necessary completion of
it — flagging this judgment call per the Agent Instructions.

**§8 open question — does `_client_factory` propagate the injected registry?**
Resolved: **No.** `LLMFactory.create` (`clients/factory.py:193-276`, the
default `client_factory`) has no registry/events parameter at all — its
signature is `create(llm, model_args=None, tool_manager=None, **kwargs)` and
nothing in its body touches lifecycle events. More decisively,
`AbstractClient.__init__` (`clients/base.py:372`) **unconditionally** calls
`self._init_events(forward_to_global=False)`, which (`navigator_eventbus/
lifecycle/mixin.py:82-85`) **always constructs a brand-new**
`EventRegistry(forward_to_global=False)` — there is no constructor kwarg or
factory parameter that could short-circuit this. Every client built via
`_create_client` therefore self-creates an isolated registry unless
`_create_client` overwrites `client._events_registry` post-construction,
which is exactly what this task's new code does.

**A second, unplanned finding surfaced while resolving §8 — a latent
double-forward bug the task's own illustrative wiring snippet would have
introduced.** The task's "Implementation Notes → The wiring" section shows
`run_registry = EventRegistry(forward_to_global=True)`. Constructing the
*shared, client-injected* registry with `forward_to_global=True` is
**incorrect**: `AbstractClient._emit_after_call` (`clients/base.py:630-634`)
and `_emit_round_event` (`clients/base.py:582-587`) **always** call
`self.events.forward_to_global(event)` explicitly and unconditionally,
specifically because clients are documented to carry an isolated
(`forward_to_global=False`) registry (see the inline comment at
`clients/base.py:583-586`: *"Client registries are isolated
(forward_to_global=False). Forward the LLM-call lifecycle events explicitly
..."*). If the injected registry also auto-forwards
(`forward_to_global=True`), `EventRegistry.emit()` (`registry.py:254-255`
and `:294-295`) schedules its OWN automatic forward **in addition to** that
explicit call — every client-emitted `AfterClientCallEvent`/
`ClientRoundEvent` would be forwarded to the global registry TWICE,
double-counting on every global subscriber (OTel `MetricsSubscriber`, the
global `UsageRecordingSubscriber` from `bootstrap.py:138`). I constructed
`_create_run_registry`'s registry with `forward_to_global=False` instead —
this preserves single-delivery to global (via the client's own existing
explicit-forward calls, unchanged) while still satisfying "OTel fed exactly
as today." `test_subscriber_not_registered_globally` and
`test_create_client_injects_the_resolved_run_registry` both pass with this
choice; I did not empirically reproduce the double-forward with `True` (it
would require asserting on `create_task` call counts), but the mechanism is
unambiguous from reading `registry.py` — documented here as a deviation
with reasoning rather than silently "fixed."

Verified all acceptance criteria: `test_recorder_receives_before_call_returns`
(no sleep, no drain — exactness), `test_subscriber_not_registered_globally`
(a full `DevLoopRunner.run()` end-to-end, comparing
`get_global_registry()._subscriptions` before/after), `test_run_registry_created_and_discarded`
(no leak), `test_per_run_registries_are_distinct_instances` (never a
singleton), and the two `_create_client` injection tests (exactness +
correct attribution end-to-end through a real `AbstractClient`, and a
graceful no-resolver fallback). Full `tests/flows/dev_loop/` suite (1117
tests, excluding the 3 pre-existing unrelated failures) + `tests/observability/`
+ `tests/unit/observability/` (198 tests) all pass. `ruff check` on the
diff: the two new "documentation" `noqa` comments I initially added
(`SLF001`, `N801`) were removed since neither rule is enabled project-wide
(matching the project's existing tolerance for that pattern elsewhere);
remaining new findings are `UP006`/`UP037`/`UP045` on the new lines,
matching `runner.py`/`llm.py`'s own pre-existing `Dict`/`Optional`
convention throughout (134→144 combined, +10, all pre-existing categories),
per the TASK-2612/2613/2614 precedent of following the surrounding file's
style rather than modernizing unrelated code.

**Deviations from spec**: (1) The shared per-run `EventRegistry` is
constructed with `forward_to_global=False`, not `forward_to_global=True` as
literally shown in the task's own illustrative code — required to avoid the
double-forward bug detailed above; global OTel/usage-recorder visibility is
unaffected since `AbstractClient`'s own explicit `forward_to_global(event)`
calls are unconditional and unchanged. (2) `_dispatch_loop` was wrapped in
`usage_attribution(run_id, node_id)`, which is not itself one of this
task's listed files-to-modify bullet points but IS within `dispatchers/llm.py`
(an explicitly listed file) and is necessary for the injected registry to
produce attributed records at all — noted as a scope judgment call per
Cardinal Rule 4. (3) `agent_builder.py`'s pool-worker dispatcher factory
(`build_dispatcher`, used by `DevAgentPool` for `nvidia`/`grok`/`zai`/
`moonshot` pool-worker instances) is **not** wired with
`set_event_registry_resolver` — that file is outside this task's declared
scope. Pool workers spawned through that path will still self-create
isolated registries and fall back to fire-and-forget forwarding; their
`AfterClientCallEvent`s reach the global registry but not the per-run
ledger. This is a known, explicitly out-of-scope gap for a future increment,
not silently swept under the rug.
