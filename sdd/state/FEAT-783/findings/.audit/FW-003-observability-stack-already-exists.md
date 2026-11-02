---
id: FW-003
query_id: Q007
type: wiki_query
intent: "Orient: existing OpenTelemetry/observability subsystem in parrot (FEAT-724/725)."
executed_at: 2026-10-30T22:38:36Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-003 — `parrot.observability` is a complete, auto-booting OTel + USD-cost stack: price tables, collector config and a Grafana usage/cost dashboard all ship in-repo

## Summary

The source's "Does NOT exist" list claims there is no ai-parrot-owned price table, no collector
config, and no Grafana datasource beyond the OTel pipeline. All three are wrong. `parrot.observability`
ships bundled per-provider pricing JSON, a `CostCalculator` with a 90-day staleness warning and a
`PARROT_PRICING_PATH` override, an OTel Collector example config, and a provisioned Grafana dashboard
titled **"AI-Parrot — LLM Usage & Cost"** with by-agent and by-model/provider cost panels. It
auto-boots: running any `wikitoolkit` command in this repo prints `Observability auto-boot: OTel
backend active` and attaches an OTLP target.

It also exposes exactly the pluggable sink seam a usage plane would hook into — `AbstractLogger` /
`UsageRecord` / `UsageRecordingSubscriber` — documented as "ship `record` (provider, model, tokens,
cost_usd, …) anywhere".

**The real gap is attribution, not plumbing**: this stack keys usage by `{provider, model, agent}`
and only observes **in-process parrot LLM calls**. It has no `feat_id`/`task_id`/`attempt_uid` and
never sees the Claude Code or Codex seats.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/cost/calculator.py`
  lines: 1-13
  symbol: module docstring
  excerpt: |
    """CostCalculator — stateless USD cost estimation for LLM API calls.
    FEAT-177 TASK-1232.
    Pricing tables are loaded from bundled JSON files once at first
    ``CostCalculator()`` construction and cached at module level.
    Override path: ``ObservabilityConfig.pricing_override_path`` or
    ``PARROT_PRICING_PATH`` env var (resolved by ``setup_telemetry``)."""

- path: `packages/ai-parrot/src/parrot/observability/cost/calculator.py`
  lines: 135-240
  symbol: `CostCalculator` / `CostCalculator.cost_usd` (L190) / `_check_staleness` (L108)

- path: `packages/ai-parrot/src/parrot/observability/cost/pricing/anthropic.json`
  lines: 1-12
  symbol: price table shape
  excerpt: |
    { "pricing": { "last_updated": "2026-06-10",
                   "source": "https://www.anthropic.com/pricing",
                   "currency": "USD" },
      "models": { "claude-3-5-sonnet-20241022": {
          "input_per_1m": 3.00, "output_per_1m": 15.00,
          "cached_input_per_1m": 0.30, "valid_from": "2024-10-22" }, ... } }

- path: `packages/ai-parrot/src/parrot/observability/cost/pricing/`
  lines: 1-1
  symbol: bundled tables
  excerpt: |
    anthropic.json (19 models, last_updated 2026-06-10)
    openai.json    (24 models, last_updated 2026-06-10)
    google.json    (15 models, last_updated 2026-06-10)
    groq.json · huggingface.json · nvidia.json (last_updated 2026-05-18)

- path: `packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-usage-cost.json`
  lines: 1-1
  symbol: dashboard "AI-Parrot — LLM Usage & Cost"
  excerpt: |
    panels: Total cost (USD) · Total requests · Total tokens · Requests without cost
            Cost rate by agent (USD/h) · Tokens/s by agent · Cumulative cost by agent
            Cost rate by model (USD/h) · Tokens/s by model · Cumulative cost by model + provider

- path: `packages/ai-parrot/src/parrot/observability/examples/otel-collector-config.yaml`
  lines: 1-49
  symbol: collector pipelines
  excerpt: |
    receivers:  otlp
    processors: memory_limiter, batch
    exporters:  clickhouse
    service.pipelines: traces / metrics / logs  -> [clickhouse]

- path: `packages/ai-parrot/src/parrot/observability/README.md`
  lines: 1-1
  symbol: "Programmatic use / custom backends"
  excerpt: |
    from parrot.observability import (
        UsageRecord, AbstractLogger, UsageRecordingSubscriber, LoggingUsageRecorder,
    )
    class MyRecorder(AbstractLogger):
        async def record(self, record: UsageRecord) -> None:
            ...  # ship `record` (provider, model, tokens, cost_usd, …) anywhere

- path: `packages/ai-parrot/src/parrot/observability/setup.py`
  lines: 151-290
  symbol: `setup_telemetry`
  excerpt: |
    # live log, captured 2026-10-30 running `wikitoolkit` in this repo:
    setup_telemetry: attached OTLP target 'default' -> http://localhost:9090/api/v1/otlp
    setup_telemetry: observability active for 'parrot' (traces=False, metrics=True, cost=True, otlp_targets=1)
    Observability auto-boot: OTel backend active.

- path: `packages/ai-parrot/src/parrot/observability/`
  lines: 1-1
  symbol: package contents
  excerpt: |
    cost/ examples/ recorders/ subscribers/ README.md __init__.py attributes.py
    bootstrap.py config.py context.py errors.py exporters.py fanout.py provider.py setup.py

## Notes

Two facts that bite the source's cost model directly:

1. **Every bundled table is already stale.** Running any CLI in this repo logs
   `CostCalculator: pricing for provider='anthropic' is stale (last_updated=2026-06-10, older than
   90 days)` for anthropic/google/huggingface/openai and 2026-05-18 for groq/nvidia. No Claude 5
   family model (claude-opus-5, claude-sonnet-5-5, claude-haiku-5-5) is priced; the newest Anthropic
   entries are `claude-fable-5`, `claude-opus-4-8`, `claude-opus-4-7`.
2. **The entry schema has three price tiers, not four**: `input_per_1m`, `output_per_1m`,
   `cached_input_per_1m`. There is **no `cache_creation` tier**, which the source's four-counter
   model requires (Anthropic bills cache writes at a premium over input).

Also note the README's pricing section documents a path (`parrot/observability/pricing/*.json`) and a
flat `{"<model>": {"input","output","cached_input"}}` shape that do **not** match the real files
(`parrot/observability/cost/pricing/*.json`, nested under `"models"`, suffixed `_per_1m`) — the docs
are drifted.

[cross-lane: type=read, intent=Read observability/subscribers/metrics.py _on_client_after to confirm the metric attribute set is {gen_ai.system, gen_ai.response.model} only]
