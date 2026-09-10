---
kind: inline
jira_key: null
fetched_at: 2026-09-10T00:00:00Z
summary_oneline: Point parrot OTEL observability at the running parrot-prometheus and build a Grafana dashboard for usage/tokens/cost by agent and model
---

# Source (inline)

Slug requested: `observability-otel-grafana`

> parrot observability was recently migrated from openlit to a compatible OTEL
> opentelemetry with per-agent usage, tokens, etc, currently there are a
> prometheus (parrot-prometheus) and grafana (parrot-grafana) docker machines
> running on this server, then we can change the env/.env variables to point to
> prometheus and update the example grafana dashboard to render usage total, by
> agent, by llm model, costs, etc.

## Explicit asks extracted

1. The observability layer was migrated openlit -> vendor-neutral OpenTelemetry,
   emitting per-agent usage/token metrics.
2. `parrot-prometheus` and `parrot-grafana` containers already run on this host.
3. Change `env/.env` variables so the OTEL exporter points at the running
   Prometheus stack.
4. Update the example Grafana dashboard to render:
   - usage total
   - usage by agent
   - usage by LLM model
   - costs
