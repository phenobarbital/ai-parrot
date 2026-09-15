---
id: F009
query_id: Q009
type: glob
intent: Locate the existing example Grafana dashboard JSON files that must be updated
executed_at: 2026-09-10T16:18:00Z
parent_id: null
depth: 0
---

# F009 — Both example dashboards query metric names that NOTHING in the codebase emits

## Summary

There are two example dashboards under
`packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/`, and
**neither one matches the current emitter**. This is the central defect behind
"update the example grafana dashboard".

* `parrot-usage.json` (6 panels) queries `parrot_llm_*` — those are the
  `prometheus_client` names from the **non-OTel** `PrometheusUsageRecorder`
  (`OBSERVABILITY_BACKEND=prometheus`, port 9464), not the OTLP path. Under
  `BACKEND=otel` these series never exist.
* `parrot-overview.json` (4 panels) queries `gen_ai_client_token_usage_total`,
  `gen_ai_client_cost_usd_total`, `gen_ai_client_error_total`,
  `gen_ai_client_operation_total` — **none of these exist under either backend**.
  The emitter's counters are `gen_ai.client.request.count` /
  `.error.count` / `.cost.total`, and token usage is a *histogram*, so a
  `..._total` counter for it can never appear.
* Both group `by (model)` / `by (provider, model)`. The real OTLP-translated
  labels are `gen_ai_response_model` / `gen_ai_request_model` /
  `gen_ai_system` / `gen_ai_provider_name`. Bare `model` / `provider` exist only
  on the `parrot_llm_*` recorder path.
* **Neither dashboard has a single panel grouped by agent**, even though
  `parrot.agent.name` has been on every LLM metric since FEAT-228.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-overview.json`
  symbol: uid `parrot-observability-overview`
  excerpt: |
    "Token throughput by model":  sum by (model) (rate(gen_ai_client_token_usage_total[5m]))
    "Cost by model (USD/hour)":   sum by (model) (increase(gen_ai_client_cost_usd_total[1h]))
    "p95 latency by model":       histogram_quantile(0.95, sum by (le, model) (rate(gen_ai_client_operation_duration_bucket[5m])))
    "Error rate by model":        sum by (model) (rate(gen_ai_client_error_total[5m])) / sum by (model) (rate(gen_ai_client_operation_total[5m]))

- path: `packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-usage.json`
  symbol: title "AI-Parrot — LLM Usage & Cost" (no uid set)
  excerpt: |
    "Total estimated cost (USD)": sum(parrot_llm_cost_usd_total)
    "Request rate (req/s)":       sum(rate(parrot_llm_requests_total[5m]))
    "Cost rate by provider/model": sum by (provider, model) (rate(parrot_llm_cost_usd_total[5m]))
    "Token throughput":           sum by (provider, model) (rate(parrot_llm_input_tokens_total[5m]))

- path: `packages/ai-parrot/src/parrot/observability/recorders/prometheus_recorder.py`
  lines: 44-80
  excerpt: |
    labelnames = ("provider", "model")
    "requests":      Counter("parrot_llm_requests_total", ..., labelnames),
    "input_tokens":  Counter("parrot_llm_input_tokens_total", ..., labelnames),
    "output_tokens": Counter("parrot_llm_output_tokens_total", ..., labelnames),
    "cost":          Counter("parrot_llm_cost_usd_total", ..., labelnames),
    "duration":      Histogram("parrot_llm_request_duration_seconds", ..., labelnames),
    "tokens":        Histogram("parrot_llm_tokens", ...),

## Notes

`parrot-usage.json` has no `uid`, so a provisioned copy gets a generated uid and
cannot be deep-linked stably. `parrot-overview.json` has uid
`parrot-observability-overview`. Also note these files live in the *package
examples* directory, which is NOT the directory the running Grafana provisions
from (see F008) — so "the example dashboard" is ambiguous between two locations.
