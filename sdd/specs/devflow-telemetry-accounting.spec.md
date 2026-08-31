---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus

**Feature ID**: FEAT-479
**Date**: 2026-08-31
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.29.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`dev_loop` and `dev_flow` report per-run usage through
`parrot/flows/dev_loop/usage_report.py` (FEAT-405), which reads token
counters off `DispatchState` in session state. That accounting is
**inaccurate in four independent, empirically verified ways**, and the
FEAT-176 lifecycle telemetry bus — which already carries exactly the
data needed — is wired into only one of the four flow graph builders.

Verified findings (each reproduced against the current `dev` tree):

1. **The lifecycle adapter is attached in 1 of 4 graph builders.**
   `build_dev_loop_flow` attaches `FlowLifecycleAdapter`
   (`flows/dev_loop/flow.py:443-447`); the feature-mode builder
   (`flows/dev_loop/runner.py:177`), the revision builder
   (`runner.py:292`) and the entire dev-flow builder
   (`flows/dev_flow/flow.py:148`) do not. Consequence: **dev-flow emits
   zero lifecycle events** — no OTel spans, no `NodeFailedEvent`, no
   observer visibility. `grep -rn observability packages/ai-parrot/src/parrot/flows/`
   returns nothing.

2. **Retry rounds overwrite instead of accumulate.** `_with_dispatch`
   (`session_state.py:711`) merges into a single `DispatchState` per
   node, so a second `dispatch/completed` replaces the first's token
   counts. Reproduced:

   ```
   after round 1: in=1000 out=500 turns=3
   after round 2: in=2000 out=700 turns=3      # round 1 erased
   (true cumulative: in=3000 out=1200 turns=6)
   ```

   Every `development → qa → feedback_router → development` retry cycle
   discards the prior round's usage.

3. **Pool-worker usage is silently discarded.** `DevAgentPool` dispatches
   under `worker_id="development.w{i}"` (`agent_pool.py:149`), but
   `NodeId` (`session_state.py:140`) is a closed `Literal` of 15 node
   names. `action_from_dispatch_event` therefore raises `ValidationError`
   for `development.w1`, and `_apply_to_session_host`
   (`dispatchers/_shared.py:53-74`) swallows it at DEBUG "so the shim
   must never break a dispatch". Reproduced: `development` maps to a
   `DispatchCompleted`; `development.w1` raises. **All fan-out
   development work reports zero tokens.**

4. **The authoritative client event carries no tokens.**
   `LLMCodeDispatcher._safe_emit_after_call` (`dispatchers/llm.py:483-495`)
   invokes `client._emit_after_call(...)` with `client_name`, `model` and
   `duration_ms` only — it never passes `input_tokens`/`output_tokens`,
   although `_emit_after_call` accepts both (`clients/base.py:589`) and
   `_extract_usage` sits at `llm.py:497`. The one *awaited* (therefore
   exactly-delivered) LLM-call event thus always reports `None` tokens.

Two things that look like gaps but are **not**, confirmed by reading the
source — recorded here so implementation does not "fix" them:

- Direct `AbstractClient.ask()` calls (e.g. the research-node log
  summarizer, `nodes/research.py:911,953`) are **already instrumented**:
  `clients/base.py` emits `AfterClientCallEvent` and `ClientRoundEvent`
  for every client. No node-level plumbing is required for them.
- The end-of-run event barrier **already exists and is already called**:
  `AgentsFlow._drain_event_tasks` (`flow.py:452`) is awaited at
  `flow.py:2074`, immediately before `run_flow` returns. Terminal
  `node_failed` events land before the caller snapshots.

### Goals

- Attach `FlowLifecycleAdapter` in **all four** flow graph builders, so
  `dev_flow` and every `dev_loop` topology emit lifecycle events.
- Produce an **accurate** end-of-run usage measurement: totals that
  accumulate across retry cycles and include pool-worker seats.
- Capture the **actual LLM model** used per seat, as data rather than a
  pool-size-1 heuristic guess.
- Register **node and LLM-call failures** so a failed cycle is reported
  with its error *and* the tokens it burned before failing.
- Report at **node → cycle → worker** granularity.
- Build entirely on the existing FEAT-176 lifecycle bus. Introduce no
  parallel telemetry substrate.

### Non-Goals (explicitly out of scope)

- **Pricing / cost figures.** Consistent with the FEAT-405 Non-Goal;
  `total_cost_usd` may pass through where a provider reports it, but no
  price table or cost computation is introduced.
- **Changing `session_state.py`'s schema.** `DispatchState`, `NodeState`
  and `NodeId` are untouched. Session state remains the *live UI*
  projection (latest attempt per node); accounting moves to the bus.
  Finding 2's overwrite is therefore left in place by design — it is
  correct behaviour for a "current state" view.
- **Migrating to the `unified-telemetry-bus` spec.** This feature is
  deliberately independent of it and would become a projection source
  for it later, not an obstacle.
- **Per-chunk streaming accounting.** `ClientStreamChunkEvent` is never
  subscribed (cardinality guard, matching `MetricsSubscriber`).

---

## 2. Architectural Design

### Overview

Three planes, separated by the question each answers. The core insight
is that today all three questions are asked of one overwritten
`DispatchState` field, which is why retries clobber, workers vanish and
dev-flow is invisible.

| Plane | Question | Substrate | Change |
|---|---|---|---|
| Live UI | "what is node X doing now?" | `DevLoopSessionState` | **none** |
| Accounting | "what did this run cost, by seat and cycle?" | lifecycle bus + `RunUsageSubscriber` | new |
| Observability | "spans, counters, traces" | global registry (OTel) | wiring fix |

Accounting keys off `AfterClientCallEvent`, which already carries
`model`, `input_tokens`, `output_tokens` and `client_name`
(`core/events/lifecycle/events/client.py:45-75`). No new usage payload
model is invented.

> **Lifecycle events are frozen `@dataclass`es, not Pydantic models**
> (verified: `dataclasses.is_dataclass(AfterClientCallEvent) is True`,
> `frozen=True`, MRO `AfterClientCallEvent → LifecycleEvent → ABC`).
> Construct them positionally/by keyword and serialize with the provided
> `to_dict()`. Do **not** call `.model_dump()` / `.model_validate()` on
> them. The new ledger models in this spec *are* Pydantic — the two must
> not be conflated.

**Exactness.** `EventRegistry.emit()` awaits each subscriber
sequentially in registration order and never raises
(`registry.py:235-295`; errors isolate into `SubscriberErrorEvent`).
`AbstractClient._emit_after_call` uses `await self.events.emit(event)`
(`clients/base.py:630`). Therefore a recorder subscribed on **the
emitting registry** is guaranteed complete before the client call
returns. By contrast `forward_to_global()` (`registry.py:392`) and
`emit_nowait()` (`registry.py:366`) schedule via `loop.create_task` and
are fire-and-forget. **The recorder must be subscribed on the per-run
registry, never only on the global one** — this is the single most
important correctness constraint in this spec.

Consequently `ClientRoundEvent` (emitted via `emit_nowait`,
`clients/base.py:582`) is treated as **best-effort enrichment**;
the awaited `AfterClientCallEvent` is the authoritative per-call record.

**Seat attribution.** A `current_run_id` / `current_seat` ContextVar
pair, read at event-construction time, following the FEAT-228 precedent
already established by `current_agent_name` / `current_user_id` /
`current_session_id` (`observability/context.py:42-53`). This is how
`development.w1` becomes a first-class seat **without widening
`NodeId`**.

### Component Diagram

```
                    ┌───────────────── per-run EventRegistry ─────────────────┐
                    │                                                          │
 AbstractClient ────┤ await emit(AfterClientCallEvent)  ──→ RunUsageSubscriber │──→ RunUsageLedger
 (in-process)       │                                            │             │      (per run_id)
                    │                                            │             │
 LLMCodeDispatcher ─┤ await emit(AfterClientCallEvent)           │             │
 (tool loop)        │   [M3: now WITH tokens]                    │             │
                    │                                            │             │
 CLI dispatchers ───┤ await emit(AfterClientCallEvent)           │             │
 (claude/codex/agy) │   [M6: after ResultMessage harvest]        │             │
                    │                                            │             │
 AgentsFlow ────────┤ FlowLifecycleAdapter → Node*Event ─────────┘             │
 (4 builders, M1)   │                                                          │
                    └──────────────────────┬───────────────────────────────────┘
                                           │ forward_to_global()  (unchanged)
                                           ▼
                              global registry → MetricsSubscriber (OTel)
                                             → GenAIOpenTelemetrySubscriber

  run close → build_usage_report(ledger) → usage.json / markdown / HTML
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `EventRegistry` | uses | per-run instance; recorder subscribed on it for awaited delivery |
| `EventEmitterMixin` | uses | eager `_events_registry` init is the injection point (`mixin.py:74-82`) |
| `FlowLifecycleAdapter` | attaches | in the 3 builders currently missing it |
| `AfterClientCallEvent` | consumes | authoritative per-call usage record |
| `ClientRoundEvent` | consumes | best-effort per-round enrichment |
| `ClientCallFailedEvent` | consumes | failed-call accounting |
| `MetricsSubscriber` | pattern | `EventProvider.register(registry)` shape copied verbatim |
| `LLMCodeDispatcher` | modifies | `_safe_emit_after_call` gains token args |
| `build_usage_report` | rewrites | reads ledger instead of `snapshot.state.nodes` |
| `DevLoopRunner._close_host` | modifies | builds report from the run's ledger |
| `DevLoopSessionState` | **untouched** | live-UI projection only |

### Data Models

```python
# parrot/observability/subscribers/usage.py

class UsageRecord(BaseModel):
    """One completed or failed LLM call, attributed to a seat and cycle."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    seat: str            # free string: "development", "development.w1",
                         # "research", "qa" — deliberately NOT NodeId
    node_id: str         # owning node, for roll-up ("development.w1" -> "development")
    cycle: int           # 1-based attempt index within (run_id, seat)
    provider: str = ""   # sourced from AfterClientCallEvent.client_name
                         # (there is NO `provider` field on the event)
    model: str = ""
    status: Literal["completed", "failed"] = "completed"
    error_type: str = ""
    error_message: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    rounds: int | None = None
    duration_ms: float | None = None


class SeatUsage(BaseModel):
    """Accumulated usage for one seat across all its cycles."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    seat: str
    node_id: str
    provider: str = ""
    model: str = ""
    cycles: list[UsageRecord] = Field(default_factory=list)
    # Sums skip None rather than coercing to 0 (FEAT-405 convention).
    input_tokens: int | None = None
    output_tokens: int | None = None
    rounds: int | None = None
    failures: int = 0


class RunUsageLedger(BaseModel):
    """Append-only per-run ledger. Cycles accumulate because appends do."""
    model_config = ConfigDict(extra="forbid")

    run_id: str
    records: list[UsageRecord] = Field(default_factory=list)

    def append(self, record: UsageRecord) -> None: ...
    def by_seat(self) -> list[SeatUsage]: ...
    def next_cycle(self, seat: str) -> int: ...
```

### New Public Interfaces

```python
# parrot/observability/context.py  (additive)
current_run_id: ContextVar[Optional[str]]
current_seat: ContextVar[Optional[str]]

@contextmanager
def usage_attribution(run_id: Optional[str], seat: Optional[str]) -> Iterator[None]:
    """Bind run/seat attribution for events emitted inside this block."""


# parrot/observability/subscribers/usage.py
class RunUsageSubscriber:
    """EventProvider that accumulates a per-run usage ledger.

    Implements the EventProvider Protocol: synchronous ``register(registry)``,
    matching ``MetricsSubscriber`` (metrics.py:175).
    """
    def __init__(self, run_id: str) -> None: ...
    def register(self, registry: EventRegistry) -> None: ...
    @property
    def ledger(self) -> RunUsageLedger: ...
```

---

## 3. Module Breakdown

### Module 1: Attach the lifecycle adapter in every builder
- **Path**: `parrot/flows/dev_loop/runner.py`, `parrot/flows/dev_flow/flow.py`
- **Responsibility**: Add the `lifecycle_events: bool = True` parameter and
  the `FlowLifecycleAdapter` attachment to the three builders missing it
  (`runner.py:177`, `runner.py:292`, `dev_flow/flow.py:148`), mirroring
  `dev_loop/flow.py:443-447` exactly, including `flow._lifecycle_adapter`.
- **Depends on**: nothing. Independently shippable and independently valuable.

### Module 2: Seat/run attribution ContextVars
- **Path**: `parrot/observability/context.py`
- **Responsibility**: Add `current_run_id`, `current_seat` and the
  `usage_attribution()` context manager, following the existing
  `agent_identity()` shape (`context.py:55`). Export from
  `parrot/observability/__init__.py` alongside `current_agent_name`
  (`__init__.py:49`).
- **Depends on**: nothing.

### Module 3: Carry tokens on the dispatcher's after-call event
- **Path**: `parrot/flows/dev_loop/dispatchers/llm.py`
- **Responsibility**: Accumulate per-round usage across the tool loop
  (`_extract_usage`, `llm.py:497` already parses it per turn) and pass
  `input_tokens`/`output_tokens` into `_safe_emit_after_call`
  (`llm.py:483`), which forwards them to `_emit_after_call`. Fixes
  Finding 4. **Standalone bug fix** — valuable even without the rest.
- **Depends on**: nothing.

### Module 4: `RunUsageSubscriber` + ledger
- **Path**: `parrot/observability/subscribers/usage.py` (new)
- **Responsibility**: The models in §2 plus the `EventProvider`. Subscribes
  `AfterClientCallEvent`, `ClientCallFailedEvent`, `ClientRoundEvent`,
  `NodeStartedEvent`, `NodeFailedEvent`, `NodeCompletedEvent`. Derives
  `cycle` at append time from `ledger.next_cycle(seat)`. Reads seat/run
  from the Module 2 ContextVars, falling back to the event's `node_id`.
  Update the `subscribers/__init__.py` docstring listing.
- **Depends on**: Module 2.

### Module 5: Per-run registry ownership
- **Path**: `parrot/flows/dev_loop/runner.py`
- **Responsibility**: `DevLoopRunner` creates one `EventRegistry` per run,
  registers a `RunUsageSubscriber` on it via `add_provider`
  (`registry.py:200`), keeps it on the `SessionHost` registry entry, and
  injects it into the clients/dispatchers built for that run
  (`EventEmitterMixin` eager init, `mixin.py:74-82`). Must verify the
  `_client_factory` path (`llm.py:326`) actually receives it — any path
  that lazily self-creates a registry degrades to fire-and-forget and
  must be threaded explicitly.
- **Depends on**: Module 4.

### Module 6: CLI dispatchers emit after harvest
- **Path**: `parrot/flows/dev_loop/dispatchers/` (claude-code / codex / agy paths)
- **Responsibility**: `claude-code`, `codex` and `agy` run out-of-process and
  have no `AbstractClient`. After the existing TASK-1927 `ResultMessage`
  telemetry harvest, emit an `AfterClientCallEvent` carrying the harvested
  model and token counts, inside a `usage_attribution(run_id, seat)` block
  where `seat` is the dispatch's `node_id` — which is `development.w1` for a
  pool worker. Resolves Findings 1 (pool workers) and the model gap without
  touching `NodeId`.
- **Depends on**: Modules 2, 5.

### Module 7: Rebuild the usage report on the ledger
- **Path**: `parrot/flows/dev_loop/usage_report.py`, `run_bundle.py`, `runner.py`
- **Responsibility**: `build_usage_report(ledger, run_id)` replaces the
  `Snapshot`-reading builder (`usage_report.py:104`). Render node → cycle →
  worker in markdown and HTML, keeping the `—`-for-unreported convention
  (never fabricate `0`). Add a **Failures** section enumerating failed seats
  and cycles with error text and the tokens burned before failing. **Delete**
  `_single_worker_summary_for_node` (`usage_report.py:79`) and its
  pool-size-1 guess — model now arrives as data.
- **Depends on**: Modules 4, 5.

### Module 8: Documentation
- **Path**: `docs/dev_loop/`
- **Responsibility**: Document the three planes, the awaited-vs-fire-and-forget
  delivery rule, and how to add a new subscriber.
- **Depends on**: Modules 1–7.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_all_builders_attach_lifecycle_adapter` | M1 | **Regression guard for Finding 1.** Parametrized over all four builders; asserts `flow._lifecycle_adapter` is a `FlowLifecycleAdapter`. This is what stops the drift recurring. |
| `test_builders_honour_lifecycle_events_false` | M1 | `lifecycle_events=False` leaves `_lifecycle_adapter` None in all four. |
| `test_usage_attribution_binds_and_restores` | M2 | ContextVar set inside the block, restored after, including on exception. |
| `test_dispatcher_after_call_carries_tokens` | M3 | **Regression guard for Finding 4.** Asserts the emitted `AfterClientCallEvent` has non-None `input_tokens`/`output_tokens`. |
| `test_ledger_accumulates_across_cycles` | M4 | **Regression guard for Finding 2.** Two cycles of 1000/500 then 2000/700 sum to `in=3000, out=1200`, with `cycle` 1 and 2 preserved. |
| `test_ledger_records_pool_worker_seat` | M4 | **Regression guard for Finding 3.** A `development.w1` seat produces a record; `node_id` rolls up to `development`. |
| `test_ledger_records_failed_call` | M4 | `ClientCallFailedEvent` yields `status="failed"` with error text and any tokens burned. |
| `test_ledger_never_fabricates_zero` | M4 | Unreported counts stay `None`, never `0`, in records and sums. |
| `test_subscriber_registers_on_registry` | M4 | `register()` subscribes the documented event set and never `ClientStreamChunkEvent`. |
| `test_recorder_receives_before_call_returns` | M5 | **The exactness constraint.** Awaiting `_emit_after_call` on the per-run registry leaves the ledger already populated — no sleep, no drain. |
| `test_report_renders_node_cycle_worker` | M7 | Table contains the parent node row, its cycle rows and the worker rows. |
| `test_report_failures_section` | M7 | Failed seats appear with error text and burned tokens. |

### Integration Tests

| Test | Description |
|---|---|
| `test_dev_flow_run_produces_usage_report` | An end-to-end dev-flow run with a fake dispatcher yields a non-empty ledger — the gap that made dev-flow invisible. |
| `test_retry_cycle_totals_are_cumulative` | A run whose feedback router forces a second development cycle reports the sum of both, not the last. |
| `test_pool_run_attributes_every_worker` | A 2-worker pool wave yields two worker seats, each with its own model. |
| `test_failed_node_reported_with_usage` | A node raising mid-dispatch is reported failed, with tokens burned before the failure. |

### Test Data / Fixtures

```python
@pytest.fixture
def isolated_registry() -> EventRegistry:
    """Registry with forward_to_global=False so tests never touch the
    process-wide singleton (registry.py:98-101 documents this switch)."""
    return EventRegistry(forward_to_global=False)

@pytest.fixture
def ledger_subscriber(isolated_registry) -> RunUsageSubscriber:
    sub = RunUsageSubscriber(run_id="run-test")
    isolated_registry.add_provider(sub)
    return sub
```

---

## 5. Acceptance Criteria

- [ ] All four flow builders attach `FlowLifecycleAdapter` by default, proven
      by a parametrized test over the four builder callables.
- [ ] A dev-flow run produces a non-empty usage ledger (today it produces none).
- [ ] Two dispatch cycles on one seat report the **sum** of both cycles;
      `test_ledger_accumulates_across_cycles` asserts `in=3000, out=1200`.
- [ ] A pool wave with N workers yields N worker seats, each with its model.
- [ ] `AfterClientCallEvent` emitted by `LLMCodeDispatcher` carries non-None
      token counts.
- [ ] The ledger is fully populated when `await _emit_after_call(...)` returns,
      with no drain or sleep in the test.
- [ ] Every failed node and failed LLM call appears in the report with its
      error and the tokens burned before failing.
- [ ] Unreported values render `—`, never `0`, in markdown and HTML.
- [ ] No pricing or cost figure appears in any rendered output.
- [ ] `session_state.py` is unmodified (`git diff --stat` shows no change) —
      no `NodeId` widening, no `DispatchState` field added.
- [ ] Existing FEAT-405 tests (`test_usage_report.py`,
      `test_usage_report_html.py`) pass or are updated with a stated rationale.
- [ ] `pytest packages/ai-parrot/tests/flows/ packages/ai-parrot/tests/observability/ -v` passes.
- [ ] `ruff check` and `mypy` clean on all changed files.
- [ ] Docs updated in `docs/dev_loop/`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/bots/flows/__init__.py:82,147
from parrot.bots.flows import FlowLifecycleAdapter
# verified: packages/ai-parrot/src/parrot/bots/flows/flow/telemetry.py:48
from parrot.bots.flows.flow.telemetry import FlowLifecycleAdapter

# verified: packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py (re-export facade)
from parrot.core.events.lifecycle import EventRegistry, LifecycleEvent, TraceContext
from parrot.core.events.lifecycle import get_global_registry

# verified: packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py:45,80,189
from parrot.core.events.lifecycle.events.client import (
    AfterClientCallEvent, ClientCallFailedEvent, ClientRoundEvent,
)
# verified: packages/ai-parrot/src/parrot/core/events/lifecycle/events/flow.py
from parrot.core.events.lifecycle.events.flow import (
    NodeCompletedEvent, NodeFailedEvent, NodeStartedEvent,
)

# verified: packages/ai-parrot/src/parrot/observability/__init__.py:49
from parrot.observability.context import agent_identity, current_agent_name
```

### Existing Class Signatures

```python
# navigator_eventbus/lifecycle/registry.py  (source of truth:
#   /home/jesuslara/proyectos/navigator-eventbus/src/navigator_eventbus/lifecycle/registry.py
#   — byte-identical to the installed copy in .venv, verified via diff)
class EventRegistry:
    def __init__(self, *, event_bus=None, bus_channel_prefix="lifecycle",
                 forward_to_global: bool = True) -> None: ...          # line 104
    def subscribe(self, event_type, callback, *, where=None,
                  forward_to_bus: bool = False) -> str: ...            # line 121
    def unsubscribe(self, subscription_id: str) -> bool: ...           # line 159
    def has_subscribers(self, event_type) -> bool: ...                 # line 175
    def add_provider(self, provider: Any) -> list[str]: ...            # line 200
    async def emit(self, event: LifecycleEvent) -> None: ...           # line 235  AWAITED, sequential, never raises
    def emit_nowait(self, event: LifecycleEvent) -> None: ...          # line 366  FIRE-AND-FORGET
    def forward_to_global(self, event: LifecycleEvent) -> None: ...    # line 392  FIRE-AND-FORGET (create_task)

# navigator_eventbus/lifecycle/mixin.py
class EventEmitterMixin:
    _events_registry: Optional[EventRegistry]                          # line 66
    # eager init (the injection point):                                 # lines 74-82
    @property
    def events(self) -> EventRegistry: ...                             # line 98 (lazily creates forward_to_global=True)

# packages/ai-parrot/src/parrot/bots/flows/flow/telemetry.py
class FlowLifecycleAdapter:
    def __init__(self, *, registry: Optional[EventRegistry] = None) -> None:  # line 62
    def __call__(self, event: str, node_id: str, info: Dict[str, Any]) -> None:  # line 72
    # NOTE: uses emit_nowait (line 93) — node events are NOT awaited-exact.

# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow:
    def add_node_event_listener(self, callback) -> None: ...           # line 400 (sync OR async callable)
    async def _drain_event_tasks(self, timeout: float = 5.0) -> None:  # line 452
    # called at line 2074, immediately before `return aggregated` in run_flow.

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
# NOTE: these are FROZEN DATACLASSES, not Pydantic models. Verified:
#   dataclasses.is_dataclass(AfterClientCallEvent) is True; frozen=True;
#   MRO = AfterClientCallEvent -> LifecycleEvent -> ABC -> object.
#   They expose to_dict(); they do NOT expose model_dump/model_validate/model_fields.
@dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent):                            # line 45
    client_name: str                   # the provider identifier — there is NO `provider` field
    model: str = ""                                                    # line 69
    input_tokens: Optional[int] = None                                 # line 71
    output_tokens: Optional[int] = None                                # line 72
class ClientCallFailedEvent(LifecycleEvent): ...                       # line 80
class ClientRoundEvent(LifecycleEvent): ...                            # line 189

# packages/ai-parrot/src/parrot/clients/base.py
    def _emit_round_event(self, ...) -> None: ...                      # line 511; emit_nowait @582, forward_to_global @587
    async def _emit_after_call(self, tc, *, client_name: str, model: str,
                               duration_ms: float,
                               input_tokens: Optional[int] = None,
                               output_tokens: Optional[int] = None,
                               finish_reason: Optional[str] = None) -> None:  # line 589
                               # await self.events.emit(event) @630; forward_to_global @634
    async def _emit_failed_call(self, tc, *, client_name: str, ...) -> None:  # line 636

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
    async def _safe_emit_after_call(self, client, tc, *, model: str,
                                    duration_ms: float) -> None:       # line 483
                                    # BUG (Finding 4): no token args forwarded
    @staticmethod
    def _extract_usage(response) -> tuple[Optional[CompletionUsage], Optional[Dict]]:  # line 497
    def _create_client(self, profile) -> Any: ...                      # line 326 (self._client_factory)

# packages/ai-parrot/src/parrot/observability/subscribers/metrics.py
class MetricsSubscriber:                                               # line 50
    def register(self, registry: "EventRegistry") -> None: ...         # line 175 (EventProvider, SYNC)

# packages/ai-parrot/src/parrot/observability/context.py
current_agent_name: ContextVar[Optional[str]]                          # line 42
current_user_id: ContextVar[Optional[str]]                             # line 46
current_session_id: ContextVar[Optional[str]]                          # line 50
@contextmanager
def agent_identity(name: Optional[str]) -> Iterator[None]: ...         # line 55

# packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py
def _single_worker_summary_for_node(node_id, shared) -> Any | None: ...  # line 79  → TO DELETE
def build_usage_report(snapshot, run_id, *, shared=None) -> UsageReport: ...  # line 104 → TO REWRITE
def render_usage_markdown(report) -> str: ...                          # line 210
def render_usage_html(report) -> str: ...                              # line 293

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py  (READ-ONLY for this feature)
NodeId = Literal[...]                                                  # line 140 (15 names, closed)
class DispatchState(_Frozen): ...                                      # line 188 (no `model` field)
def _with_dispatch(state, node_id, **changes): ...                     # line 711 (merges → overwrites)
def action_from_dispatch_event(kind, node_id, ts, payload): ...        # line 1278

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py
def _apply_to_session_host(event: DispatchEvent) -> None: ...          # line 53 (swallows at DEBUG, line 70-74)

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class WorkerSummary(BaseModel):                                        # line 470
    worker_id: str   # "development.w1"                                # line 478
    agent: str                                                         # line 479
    model: str                                                         # line 480
    # NOTE: carries NO token fields.

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
    async def _close_host(self, host, result, ctx) -> None: ...        # line 1460
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| M1 builders | `AgentsFlow.add_node_event_listener()` | method call | `bots/flows/flow/flow.py:400` |
| M1 builders | pattern to copy | reference impl | `flows/dev_loop/flow.py:443-447` |
| `RunUsageSubscriber` | `EventRegistry.subscribe()` | `register(registry)` | `registry.py:121`, pattern `metrics.py:175` |
| `RunUsageSubscriber` | `EventRegistry.add_provider()` | provider registration | `registry.py:200` |
| M3 token fix | `AbstractClient._emit_after_call()` | kwargs | `clients/base.py:589` |
| M5 injection | `EventEmitterMixin` eager init | constructor | `mixin.py:74-82` |
| M6 CLI emit | `AfterClientCallEvent` | construct + await emit | `events/client.py:45` |
| M7 report | `DevLoopRunner._close_host()` | ledger lookup | `runner.py:1460` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AgentsFlow.drain_node_events()`~~ — the public name does **not** exist.
  The real method is the private `_drain_event_tasks` (`flow.py:452`), and it
  **is** already called (`flow.py:2074`). Do not add a call to it.
- ~~`parrot.observability.subscribers.usage`~~ — does not exist yet (M4 creates it).
  The package currently contains only `trace.py` and `metrics.py`.
- ~~`DispatchState.model`~~ — no `model` field exists (`session_state.py:188-213`).
- ~~`WorkerSummary.input_tokens` / `.output_tokens`~~ — no token fields (`models/base.py:470-483`).
- ~~`current_run_id` / `current_seat`~~ — do not exist yet (M2 creates them).
- ~~`usage_attribution()`~~ — does not exist yet (M2 creates it).
- ~~Any import of `parrot.observability` under `parrot/flows/`~~ — there are
  currently **zero**; the flows package is entirely unwired from observability.
- ~~A cost/pricing table anywhere in `parrot/flows/`~~ — does not exist and is a Non-Goal.
- ~~`AfterClientCallEvent.provider`~~ — no such field. The provider identifier is
  `client_name`. Verified via `dataclasses.fields()`.
- ~~`AfterClientCallEvent.model_dump()` / `.model_fields`~~ — lifecycle events are
  frozen dataclasses, not Pydantic. Use `to_dict()`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `EventProvider` protocol: a **synchronous** `register(registry)` that calls
  `registry.subscribe(...)`, exactly as `MetricsSubscriber.register`
  (`metrics.py:175`).
- ContextVar attribution: mirror `agent_identity()` (`context.py:55`) —
  `set` a token, `reset` it in a `finally`.
- Read ContextVars at **event-construction time, not emit time**. `clients/base.py`
  documents this explicitly (FEAT-228 comments at lines ~578 and ~625): the
  dispatch may leave the calling coroutine.
- Never fabricate `0` for unreported values — `None` renders `—` (FEAT-405
  convention, `usage_report.py:_fmt_value`).
- Telemetry must never break a run: subscriber exceptions already isolate into
  `SubscriberErrorEvent` (`registry.py:267-273`); do not add `raise` paths.
- async/await throughout; `self.logger`, not `print`.

### Known Risks / Gotchas

- **Awaited vs fire-and-forget is the whole correctness story.** A recorder
  registered only on the *global* registry receives events via
  `loop.create_task` and may not have run when the report is built. Register
  on the per-run registry. `test_recorder_receives_before_call_returns` is the
  guard.
- **`FlowLifecycleAdapter` itself uses `emit_nowait`** (`telemetry.py:93`), so
  node events are not awaited-exact. This is acceptable: node events supply
  *structure* (which seats existed, which failed), while token *totals* come
  from the awaited client events. `_drain_event_tasks` (`flow.py:2074`) already
  bounds the node-event race before `run_flow` returns.
- **Client registries are isolated** (`forward_to_global=False`) and forward
  explicitly (`clients/base.py:634`). Injecting a per-run registry must not
  disable that forwarding, or OTel loses LLM events.
- **`_client_factory` may not thread the registry** (`llm.py:326`). If any path
  builds a client that lazily self-creates a registry (`mixin.py:113`), that
  path silently degrades to fire-and-forget. M5 must verify this explicitly
  rather than assume it — see §8.
- **Ledger lifetime.** The ledger is per-run and in-memory. A run parked on an
  ideation `open_questions` gate can resume in a different process, losing it.
  Scope decision: accept partial loss on cross-process resume for v1 and state
  it in the report rather than silently under-reporting. See §8.
- **Cycle numbering under concurrency.** A pool wave dispatches workers
  concurrently; `next_cycle(seat)` must be computed per distinct seat, and
  distinct workers are distinct seats, so concurrent waves do not contend.
  Retries of the *same* seat are sequential by construction.
- Do not "fix" the `DispatchState` overwrite (Finding 2) — it is the correct
  behaviour for a live-state view and is an explicit Non-Goal.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-eventbus` | existing pin | `EventRegistry`, `EventEmitterMixin`, `LifecycleEvent` |
| `opentelemetry-*` | existing pin | already used by `metrics.py` / `trace.py`; no new dependency |

No new third-party dependency is introduced.

---

## 8. Open Questions

- [ ] Does `LLMCodeDispatcher._client_factory` (`llm.py:326`) propagate an
      injected `EventRegistry` to the constructed client, or does the client
      lazily self-create one (`mixin.py:113`)? If the latter, M5 must thread it
      explicitly. **Must be resolved by reading the factory during M5 — not
      assumed.** — *Owner: implementer*
- [ ] Cross-process park/resume: is losing the in-memory ledger acceptable for
      v1 (report states "partial — run resumed in a new process"), or must the
      ledger be persisted alongside the session-state envelope? — *Owner: Jesus*
- [ ] Should `RunUsageSubscriber` also be registered on the global registry for
      long-lived aggregate metrics, or is per-run scope sufficient? — *Owner: Jesus*
- [ ] Do `codex` and `agy` dispatchers expose model identity in their
      terminal payload, or only `claude-code`? If a backend cannot report a
      model, the seat renders `—` rather than guessing. — *Owner: implementer*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree, tasks sequential.
- Rationale: M4 → M5 → M6/M7 form a hard dependency chain, so cross-task
  parallelism would mostly block.
- **Independently shippable early** (no dependency on the chain; could land
  first to deliver value immediately):
  - **M1** (attach the adapter) — fixes the dev-flow blind spot alone.
  - **M3** (token args) — a standalone bug fix.
  - **M2** (ContextVars) — pure addition.
- **Cross-feature dependencies**: none. Deliberately independent of the
  `unified-telemetry-bus` spec (`sdd/specs/unified-telemetry-bus.spec.md`);
  this ledger would become a projection source for it, not a conflict.

```bash
git worktree add -b feat-479-devflow-telemetry-accounting \
  .claude/worktrees/feat-479-devflow-telemetry-accounting origin/dev
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-31 | Jesus Lara | Initial draft — findings 1–4 verified empirically against `dev`; two suspected gaps (direct `client.ask`, event drain) disproved by source reading and recorded as non-gaps. |
