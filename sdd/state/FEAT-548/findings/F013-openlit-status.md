---
id: F013
query_id: Q004
type: grep
intent: Confirm residual openlit references — whether the migration is complete or partial
executed_at: 2026-09-10T16:22:00Z
parent_id: null
depth: 0
---

# F013 — The openlit→OTEL migration is complete in the emitter; OpenLIT survives as an optional OTLP destination

## Summary

"Migrated from openlit to OTEL" is accurate but needs one refinement: OpenLIT
was never the emitter of the metrics in question. FEAT-462 (`unified-telemetry-bus`)
demoted OpenLIT from an SDK-level integration to *a plain OTLP destination*.
`enable_openlit` / `enable_traceloop` are retained only as deprecated no-op
flags. What remains openlit-flavoured is optional and peripheral:

* `recorders/openlit_recorder.py` — an `AbstractLogger` sink that pushes
  `UsageRecord` data as GenAI SemConv spans, gated behind
  `OBSERVABILITY_OPENLIT_RECORDER`.
* `packages/ai-parrot-openlit-bridge/` — a separate distribution with a
  `parrot-openlit-check` CLI probe and its own compose file.
* `config.openlit_disabled_instrumentors` / `openlit_disable_metrics` — a
  large skip-list that exists specifically to stop OpenLIT double-emitting the
  same GenAI spans and duplicate same-named metric instruments.

So the native `MetricsSubscriber` is, and already was, the sole owner of the
instruments in F002 — nothing needs to be un-migrated for this feature.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/config.py`
  lines: 78-92
  excerpt: |
    enable_openlit: **Deprecated (FEAT-462)** — previously called
        ``openlit.init()`` after setting up OTel providers. Configure an
        OTLP target instead. ... setting it to ``True`` now only emits a
        ``DeprecationWarning`` and has no other effect.

- path: `packages/ai-parrot/src/parrot/observability/config.py`
  lines: 200-215
  symbol: `ObservabilityConfig.openlit_disable_metrics`
  excerpt: |
    # OpenLIT registers its own GenAI metric instruments (``gen_ai.client.
    # token.usage``, ...) using the same OTel semantic-convention names as our
    # native ``MetricsSubscriber``. ... Our subscriber already owns these
    # metrics (with LLM-tuned histogram buckets), so OpenLIT should do tracing only.

- path: `packages/ai-parrot/src/parrot/observability/recorders/openlit_recorder.py`
  lines: 116-124
  symbol: `OpenLitUsageRecorder`

- path: `packages/ai-parrot-openlit-bridge/src/ai_parrot_openlit_bridge/probe.py`
- path: `packages/ai-parrot/tests/unit/observability/test_integrations_removed.py`

## Notes

`test_integrations_removed.py` exists specifically to assert the old SDK
integrations stay removed — a useful guard rail for any change here.
