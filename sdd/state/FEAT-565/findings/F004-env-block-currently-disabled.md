---
id: F004
query_id: Q005
type: grep
intent: Enumerate the env/.env* files and the OTEL-related variables they already define
executed_at: 2026-09-10T16:13:00Z
parent_id: null
depth: 0
---

# F004 — `env/.env` has an `[observability]` block that is switched OFF and aimed at OpenLIT

## Summary

`env/` is a single INI-style `env/.env` (git-ignored via `.gitignore:181`) with
one `[observability]` section. Telemetry is currently **disabled**, and the
endpoint points at `http://localhost:4318` — which is OpenLIT's OTLP receiver
(`parrot-openlit-ui` publishes 4317-4318), not Prometheus. The in-file comment
records exactly why it was disabled: with nothing reachable at that endpoint the
atexit flush blocked shutdown for ~10s+ after a crew run. `OBSERVABILITY_OPENLIT=true`
is set but is a no-op deprecated flag as of FEAT-462 (it now only raises a
`DeprecationWarning`).

## Citations

- path: `env/.env`
  lines: 715-726
  excerpt: |
    [observability]
    # Disabled: with no reachable OTLP collector at OTEL_EXPORTER_OTLP_ENDPOINT,
    # the atexit telemetry flush blocks ~10s+ on CTRL+C after a crew run (many
    # buffered spans/metrics), hanging shutdown. Re-enable only with a healthy
    # collector listening at the endpoint below.
    OBSERVABILITY_ENABLED=false
    OBSERVABILITY_BACKEND=otel
    OBSERVABILITY_OPENLIT=true
    OBSERVABILITY_SERVICE_NAME=parrot
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
    OBSERVABILITY_COST=True

- path: `.gitignore`
  lines: 181
  excerpt: |
    env/

- path: `packages/ai-parrot/src/parrot/observability/config.py`
  lines: 331-345
  symbol: `ObservabilityConfig._warn_deprecated_flags`
  excerpt: |
    if self.enable_openlit:
        warnings.warn("enable_openlit is deprecated — configure an OTLP target "
                      "instead. See FEAT-462.", DeprecationWarning, stacklevel=2)

## Notes

`env/.env` is git-ignored and also holds live API keys and AWS credentials.
Any change to it is an operator action on this host, NOT a committed diff — and
its contents must never be pasted into an SDD artifact. A committed
`env/.env.example`-style template does not currently exist for this block.
