---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus

**Feature ID**: FEAT-479
**Date**: 2026-08-31
**Author**: Jesus Lara
**Status**: approved
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
| Accounting | "what did this run cost, by seat and cycle?" | existing `UsageRecordingSubscriber` + a new `AbstractLogger` sink | extend |
| Observability | "spans, counters, traces" | global registry (OTel) | wiring fix |

> **v0.3 amendment — reuse, do not rebuild.** An earlier draft of this spec
> proposed a new `RunUsageSubscriber` with its own `UsageRecord`/`SeatUsage`/
> `RunUsageLedger` models. That was **wrong**: `parrot/observability/recorders/`
> already implements this exact pipeline —
>
> ```
> AfterClientCallEvent → UsageRecordingSubscriber → UsageRecord
>                          → fan-out to N AbstractLogger sinks
>                             (logging, openlit, prometheus)
> ```
>
> — with cost calculation, provider normalization and error-isolated fan-out
> already solved (`recorders/subscriber.py:30`, `recorders/models.py:22`,
> `recorders/base.py:16`). The proposed `UsageRecord` was also a direct **name
> collision** with the existing one. This feature therefore **extends** that
> pipeline through its designed extension point — `AbstractLogger` — instead of
> creating a parallel one.

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

**Scope: per-run only** (§8 Q1/Q2, resolved). The run's
`UsageRecordingSubscriber` — the one carrying the `RunLedgerRecorder` sink —
is registered on the per-run registry and **never on the global registry**.
This does not disturb the *existing* global `UsageRecordingSubscriber`
registered by `bootstrap.py:138`: the two instances carry different
`recorders` lists, so the global one keeps feeding logging/openlit/prometheus
while the per-run one feeds only this run's ledger. They do not double-count,
because each fans out to its own sinks.
Long-lived aggregate metrics are already `MetricsSubscriber`'s
responsibility (`observability/subscribers/metrics.py:50`, globally
registered today); a second global accumulator would duplicate it with
weaker fire-and-forget delivery and would make per-run totals
unreproducible — defeating the point of this feature. Cross-run
aggregation is done by querying emitted `usage.json` artifacts, not by a
second live subscriber.

**Seat attribution.** A `current_run_id` / `current_seat` ContextVar
pair, read at event-construction time, following the FEAT-228 precedent
already established by `current_agent_name` / `current_user_id` /
`current_session_id` (`observability/context.py:42-53`). This is how
`development.w1` becomes a first-class seat **without widening
`NodeId`**.

### Component Diagram

```
                 ┌──────────────────── per-run EventRegistry ────────────────────┐
                 │                                                               │
 AbstractClient ─┤ await emit(AfterClientCallEvent) ─┐                           │
 (in-process,    │                                   │                           │
  already emits) │                                   │                           │
                 │                                   ▼                           │
 LLMCodeDispatch ┤ await emit(...)  [M3: +tokens] ──→ UsageRecordingSubscriber ───┼─→ RunLedgerRecorder
 (tool loop)     │                                   (EXISTING, reused;          │   (NEW AbstractLogger
                 │                                    per-run instance,          │    sink — the per-run
 CLI dispatchers ┤ await emit(...)  [M6: after       │  cost_calculator=None)     │    ledger, M4b)
 (claude/codex/  │   ResultMessage harvest]       ───┘         │                 │
  agy)           │                                             │ builds          │
                 │                                             ▼                 │
 AgentsFlow ─────┤ FlowLifecycleAdapter → Node*Event      UsageRecord             │
 (4 builders, M1)│                                        (EXISTING, extended    │
                 │                                         with run/seat/cycle,  │
                 │                                         M4a)                  │
                 └────────────────────────┬──────────────────────────────────────┘
                                          │ forward_to_global()  (unchanged)
                                          ▼
                    global registry → MetricsSubscriber (OTel)
                                    → GenAIOpenTelemetrySubscriber
                                    → UsageRecordingSubscriber  (EXISTING global
                                       instance, bootstrap.py:138 — untouched;
                                       its own sinks: logging/openlit/prometheus)

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

**A. Extend the EXISTING `UsageRecord`** (`observability/recorders/models.py:22`)
— additive, defaulted fields only, so the three existing recorders
(logging/openlit/prometheus) keep working unchanged:

```python
# parrot/observability/recorders/models.py  — MODIFY, do not recreate
class UsageRecord(BaseModel):
    # ... all existing fields unchanged (provider, client_name, model,
    #     input_tokens, output_tokens, cost_usd, cumulative_cost_usd,
    #     duration_ms, finish_reason, trace_id, service_name, timestamp,
    #     and the total_tokens computed_field) ...

    # ── NEW (FEAT-479): flow attribution. All optional/defaulted. ──
    run_id: Optional[str] = None
    seat: Optional[str] = None       # "development", "development.w1", "qa"
    node_id: Optional[str] = None    # roll-up owner: "development.w1" -> "development"
    cycle: Optional[int] = None      # 1-based attempt index within (run_id, seat)

    # ── NEW: honesty + failure ──
    # The existing handler coerces unreported tokens to 0
    # (`event.input_tokens or 0`, subscriber.py:79-80). Prometheus/OpenLit
    # need real ints, so the 0-coercion STAYS. This flag preserves the
    # distinction the report needs: False => the provider reported nothing,
    # so the report renders `—` instead of a fabricated 0.
    usage_reported: bool = True
    status: Literal["completed", "failed"] = "completed"
    # Exception CLASS NAME only — never the message. The module's privacy
    # contract (models.py:8-11) forbids content in this record; error text
    # lives in session state (NodeState.error / DispatchState.last_error),
    # which the run bundle already renders.
    error_type: Optional[str] = None
```

**B. New sink** — the per-run ledger is an `AbstractLogger`, the pipeline's
designed extension point (`recorders/base.py:16`):

```python
# parrot/observability/recorders/run_ledger.py  (NEW)
class RunLedgerRecorder(AbstractLogger):
    """In-memory, append-only per-run ledger. Cycles accumulate because
    appends accumulate — nothing is ever overwritten."""

    def __init__(self, run_id: str) -> None: ...

    async def record(self, record: UsageRecord) -> None: ...   # AbstractLogger
    async def aclose(self) -> None: ...                        # AbstractLogger

    @property
    def records(self) -> list[UsageRecord]: ...
    def by_seat(self) -> list["SeatUsage"]: ...
    def next_cycle(self, seat: str) -> int: ...
    # §8 Q1: set when a resumed run finds no ledger for its run_id, so the
    # report SAYS "partial" rather than printing a total that silently omits
    # pre-park usage.
    def mark_partial(self, reason: str) -> None: ...
    partial: bool
    partial_reason: str


class SeatUsage(BaseModel):
    """Roll-up of one seat across its cycles. Report-facing only."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    seat: str
    node_id: str
    provider: str = ""
    model: str = ""
    cycles: list[UsageRecord] = Field(default_factory=list)
    # Sums skip unreported values rather than coercing (FEAT-405 convention).
    input_tokens: int | None = None
    output_tokens: int | None = None
    rounds: int | None = None
    failures: int = 0
```

### New Public Interfaces

```python
# parrot/observability/context.py  (additive)
current_run_id: ContextVar[Optional[str]]
current_seat: ContextVar[Optional[str]]

@contextmanager
def usage_attribution(run_id: Optional[str], seat: Optional[str]) -> Iterator[None]:
    """Bind run/seat attribution for events emitted inside this block."""


# parrot/observability/recorders/run_ledger.py  (NEW — a SINK, not a subscriber)
class RunLedgerRecorder(AbstractLogger):
    """Per-run in-memory usage ledger. See §2B for the full interface.

    NOT an EventProvider — it has no register(). The EXISTING
    UsageRecordingSubscriber (recorders/subscriber.py:30) owns the
    subscription and fans records out to this sink.
    """
    def __init__(self, run_id: str) -> None: ...
    async def record(self, record: UsageRecord) -> None: ...

# Wiring (M5) — reuse, no new subscriber class:
#   recorder = RunLedgerRecorder(run_id)
#   subscriber = UsageRecordingSubscriber(
#       recorders=[recorder], cost_calculator=None,   # pricing is a Non-Goal
#   )
#   per_run_registry.add_provider(subscriber)          # NEVER the global registry
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

### Module 4a: Extend `UsageRecord` + record failed calls
- **Path**: `parrot/observability/recorders/models.py`,
  `parrot/observability/recorders/subscriber.py` (both MODIFY)
- **Responsibility**: Add the additive fields in §2A to the **existing**
  `UsageRecord`. In `UsageRecordingSubscriber`: populate `run_id`/`seat`/
  `node_id` from the Module 2 ContextVars (falling back to `None`), set
  `usage_reported=False` when the event reported neither token count, and
  **also subscribe `ClientCallFailedEvent`** (`register()`,
  `subscriber.py:63` currently subscribes only `AfterClientCallEvent`) so a
  failed call is recorded with `status="failed"` and its `error_type`.
  Existing recorders must keep passing unchanged.
- **Depends on**: Module 2.

### Module 4b: `RunLedgerRecorder` sink
- **Path**: `parrot/observability/recorders/run_ledger.py` (new),
  `parrot/observability/recorders/__init__.py` (export)
- **Responsibility**: The `AbstractLogger` implementation in §2B. Assigns
  `cycle` via `next_cycle(seat)` at record time, exposes `by_seat()` for the
  report, and carries the `partial`/`mark_partial()` state from §8 Q1.
  Must NOT subscribe to anything itself — it is a sink, and
  `UsageRecordingSubscriber` owns the subscription.
- **Depends on**: Module 4a.

### Module 5: Per-run registry ownership
- **Path**: `parrot/flows/dev_loop/runner.py`
- **Responsibility**: `DevLoopRunner` creates one `EventRegistry` per run and
  registers a `UsageRecordingSubscriber(recorders=[RunLedgerRecorder(run_id)])`
  on it via `add_provider` (`registry.py:200`) — **on that per-run registry
  only, never on the global one** (§8 Q2). Keeps the recorder on the
  `SessionHost` registry entry so `_close_host` can read its ledger, and
  injects the registry into the clients/dispatchers built for that run
  (`EventEmitterMixin` eager init, `mixin.py:74-82`). Must verify the
  `_client_factory` path (`llm.py:326`) actually receives it — any path
  that lazily self-creates a registry degrades to fire-and-forget and
  must be threaded explicitly. Must NOT disturb the global
  `UsageRecordingSubscriber` registered at `bootstrap.py:138`.
- **Depends on**: Module 4b.

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
| `test_ledger_accumulates_across_cycles` | M4b | **Regression guard for Finding 2.** Two cycles of 1000/500 then 2000/700 sum to `in=3000, out=1200`, with `cycle` 1 and 2 preserved. |
| `test_ledger_records_pool_worker_seat` | M4b | **Regression guard for Finding 3.** A `development.w1` seat produces a record; `node_id` rolls up to `development`. |
| `test_ledger_records_failed_call` | M4a | `ClientCallFailedEvent` yields a record with `status="failed"` and `error_type` (class name only — never the message, per the privacy contract). |
| `test_ledger_never_fabricates_zero` | M4a | An event reporting neither token count yields `usage_reported=False`, so the report renders `—` rather than a fabricated `0`. |
| `test_subscriber_registers_on_registry` | M4a | `register()` subscribes `AfterClientCallEvent` **and** `ClientCallFailedEvent`, and never `ClientStreamChunkEvent`. |
| `test_existing_recorders_unaffected` | M4a | **Back-compat guard.** Logging/OpenLit/Prometheus recorders still accept a `UsageRecord` built with none of the new fields set. |
| `test_recorder_receives_before_call_returns` | M5 | **The exactness constraint.** Awaiting `_emit_after_call` on the per-run registry leaves the ledger already populated — no sleep, no drain. |
| `test_report_renders_node_cycle_worker` | M7b | Table contains the parent node row, its cycle rows and the worker rows. |
| `test_report_failures_section` | M7b | Failed seats appear with error text and burned tokens. |
| `test_subscriber_not_registered_globally` | M5 | **§8 Q2 guard.** After a full run, no `RunLedgerRecorder` is reachable from the global registry, and the global `UsageRecordingSubscriber` from `bootstrap.py:138` is left intact. |
| `test_partial_ledger_is_labelled` | M7b | **§8 Q1 guard.** A ledger with `partial=True` renders a visible partial marker; markdown and HTML both carry it, and no total is presented as complete. |

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
def run_ledger(isolated_registry) -> RunLedgerRecorder:
    """Reuse the EXISTING subscriber; the ledger is just its sink."""
    recorder = RunLedgerRecorder(run_id="run-test")
    isolated_registry.add_provider(
        UsageRecordingSubscriber(recorders=[recorder], cost_calculator=None)
    )
    return recorder
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
- [ ] Unreported values render `—`, never `0`, in markdown and HTML — driven by
      `UsageRecord.usage_reported`, since the shared record keeps its
      `int = 0` token fields for Prometheus/OpenLit.
- [ ] No pricing or cost figure appears in any rendered output.
- [ ] **(§8 Q2)** The run's `UsageRecordingSubscriber` (the one carrying the
      `RunLedgerRecorder`) is registered on the per-run registry only, and the
      global `UsageRecordingSubscriber` from `bootstrap.py:138` is left intact
      and unmodified.
- [ ] **(v0.3)** No new subscriber class and no second `UsageRecord` model are
      introduced. `parrot/observability/subscribers/usage.py` does NOT exist;
      the ledger is an `AbstractLogger` under `recorders/`.
- [ ] **(v0.3)** The three existing recorders (logging, openlit, prometheus)
      pass unchanged against a `UsageRecord` carrying none of the new fields.
- [ ] **(§8 Q1)** A run whose ledger is missing at report time (simulating
      cross-process resume) renders a visible "partial" marker and does **not**
      print a total presented as complete.
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

# ── THE EXISTING USAGE PIPELINE THIS FEATURE EXTENDS (v0.3) ──
# packages/ai-parrot/src/parrot/observability/recorders/models.py
class UsageRecord(BaseModel):                                          # line 22
    provider: str                                                      # line 45
    client_name: str = ""                                              # line 46
    model: str = ""                                                    # line 47
    input_tokens: int = 0                                              # line 48  (NOT Optional)
    output_tokens: int = 0                                             # line 49  (NOT Optional)
    cost_usd: Optional[float] = None                                   # line 50
    cumulative_cost_usd: Optional[float] = None                        # line 51
    duration_ms: float = 0.0                                           # line 52
    finish_reason: Optional[str] = None                                # line 53
    trace_id: Optional[str] = None                                     # line 54
    service_name: str = "ai-parrot"                                    # line 55
    timestamp: datetime                                                # line 56
    @computed_field @property
    def total_tokens(self) -> int: ...                                 # line 62
    # PRIVACY CONTRACT (docstring lines 8-11): carries NO prompt/completion
    # content and NO user_id/session_id. Do not add error MESSAGES here.

# packages/ai-parrot/src/parrot/observability/recorders/base.py
class AbstractLogger(ABC):                                             # line 16
    async def record(self, record: UsageRecord) -> None: ...           # line 31 (abstract)
    async def aclose(self) -> None: ...                                # line 39

# packages/ai-parrot/src/parrot/observability/recorders/subscriber.py
class UsageRecordingSubscriber:                                        # line 30
    def __init__(self, *, recorders: list[AbstractLogger],
                 cost_calculator: Optional[CostCalculator] = None,
                 service_name: str = "ai-parrot") -> None: ...         # line 40
    @property
    def recorders(self) -> list[AbstractLogger]: ...                   # line 55
    def register(self, registry: EventRegistry) -> None: ...           # line 63
        # currently subscribes ONLY AfterClientCallEvent (line 70)
    async def _on_client_after(self, event: AfterClientCallEvent) -> None: ...  # line 76
        # NOTE line 79-80: `event.input_tokens or 0` — coerces unreported to 0.
    async def aclose(self) -> None: ...                                # line 123

# Concrete sinks already implementing AbstractLogger:
#   recorders/logging_recorder.py:17    LoggingUsageRecorder
#   recorders/openlit_recorder.py:25    OpenLitUsageRecorder
#   recorders/prometheus_recorder.py:84 PrometheusUsageRecorder
# Global registration (must NOT be disturbed):
#   observability/bootstrap.py:129 constructs, :138 get_global_registry().add_provider(subscriber)

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
| `RunLedgerRecorder` | `AbstractLogger.record()` | subclass override | `recorders/base.py:31` |
| `UsageRecordingSubscriber` | `EventRegistry.add_provider()` | provider registration (per-run registry only) | `registry.py:200` |
| M4a fields | `UsageRecord` | additive model fields | `recorders/models.py:22` |
| M4a failure path | `ClientCallFailedEvent` | new `registry.subscribe()` in `register()` | `recorders/subscriber.py:63` |
| M3 token fix | `AbstractClient._emit_after_call()` | kwargs | `clients/base.py:589` |
| M5 injection | `EventEmitterMixin` eager init | constructor | `mixin.py:74-82` |
| M6 CLI emit | `AfterClientCallEvent` | construct + await emit | `events/client.py:45` |
| M7 report | `DevLoopRunner._close_host()` | ledger lookup | `runner.py:1460` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AgentsFlow.drain_node_events()`~~ — the public name does **not** exist.
  The real method is the private `_drain_event_tasks` (`flow.py:452`), and it
  **is** already called (`flow.py:2074`). Do not add a call to it.
- ~~`parrot.observability.subscribers.usage`~~ — **do NOT create this module.**
  The `subscribers/` package holds only `trace.py` and `metrics.py`, and the
  usage pipeline does **not** live there — it lives in
  `parrot/observability/recorders/`. Extend that (M4a/M4b).
- ~~A new `RunUsageSubscriber` class~~ — **rejected in v0.3.** Use the existing
  `UsageRecordingSubscriber` (`recorders/subscriber.py:30`) with a new
  `AbstractLogger` sink. Creating a second subscriber would duplicate its cost
  calculation, provider normalization and error-isolated fan-out.
- ~~A new `UsageRecord` model~~ — **name collision.** `UsageRecord` already
  exists at `recorders/models.py:22` and is exported from
  `parrot.observability` (`__init__.py`). Extend it; do not shadow it.
- ~~`UsageRecord.input_tokens` being `Optional[int]`~~ — it is `int = 0`
  (`models.py:48`). Do NOT change its type; Prometheus/OpenLit rely on real
  ints. Use the new `usage_reported: bool` flag to distinguish "reported 0"
  from "not reported".
- ~~Putting an error *message* on `UsageRecord`~~ — forbidden by the module's
  privacy contract (`models.py:8-11`). `error_type` (class name) only.
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
- ~~A global registration of `RunUsageSubscriber`~~ — explicitly rejected (§8 Q2).
  Do NOT call `get_global_registry().add_provider(RunUsageSubscriber(...))`.
  Global aggregation belongs to `MetricsSubscriber` alone.
- ~~Ledger persistence to Redis / the session-state envelope~~ — out of scope for
  v1 (§8 Q1). Do not add a persisted ledger; call `mark_partial()` instead.

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
- **Two live `UsageRecordingSubscriber` instances (v0.3).** The global one
  (`bootstrap.py:138`) and the per-run one both handle every
  `AfterClientCallEvent` that reaches their registry. This is intended, not
  double-counting: each fans out to its own `recorders` list, so the global
  sinks and the run ledger each see the call exactly once. Do not "optimize"
  by reusing the global subscriber for the ledger — its delivery is
  fire-and-forget via `forward_to_global`, which breaks the exactness
  guarantee this feature depends on.
- **`cost_calculator` on the per-run subscriber.** Pricing is a Non-Goal, so
  construct the per-run `UsageRecordingSubscriber` with
  `cost_calculator=None`. Passing one would populate `cost_usd` and invite
  cost figures into the report.
- **`_client_factory` may not thread the registry** (`llm.py:326`). If any path
  builds a client that lazily self-creates a registry (`mixin.py:113`), that
  path silently degrades to fire-and-forget. M5 must verify this explicitly
  rather than assume it — see §8.
- **Ledger lifetime — resolved, §8 Q1.** The ledger is per-run and in-memory. A
  run parked on an ideation `open_questions` gate can resume in a **different
  process**, losing its pre-park records. This matters because ideation gates
  are the *normal* path for `new_feature`/`enhancement` briefs, so parked runs
  are long and expensive — exactly the ones worth accounting. **Decision:
  accept the loss for v1, but never hide it.** A resumed run that finds no
  ledger for its `run_id` calls `mark_partial(...)`, and the rendered report
  must carry a visible "partial" marker instead of a total that silently omits
  pre-park usage. This preserves the FEAT-405 principle already enforced for
  `—`: never print a number you cannot stand behind. Persisting the ledger
  alongside the session-state envelope is a clean additive follow-up if parked
  runs prove common.
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
- [x] Cross-process park/resume: is losing the in-memory ledger acceptable for
      v1, or must the ledger be persisted alongside the session-state envelope?
      — *Resolved*: **accept partial for v1**, on the hard condition that the
      report *labels itself partial* rather than printing a silently-wrong
      total. Persisting the ledger is an additive follow-up feature, not a
      prerequisite. Routed into §2B (`RunLedgerRecorder.partial` /
      `.partial_reason` — renamed from `RunUsageLedger` in v0.3), §5 (acceptance
      criteria), §7 (Known Risks).
- [x] Should the run's usage subscriber also be registered on the global registry for
      long-lived aggregate metrics, or is per-run scope sufficient?
      — *Resolved*: **per-run scope only.** Global aggregates are already
      `MetricsSubscriber`'s job (`metrics.py:50`, already globally registered);
      a second global accumulator would duplicate it with weaker
      (fire-and-forget) delivery and would make per-run totals unreproducible.
      Routed into §2 Overview, §3 Module 5, §5, §6 (Does NOT Exist).
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
| 0.3 | 2026-08-31 | Jesus Lara | **Corrected a false premise.** v0.1-0.2 claimed no usage-recording subscriber existed (based on `ls observability/subscribers/`, having never checked `observability/recorders/`). `UsageRecordingSubscriber`, `UsageRecord`, `AbstractLogger` and three concrete sinks already exist and already consume `AfterClientCallEvent`. Withdrew the invented `RunUsageSubscriber`/`UsageRecord` (the latter a direct name collision); the per-run ledger is now a new `AbstractLogger` sink. M4 split into M4a (extend `UsageRecord` + record failed calls) and M4b (`RunLedgerRecorder`). |
| 0.2 | 2026-08-31 | Jesus Lara | §8 Q1/Q2 resolved: ledger stays in-memory and per-run (partial runs must self-label, `RunUsageLedger.partial`); `RunUsageSubscriber` is per-run only, never global. Routed into §2, §3 M5, §4, §5, §6, §7. |
