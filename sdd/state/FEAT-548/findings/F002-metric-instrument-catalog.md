---
id: F002
query_id: Q002
type: grep
intent: Find every OTEL metric instrument name emitted (counters/histograms) to know what the dashboard can query
executed_at: 2026-09-10T16:11:00Z
parent_id: null
depth: 0
---

# F002 — The complete emitted metric catalog and its label sets

## Summary

`MetricsSubscriber.__init__` creates exactly 5 counters and 5 histograms. Every
LLM-call instrument carries `parrot.agent.name` (FEAT-228), `gen_ai.system`,
`gen_ai.provider.name` and a model attribute — so "total / by agent / by model /
by provider" is fully answerable from metrics alone, no trace joins needed.
`user_id`/`session_id` are deliberately span-only and are NOT metric labels
(cardinality guard), so per-user slicing is NOT available from Prometheus.

Instruments (OTel names, before Prometheus translation):

| Instrument | Kind | Unit | Labels |
|---|---|---|---|
| `gen_ai.client.request.count` | counter | — | gen_ai.system, gen_ai.provider.name, gen_ai.request.model, parrot.agent.name |
| `gen_ai.client.error.count` | counter | — | gen_ai.system, gen_ai.provider.name, error.type, parrot.agent.name |
| `gen_ai.client.cost.total` | counter | USD | gen_ai.system, gen_ai.provider.name, gen_ai.response.model, parrot.agent.name |
| `gen_ai.client.operation.duration` | histogram | s | + gen_ai.operation.name="chat" |
| `gen_ai.client.token.usage` | histogram | tokens | + gen_ai.token.type ∈ {input,output} |
| `parrot.client.rounds` | counter | — | + parrot.round.number |
| `parrot.client.round.token.usage` | histogram | tokens | + parrot.round.number, gen_ai.token.type |
| `parrot.tool.execution.duration` | histogram | s | parrot.tool.name |
| `parrot.tool.failure.count` | counter | — | parrot.tool.name, error.type |
| `parrot.agent.invoke.duration` | histogram | s | parrot.agent.name, parrot.invoke.method |
| `parrot.agent.invoke.failure.count` | counter | — | parrot.agent.name, parrot.invoke.method |

## Citations

- path: `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py`
  lines: 96-160
  symbol: `MetricsSubscriber.__init__`
  excerpt: |
    self._client_request_count = meter.create_counter("gen_ai.client.request.count", ...)
    self._client_error_count   = meter.create_counter("gen_ai.client.error.count", ...)
    self._client_cost_total    = meter.create_counter("gen_ai.client.cost.total", unit="USD", ...)
    self._tool_failure_count   = meter.create_counter("parrot.tool.failure.count", ...)
    self._invoke_failure_count = meter.create_counter("parrot.agent.invoke.failure.count", ...)
    self._client_rounds        = meter.create_counter("parrot.client.rounds", ...)
    self._client_op_duration   = meter.create_histogram("gen_ai.client.operation.duration", unit="s", ...)
    self._client_token_usage   = meter.create_histogram("gen_ai.client.token.usage", unit="tokens", ...)
    self._client_round_token_usage = meter.create_histogram("parrot.client.round.token.usage", unit="tokens", ...)
    self._tool_exec_duration   = meter.create_histogram("parrot.tool.execution.duration", unit="s", ...)
    self._invoke_duration      = meter.create_histogram("parrot.agent.invoke.duration", unit="s", ...)

- path: `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py`
  lines: 211-250
  symbol: `MetricsSubscriber._on_client_after`
  excerpt: |
    base = {
        "gen_ai.system": system,
        "gen_ai.provider.name": system,
        "gen_ai.response.model": event.model,
        "parrot.agent.name": event.agent_name or "unknown",  # FEAT-228
    }
    self._client_op_duration.record(event.duration_ms / 1000.0,
        attributes={**base, "gen_ai.operation.name": "chat"})
    self._client_token_usage.record(event.input_tokens,
        attributes={**base, "gen_ai.token.type": "input"})

- path: `packages/ai-parrot/src/parrot/observability/attributes.py`
  lines: 126-133
  excerpt: |
    # user_id and session_id ARE included in SPAN attributes for per-user usage
    # tracking (e.g. OpenLIT dashboards) — but NEVER in metric labels (cardinality).

- path: `packages/ai-parrot/src/parrot/observability/attributes.py`
  lines: 34-90
  symbol: `PROVIDER_TO_GEN_AI_SYSTEM`

## Notes

`gen_ai.client.token.usage` is a HISTOGRAM recorded twice per call (once for
input, once for output) — a token *total* must be built from its `_sum`, never
from a `_total` counter (which does not exist). `parrot.client.round.token.usage`
is a separate instrument and must never be added to it (double counting — see
the FEAT-397 note at metrics.py:139-151).
