---
id: F012
query_id: Q016
type: glob
intent: Find existing observability documentation and tests that must be kept in sync
executed_at: 2026-09-10T16:21:00Z
parent_id: null
depth: 0
---

# F012 — Docs and a 29-file unit test suite already pin this surface

## Summary

`docs/architecture/10-observability.md` documents the env-var table and still
tells the reader to point `OTEL_EXPORTER_OTLP_ENDPOINT` at
`http://localhost:4318` and to import the dashboards from the package examples
directory under `OBSERVABILITY_BACKEND=prometheus` — advice that conflicts with
routing to Prometheus over OTLP and must be updated alongside any wiring change.
`packages/ai-parrot/src/parrot/observability/examples/README.md` similarly frames
the example stack around OpenLIT, though it already notes Prometheus moved to
`docker/prometheus/`.

The test suite is substantial: 29 unit test modules under
`packages/ai-parrot/tests/unit/observability/` plus 3 integration modules,
including `test_config_from_env.py`, `test_exporters_multi.py`,
`test_setup_multi_target.py` and `test_metrics_subscriber.py` — meaning the env
contract, the multi-target wiring and the instrument names are all already
covered by assertions that a change must not break.

## Citations

- path: `docs/architecture/10-observability.md`
  lines: 20-95
  excerpt: |
    ├─ backend=prometheus  → counters/histograms on :9464/metrics
    parrot-openlit-check http://localhost:4318   # verify reachability
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
    `OBSERVABILITY_BACKEND=prometheus` and import the dashboards under
    `packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/`.
    | `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector base URL | `http://localhost:4318` |

- path: `packages/ai-parrot/src/parrot/observability/examples/README.md`
  lines: 26-48

- path: `packages/ai-parrot/tests/unit/observability/test_config_from_env.py`
- path: `packages/ai-parrot/tests/unit/observability/test_metrics_subscriber.py`
- path: `packages/ai-parrot/tests/unit/observability/test_exporters_multi.py`
- path: `packages/ai-parrot/tests/unit/observability/test_setup_multi_target.py`
- path: `docs/dev_loop/telemetry-accounting.md`

## Notes

Prior SDD specs covering this surface, useful as background for a spec author:
`sdd/specs/otel-observability.spec.md` (FEAT-177),
`sdd/specs/per-agent-cost-usage-metrics.spec.md` (FEAT-228 — the spec that put
`parrot.agent.name` on metrics),
`sdd/specs/unified-telemetry-bus.spec.md` (FEAT-462 — multi-target OTLP,
openlit/traceloop deprecation), `sdd/specs/tokens-observability.spec.md`
(FEAT-397 — per-round instruments).
