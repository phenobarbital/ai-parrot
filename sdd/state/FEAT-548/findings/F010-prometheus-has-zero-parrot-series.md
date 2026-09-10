---
id: F010
query_id: Q011
type: read
intent: Empirically confirm whether any parrot telemetry currently reaches the running Prometheus
executed_at: 2026-09-10T16:19:00Z
parent_id: F007
depth: 1
---

# F010 — Live Prometheus holds ZERO `gen_ai_*` / `parrot_*` series today

## Summary

Queried the running instance directly. Of 291 distinct metric names, the
prefixes are `prometheus` (178), `codex` (54), `go` (29), `claude` (8),
`process` (7), `net` (6), `scrape` (4), `promhttp` (2), `claudestats` (1),
`target` (1), `up` (1). Filtering for names starting with `gen_ai` or `parrot`
returns an **empty list**. Both scrape targets (`codex` via
`otel-collector:8889`, and Prometheus itself) are healthy.

This is direct confirmation that no parrot telemetry has ever landed here — the
gap is not a dashboard-query bug alone but a wiring gap (F004: disabled + aimed
at OpenLIT). It also means any new dashboard cannot be validated against
existing data; a real agent run is required to produce the first series.

## Citations

- path: `docker/prometheus/prometheus.yml`
  excerpt: |
    $ curl -sG http://localhost:9090/api/v1/label/__name__/values
    total series names: 291
    gen_ai/parrot names: []
    $ curl -sG http://localhost:9090/api/v1/targets
    codex       http://otel-collector:8889/metrics  up
    prometheus  http://localhost:9090/metrics       up

- path: `env/.env`
  lines: 720
  symbol: `OBSERVABILITY_ENABLED`

## Notes

`claude_*` (8 names) and `codex_*` (54 names) confirm the two existing producers
work end to end — the same host, the same Prometheus. So the infrastructure path
is proven; only the parrot producer is missing.
