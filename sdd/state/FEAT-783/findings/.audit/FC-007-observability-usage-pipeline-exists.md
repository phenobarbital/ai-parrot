---
id: FC-007
query_id: Q023
type: grep
intent: "Find any existing OTel wiring in the repo (env vars, exporters, collector config)."
executed_at: 2026-10-30T22:48:00Z
duration_ms: 1400
parent_id: null
depth: 1
---

# FC-007 — REFUTED (keystone): `parrot.observability` already is a normalized usage plane — UsageRecord, a ContextVar correlation key, a pluggable sink fan-out and an OTel/Prometheus pipeline

## Summary

The source's central premise — "the gap is a missing **correlation key** shared by the
seats, and a missing **single store** that owns the per-spec numbers" — is answered for
the *parrot-internal* seats by a subsystem the brainstorm never mentions.
`parrot/observability/` contains:

1. **`UsageRecord`** (`recorders/models.py:22-61`) — "the normalized, PII-free record
   shared by all usage recorders", built **once per successful LLM call**: `provider`,
   `client_name`, `model`, `input_tokens`, `output_tokens`, `cost_usd`,
   `cumulative_cost_usd`, `duration_ms`, `finish_reason`, `trace_id`, `service_name`,
   `timestamp`, plus the FEAT-479 attribution fields **`run_id`, `seat`, `node_id`,
   `cycle`, `usage_reported`, `status`, `error_type`**.
2. **A ContextVar correlation key** — `current_run_id` / `current_seat`
   (`observability/context.py`), read by the subscriber at record time. This is
   structurally the same mechanism the source proposes to build from hooks, already
   working inside the process.
3. **`UsageRecordingSubscriber`** (`recorders/subscriber.py:1-9`) — subscribes to
   `AfterClientCallEvent`/`ClientCallFailedEvent` on the global registry, computes cost
   with the shared `CostCalculator`, and **fans the record out to every configured
   `AbstractLogger`** backend. Adding a new sink is a plugin, not a fork of the pipeline.
4. **Existing sinks** — `prometheus_recorder.py` (counters for requests / input_tokens /
   output_tokens / cost, histograms for duration and tokens), `openlit_recorder.py`
   (spans with `gen_ai.usage.input_tokens` / `output_tokens` / `total_tokens` /
   `gen_ai.usage.cost`), `logging_recorder.py`, and **`run_ledger.py` —
   "the per-run usage ledger sink (FEAT-479 Module 4b)"**, an append-only in-memory
   roll-up by seat whose docstring already solves "retry cycles overwriting each other's
   token counts" by appending rather than merging.
5. **An OTel metrics subscriber** (`subscribers/metrics.py`) emitting
   `gen_ai.client.request.count`, `gen_ai.client.error.count`,
   `gen_ai.client.cost.total`, `gen_ai.client.operation.duration` and
   `gen_ai.client.token.usage` under current `gen_ai.*` SemConv, plus
   `subscribers/trace.py`, `exporters.py`, `bootstrap.py`, `setup.py`, `fanout.py`.

**The hardest constraint this surfaces is a privacy/cardinality contract that the source's
design violates.** `UsageRecord` carries "**NO `user_id`/`session_id`** — only
provider/model identifiers, token counts, cost, timing, and a correlation `trace_id`", and
`subscribers/metrics.py:8-10` states a "Cardinality whitelist: ONLY the attributes
documented per metric may appear in metric labels. `user_id`, `session_id`,
prompt/completion content NEVER." The source's plane is keyed on `session_id` and
`agent_id` and proposes per-spec Grafana panels — i.e. it proposes exactly the unbounded
labels this subsystem forbids by policy.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/recorders/models.py`
  lines: 1-12
  symbol: `module docstring`
  excerpt: |
    """UsageRecord — the normalized, PII-free record shared by all usage recorders.

    A single ``UsageRecord`` is built per successful LLM call by
    ``UsageRecordingSubscriber`` from an ``AfterClientCallEvent`` plus an optional
    ``CostCalculator`` result, then fanned out to every configured
    ``AbstractLogger`` backend.

    Privacy: this record carries NO prompt/completion content and NO
    ``user_id``/``session_id`` — only provider/model identifiers, token counts,
    cost, timing, and a correlation ``trace_id``.

- path: `packages/ai-parrot/src/parrot/observability/recorders/models.py`
  lines: 63-75
  symbol: `UsageRecord`
  excerpt: |
    provider: str
    client_name: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Optional[float] = None
    cumulative_cost_usd: Optional[float] = None
    duration_ms: float = 0.0
    trace_id: Optional[str] = None

- path: `packages/ai-parrot/src/parrot/observability/recorders/models.py`
  lines: 43-50
  symbol: `UsageRecord` (FEAT-479 attribution fields)
  excerpt: |
    run_id: FEAT-479 — the dev-loop / dev-flow run identifier, from the
        ``current_run_id`` ContextVar, or ``None`` when unattributed.
    seat: FEAT-479 — the accounting seat, e.g. ``"development"`` or a
        pool-worker seat ``"development.w1"``, from the ``current_seat``
        ContextVar, or ``None`` when unattributed.
    node_id: FEAT-479 — the roll-up owner node id
    cycle: FEAT-479 — 1-based attempt index within ``(run_id, seat)``

- path: `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py`
  lines: 1-9
  symbol: `UsageRecordingSubscriber`
  excerpt: |
    """UsageRecordingSubscriber — turns LLM-call events into UsageRecords + fan-out.

    This is the bridge between the FEAT-176 lifecycle event system and the pluggable
    recorder backends. It subscribes to ``AfterClientCallEvent`` on the global
    registry (the same surface the OTel ``MetricsSubscriber`` uses), computes cost
    via the shared ``CostCalculator``, builds a normalized ``UsageRecord``, and
    fans it out to every configured ``AbstractLogger``.

- path: `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py`
  lines: 22-24
  symbol: `subscriber imports`
  excerpt: |
    from parrot.observability.attributes import resolve_gen_ai_system
    from parrot.observability.context import current_run_id, current_seat
    from parrot.observability.recorders.models import UsageRecord

- path: `packages/ai-parrot/src/parrot/observability/recorders/run_ledger.py`
  lines: 1-14
  symbol: `RunLedgerRecorder`
  excerpt: |
    """RunLedgerRecorder — the per-run usage ledger sink (FEAT-479 Module 4b).

    An in-memory, append-only ``AbstractLogger`` sink. It is a SINK, not an
    ``EventProvider`` — it has no ``register()``. The EXISTING
    ``UsageRecordingSubscriber`` (``recorders/subscriber.py``) owns the
    ``AfterClientCallEvent``/``ClientCallFailedEvent`` subscription and fans
    records out to this sink alongside any other configured recorders.

    Being append-only is what fixes spec Finding 2 (retry cycles overwriting
    each other's token counts in session state)

- path: `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py`
  lines: 8-10
  symbol: `cardinality contract`
  excerpt: |
    Cardinality whitelist: ONLY the attributes documented per metric may appear in
    metric labels. ``user_id``, ``session_id``, prompt/completion content NEVER

- path: `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py`
  lines: 96-134
  symbol: `MetricsSubscriber` instruments
  excerpt: |
    self._client_request_count = meter.create_counter("gen_ai.client.request.count", ...)
    self._client_error_count = meter.create_counter("gen_ai.client.error.count", ...)
    self._client_cost_total = meter.create_counter("gen_ai.client.cost.total", ...)
    ... "gen_ai.client.operation.duration" ... "gen_ai.client.token.usage"

- path: `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py`
  lines: 216-247
  symbol: `MetricsSubscriber` label set
  excerpt: |
    base = {
        "gen_ai.system": system,
        "gen_ai.provider.name": system,
        "gen_ai.response.model": event.model,
        "parrot.agent.name": event.agent_name or "unknown",  # FEAT-228
    }
    ... attributes={**base, "gen_ai.token.type": "input"} ...
    self._client_cost_total.add(cost, attributes=base)

- path: `packages/ai-parrot/src/parrot/observability/recorders/openlit_recorder.py`
  lines: 116-124
  symbol: `OpenLitRecorder span attributes`
  excerpt: |
    span.set_attribute("gen_ai.system", record.provider)
    span.set_attribute("gen_ai.request.model", record.model)
    span.set_attribute("gen_ai.usage.input_tokens", record.input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", record.output_tokens)
    span.set_attribute("gen_ai.usage.total_tokens", record.total_tokens)
    span.set_attribute("gen_ai.usage.cost", record.cost_usd)

- path: `packages/ai-parrot/src/parrot/observability/`
  lines: n/a
  symbol: `package inventory`
  excerpt: |
    cost/  examples/  recorders/  subscribers/
    README.md (17.1K)  __init__.py  attributes.py (13.6K)  bootstrap.py (14.3K)
    config.py (21.7K)  context.py (7.7K)  errors.py  exporters.py (7.9K)
    fanout.py (5.2K)  provider.py  setup.py (16.9K)
    recorders/: base.py factory.py logging_recorder.py models.py
                openlit_recorder.py prometheus_recorder.py run_ledger.py subscriber.py
    subscribers/: metrics.py (14.4K) trace.py (13.7K)

## Notes

- **The natural extension point is a ContextVar + a sink, not a new ledger plane.** Adding
  `current_feat_id` / `current_task_id` / `current_attempt_uid` beside `current_run_id`
  and `current_seat`, widening `UsageRecord`, and registering one `AbstractLogger` that
  persists rows would give per-spec attribution for every *in-process* parrot call with no
  new store, no new price table and no new event kind.
- That path covers the dev-loop seat only. The Claude Code and Codex seats never enter
  `AbstractClient`, so they remain genuinely outside this pipeline — the source is right
  about the gap, but wrong about where the gap starts.
- `cumulative_cost_usd` is **process-cumulative**, so an sdd-worker process that outlives
  several tasks gives a monotonically rising number that must not be summed per task.
- [cross-lane: type=git_log, intent=FEAT-479 and FEAT-710 landing dates and whether the usage recorder pipeline is enabled by default]
