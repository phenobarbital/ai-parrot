# Dev-flow / dev-loop telemetry accounting

FEAT-479 closed dev-flow's telemetry blind spot (zero lifecycle events)
and fixed three accounting defects in dev-loop's per-run usage report:
retry cycles overwrote each other, pool-worker seats were silently
dropped, and the one *awaited* (therefore exactly-delivered) LLM-call
event reported `None` tokens. This document is the operator/implementer
reference for the result: which plane answers which question, which
event-delivery paths are safe to build accounting on, how to add a usage
sink, and how seat attribution works. See
[`sdd/specs/devflow-telemetry-accounting.spec.md`](../../sdd/specs/devflow-telemetry-accounting.spec.md)
for the full rationale, the verified findings, and the FEAT-405 R4
override this feature deliberately makes.

## The one rule that matters: awaited vs. fire-and-forget

Everything else in this document follows from one fact about the
lifecycle bus (`navigator_eventbus.lifecycle.registry.EventRegistry`,
installed at `.venv/lib/python3.12/site-packages/navigator_eventbus/
lifecycle/registry.py`):

| Path | Delivery | Safe for accounting? |
|---|---|---|
| `await registry.emit(event)` on the registry an emitter *itself* holds | awaited, sequential, subscriber errors isolate into `SubscriberErrorEvent` rather than propagating (`registry.py:235`, error isolation `:273`) | ✅ yes |
| `registry.emit_nowait(event)` | schedules `loop.create_task(self.emit(event))` — fire-and-forget (`registry.py:366`) | ❌ no |
| `registry.forward_to_global(event)` | same — `loop.create_task` (`registry.py:392`) | ❌ no |

**Rule**: if a subscriber's data must be complete at a known point (e.g.
when a run closes and a report is built), it must be subscribed on the
registry that the emitter *awaits `emit()` on* — never only on the global
registry, and never relying on `emit_nowait()`/`forward_to_global()` to
have already run by the time you read state. This is why FEAT-479 gives
every run its own `EventRegistry` (Module 5, below) instead of relying on
the global one.

Two concrete consequences worth knowing cold:

- `AbstractClient._emit_after_call` (the authoritative per-call usage
  event) does `await self.events.emit(event)` — exact
  (`clients/base.py:630`). `_emit_round_event` (per-round enrichment) uses
  `self.events.emit_nowait(event)` — best-effort (`clients/base.py:582`).
  Client registries are themselves constructed with
  `forward_to_global=False` (`clients/base.py:372`) and forward to the
  global registry **explicitly**, at the end of both methods
  (`clients/base.py:634` and `:587`) — so a client's own registry never
  auto-forwards; the explicit call is the only path to global.
- `FlowLifecycleAdapter` (node lifecycle → typed events) uses
  `emit_nowait` (`bots/flows/flow/telemetry.py:93`). Node events therefore
  supply *structure* (which seats existed, which failed) on a
  best-effort basis; token *totals* come from the awaited client events.
  The end-of-run barrier `AgentsFlow._drain_event_tasks`
  (`bots/flows/flow/flow.py:452`) is already awaited at
  `bots/flows/flow/flow.py:2074`, immediately before `run_flow` returns,
  which bounds (but does not make exact) the node-event race.

## The three planes

One overwritten `DispatchState` field used to answer three different
questions at once, which is exactly why retries clobbered totals, pool
workers vanished, and dev-flow went dark — one write-once slot cannot
serve "what is happening now," "what did this cost," and "trace/span
data" simultaneously. FEAT-479 splits them:

| Plane | Question | Substrate | FEAT-479 touched it? |
|---|---|---|---|
| Live UI | "What is node X doing right now?" | `DevLoopSessionState` (`flows/dev_loop/session_state.py`) | **No** — untouched by design; still the live-state projection, still overwrites on retry (correct for "what's happening now") |
| Accounting | "What did this run cost, by seat and cycle?" | `UsageRecordingSubscriber` → `RunLedgerRecorder` (per-run, append-only) | **Yes** — this feature |
| Observability | "Spans, counters, traces" | Global `EventRegistry`, OTel subscribers (`MetricsSubscriber`, `GenAIOpenTelemetrySubscriber`) | Wiring fix only (Module 1) — no new observability substrate |

`session_state.py` is genuinely unmodified by this feature (`git diff
--stat` against it is empty) — the live-UI plane was never the problem;
conflating it with accounting was.

## The usage pipeline already existed — read this before adding anything

**The single most useful sentence in this document**: the usage-recording
pipeline lives under `parrot/observability/recorders/`, **not**
`parrot/observability/subscribers/` (which holds only `trace.py` and
`metrics.py`). This spec's own first two drafts proposed rebuilding the
whole thing from scratch — a new subscriber class plus a second, colliding
usage-record model — because `ls observability/subscribers/` looked like
the complete story. It wasn't — `recorders/` already had:

```
AfterClientCallEvent → UsageRecordingSubscriber → UsageRecord
                          → fan-out to N AbstractLogger sinks
                             (logging, openlit, prometheus, …)
```

- `recorders/subscriber.py:47` — `UsageRecordingSubscriber`. Implements
  the `EventProvider` protocol: a **synchronous** `register(registry)`
  (`:80`) that calls `registry.subscribe(...)`, mirroring
  `MetricsSubscriber.register`. FEAT-479 extended it (Module 4a) to also
  subscribe `ClientCallFailedEvent` and to populate `run_id`/`seat`/
  `node_id`/`usage_reported` from context.
- `recorders/models.py:22` — `UsageRecord`. The normalized, PII-free
  record (privacy contract in the module docstring, `models.py:8-11`: no
  prompt/completion content, no `user_id`/`session_id`). FEAT-479 added
  additive, defaulted-only fields: `run_id`, `seat`, `node_id`, `cycle`,
  `usage_reported`, `status`, `error_type` — the three existing recorders
  below still accept a record built with none of them set.
- `recorders/base.py:16` — `AbstractLogger`, the extension point.
  `record(record: UsageRecord)` (`:31`, abstract) and `aclose()` (`:39`).
- Existing sinks: `recorders/logging_recorder.py:17`
  (`LoggingUsageRecorder`), `recorders/openlit_recorder.py:25`
  (`OpenLitUsageRecorder`), `recorders/prometheus_recorder.py:84`
  (`PrometheusUsageRecorder`).
- The **global** registration lives at `observability/bootstrap.py:138`
  (`get_global_registry().add_provider(subscriber)`, constructed at
  `:129`) — FEAT-479 never touches it. It keeps feeding logging/openlit/
  prometheus exactly as before.

### Adding a new usage consumer

Implement `AbstractLogger` and register it through the **existing**
`UsageRecordingSubscriber` — never write a second subscriber. That is
precisely how FEAT-479 itself added the per-run ledger (Module 4b, next
section): `recorders/run_ledger.py`'s `RunLedgerRecorder` is a sink, not a
subscriber — it has no `register()` method at all, by design (adding one
would recreate the duplicate-subscriber design this feature explicitly
rejected).

```python
class MyRecorder(AbstractLogger):
    async def record(self, record: UsageRecord) -> None: ...
    async def aclose(self) -> None: ...

subscriber = UsageRecordingSubscriber(recorders=[MyRecorder()], cost_calculator=None)
registry.add_provider(subscriber)   # the registry the emitter awaits emit() on
```

## The per-run ledger (Module 4b/5)

`recorders/run_ledger.py:65` — `RunLedgerRecorder(AbstractLogger)`. In
memory, append-only, one instance per run:

- `record()` (`:102`) assigns a 1-based `cycle` via `next_cycle(seat)`
  (`:97`) when the incoming record's `cycle` is unset, and appends a
  **copy** (`model_copy`) rather than mutating the shared incoming
  `UsageRecord` — other sinks in the same fan-out hold the same instance.
  Appends never overwrite, which is what fixes the retry-overwrite defect:
  two cycles for the same seat both survive and both sum.
- `by_seat()` (`:134`) rolls every retained record up into one
  `SeatUsage` (`run_ledger.py:30`) per distinct `seat`. Sums skip
  `usage_reported=False` records rather than coercing — an all-unreported
  seat totals `None`, never a fabricated `0`.
- `mark_partial(reason)` (`:125`) is idempotent (keeps the first reason) —
  see "Cross-process resume" below.

**`DevLoopRunner` owns one `EventRegistry` + one `RunLedgerRecorder` per
run** — `runner.py`'s `_create_run_registry` (`:514`) builds
`EventRegistry(forward_to_global=False)`, wraps the ledger in a
`UsageRecordingSubscriber(recorders=[ledger], cost_calculator=None)`
(pricing is a Non-Goal), and `add_provider`s it — **never on the global
registry**. `_discard_run_registry` (`:544`) releases both after the run
closes (called from `run()`/`_run_feature()`/`run_revision()`/
`DevFlowRunner.run()`, on both the success and exception paths — every one
of these methods duplicates this pairing rather than sharing a base-class
hook, because `DevFlowRunner.run()` is a **full override** of
`DevLoopRunner.run()`, not a call to `super().run()`; wiring it in only
three of the four call sites was an actual bug caught by FEAT-479's own
integration tests — see TASK-2620's Completion Note).

The registry is constructed with `forward_to_global=False`, matching a
client's own default (`clients/base.py:372`) — **not** `True`. Setting it
`True` would double-schedule the forward to global for every
client-emitted event once the registry is injected as the client's own
(`AbstractClient` always calls `forward_to_global()` explicitly and
unconditionally regardless of the flag), double-counting on every global
subscriber. `get_run_ledger(run_id)` (`runner.py:549`) returns the
tracked ledger or `None`.

### Injection: why a client can't just receive the registry as a constructor arg

`AbstractClient.__init__` **unconditionally** calls
`self._init_events(forward_to_global=False)` (`clients/base.py:372`),
which always constructs a **brand-new, isolated** `EventRegistry` — there
is no constructor kwarg or client-factory parameter that can short-circuit
this (verified by reading `clients/factory.py`'s `LLMFactory.create`
signature, which has none). `LLMCodeDispatcher._create_client`
(`flows/dev_loop/dispatchers/llm.py`) therefore threads the run's registry
in explicitly, **after** construction, by overwriting
`client._events_registry` — the documented injection point — once
`set_event_registry_resolver` (wired once by `DevLoopRunner.__init__`) has
resolved it for the current `run_id`. `ClaudeCodeDispatcher`
(`dispatchers/claude.py`) exposes the identical `set_event_registry_
resolver` method shape (`:138`) even though it never builds an
`AbstractClient` at all — see the out-of-process section below.

## Seat attribution

A **seat** is the accounting unit: a flow node id (`"qa"`) or a
pool-worker id (`"development.w1"`). It is deliberately a **free
string**, not `flows.dev_loop.session_state.NodeId` — a closed `Literal`
of 15 fixed flow-node names. `DevAgentPool` dispatches under
`worker_id="development.w1"`/`"development.w2"`/… (`agent_pool.py:149`),
which cannot validate against that closed `Literal`; the dual-publish
shim `_apply_to_session_host` (`dispatchers/_shared.py`) swallows the
resulting `ValidationError` at DEBUG "so the shim must never break a
dispatch," and every pool worker's telemetry vanished silently. Seats
sidestep this entirely — no `NodeId` widening required, and none is
planned.

`current_run_id`/`current_seat` (`observability/context.py:132`, `:136`)
are task-local `ContextVar`s, following the exact FEAT-228 precedent
already established by `current_agent_name`/`current_user_id`/
`current_session_id` (`context.py:56`, `:60`, `:64`). `usage_attribution
(run_id, seat)` (`context.py:142`) binds both with token-based `set()`/
`reset()`, mirroring `agent_identity`/`invocation_context` (`:70`, `:98`).
`UsageRecordingSubscriber._on_client_after`/`_on_client_failed` read these
ContextVars **at record-build time** — inside the handler invoked
synchronously by `await registry.emit(event)` — not at event-construction
time, which is why the attribution block must still be active when the
awaited emit resolves.

`node_id` — the roll-up owner a seat belongs to — is derived as
`seat.split(".", 1)[0]` when not already present on the event
(`subscriber.py`'s `_node_id_from_seat` helper), so `"development.w1"`
rolls up to `"development"` for report grouping while remaining its own
row.

### In-process clients: `LLMCodeDispatcher`

`_dispatch_loop` wraps its whole body in `with usage_attribution(run_id,
node_id):` — `node_id` *is* the seat here, since `DevAgentPool` already
passes `"development.w1"`-style worker ids as `node_id` into `dispatch()`.

### Out-of-process dispatchers: `claude-code`, `codex`, `agy`/`google_coding`

These run as external processes — there is no `AbstractClient`, so none
of `clients/base.py`'s lifecycle emission happens. `ClaudeCodeDispatcher`
mines the terminal `ResultMessage` for usage
(`_extract_result_usage`, pre-existing TASK-1927 harvest) and, when a
resolver is wired and the harvest reports something,
`_emit_usage_event` (`dispatchers/claude.py:749`) constructs and
`await`s an `AfterClientCallEvent` on the run's registry inside
`usage_attribution(run_id, seat=node_id)`, then explicitly calls
`registry.forward_to_global(event)` — mirroring
`AbstractClient._emit_after_call` (`clients/base.py:634`), since the
per-run registry is `forward_to_global=False` — routing this backend's
usage through the identical accounting path as in-process clients, with
no fabricated zeros when the harvest reports nothing.

Every one of `dispatch()`'s failure branches (timeout, session exception,
an `is_error` `ResultMessage` the SDK doesn't raise on, and output
validation failure) also routes through `_emit_failure_event`
(`dispatchers/claude.py:806`): harvest whatever usage the buffered
messages report (often partial, sometimes none, for a genuine failure),
emit that as a normal `AfterClientCallEvent` if anything was reported,
then emit a `ClientCallFailedEvent` for the failure itself — two ledger
records rather than one, since `ClientCallFailedEvent` structurally
carries no token fields (see "Reading a report," below, for how both
surface in the rendered Failures section).

`codex` and `google_coding` currently have **no usage harvest at all** —
verified by grepping both dispatcher modules for any token/cost/
`ResultMessage` handling; there is none to route. Building one is a
follow-up feature, not part of this one; those two backends' seats render
`—` for tokens until it exists.

## FEAT-405 R4 — deliberately overridden, once

FEAT-405 (`novaclient-dev-loop.brainstorm.md:107-111`, R4) forbids "a
summing loop inside any dev-loop dispatcher." FEAT-479 Module 3
(`flows/dev_loop/dispatchers/llm.py`, the comment at `:225`-`:239`)
overrides this **for the after-call event only**: `LLMCodeDispatcher`
never calls `AbstractClient.ask()` (FEAT-405's own "Gap B"), so its
per-round events are fire-and-forget (`emit_nowait`) and cannot be relied
on for exactness. The loop now accumulates with the sanctioned
`CompletionUsage.__add__` primitive — the same mechanism FEAT-397 uses
inside `ask()` — honouring R4's *intent* (reuse, don't hand-roll) while
departing from its letter for this one path. Full rationale, rejected
alternatives, and why literal compliance was impossible:
[`sdd/specs/devflow-telemetry-accounting.spec.md`](../../sdd/specs/devflow-telemetry-accounting.spec.md)
§3 Module 3.

## Cross-process resume (§8 Q1)

The ledger is per-run and in-memory. A run parked on an `open_questions`
gate can resume in a **different process**, losing its pre-park records —
accepted for v1, on the hard condition that the report **labels itself
partial** rather than silently printing a short total as complete.
`_persist_run_bundle`'s call site constructs a fresh `RunLedgerRecorder`
and calls `mark_partial(reason)` on it when `get_run_ledger(run_id)`
returns `None`; `UsageReport.partial`/`.partial_reason` flow straight
through to both renderers, which show a `⚠️ Partial` banner above the
table and label the totals row `**Totals (partial)**` in markdown /
`Totals (partial)` in HTML.

## Reading a report

`build_usage_report(ledger, run_id)` (`flows/dev_loop/usage_report.py`)
is a pure function — no filesystem, no Redis, no network — that maps
`ledger.by_seat()` into node → cycle → worker rows. `render_usage_markdown`
/`render_usage_html` render from the same `UsageReport` model, so they
cannot disagree: seat rows, indented `└ cycle N` sub-rows (suppressed when
a seat has exactly one cycle), a **Failures** section (seat/cycle/
`error_type`/tokens burned — never an error *message*, per the privacy
contract; omitted entirely when there are no failures), and the partial
marker described above. No pricing/cost figure appears anywhere (spec
Non-Goal, unchanged from FEAT-405).

## Does NOT exist — save yourself the grep

- `parrot.observability.subscribers.usage` — never existed, never will;
  see "The usage pipeline already existed," above.
- A second, run-scoped usage subscriber class — rejected in the spec's
  v0.3 revision; use the existing `UsageRecordingSubscriber` with a new
  `AbstractLogger` sink instead (see "Adding a new usage consumer," above).
- `AgentsFlow.drain_node_events()` — the public-sounding name does not
  exist. The real method is the private `_drain_event_tasks`
  (`bots/flows/flow/flow.py:452`), and it is already awaited
  (`bots/flows/flow/flow.py:2074`).
- `DispatchState.model` — session state carries no model identity field at
  all; that absence is exactly why the report reads the ledger instead.
- `UsageRecord.cache_creation_input_tokens` / `.cache_read_input_tokens` —
  those exist on `DispatchState` (the live-UI plane) only. The FEAT-479
  report deliberately dropped these columns rather than mixing planes.
