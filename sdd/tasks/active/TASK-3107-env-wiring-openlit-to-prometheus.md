# TASK-3107: Move the [observability] env block from OpenLIT to Prometheus

**Feature**: FEAT-548 — Observability — OTEL to Prometheus + Grafana usage/cost dashboard
**Spec**: `sdd/specs/observability-otel-grafana.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. This is the whole point of the feature: parrot's
telemetry emitter is complete but disconnected. `env/.env` currently has
`OBSERVABILITY_ENABLED=false` and points at `http://localhost:4318`, which is
OpenLIT's OTLP receiver — not the `parrot-prometheus` OTLP receiver on `:9090`.
Live Prometheus holds 291 metric names and **zero** starting `gen_ai_`/`parrot_`.

Nothing in the observability package changes. This is a pure env-variable move.

---

## Scope

- Rewrite the `[observability]` block in `env/.env` (operator action — the file
  is git-ignored) to the exact block in the Implementation Blueprint.
- Create `env/.env.observability.example`, a committed, secret-free copy.
- Replace the stale "Disabled: with no reachable OTLP collector…" comment with
  one naming the new target and the sampling rationale.

**NOT in scope**: any change under `packages/ai-parrot/src/parrot/observability/`
(the emitter is complete and pinned by 29 test modules); the Grafana dashboard
(TASK-3110); docs (TASK-3112); verifying that data actually arrives (TASK-3108).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `env/.env` | MODIFY | `[observability]` block, currently lines 715-726. **Git-ignored** — operator action, never committed |
| `env/.env.observability.example` | CREATE | Committed secret-free reference (this block contains no secrets) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Nothing is imported by this task — it changes configuration only.
# The consumer of these variables, for reference:
from parrot.observability.config import ObservabilityConfig  # verified: config.py:42
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/observability/config.py
class ObservabilityConfig(BaseModel):              # line 42
    enabled: bool = False                          # line 119  <- OBSERVABILITY_ENABLED
    otlp_endpoint: str = "http://localhost:4318"   # line 125  <- OTEL_EXPORTER_OTLP_ENDPOINT (BASE url)
    enable_traces: bool = True                     # line 132  <- NOT env-settable
    enable_metrics: bool = True                    # line 133  <- NOT env-settable
    sampling_ratio: float = 1.0                    # line 206  <- OBSERVABILITY_SAMPLING (ge=0.0, le=1.0)

    @classmethod
    def from_env(cls) -> "ObservabilityConfig": ...  # line 251
        # "sampling_ratio": _as_float(get("OBSERVABILITY_SAMPLING"), ...)   line 306
        # endpoint = get("OTEL_EXPORTER_OTLP_ENDPOINT")                     line 325

# packages/ai-parrot/src/parrot/observability/exporters.py
def make_metric_exporter(config) -> Any:                              # line 117
    endpoint = f"{config.otlp_endpoint.rstrip('/')}/v1/metrics"       # line 152  <- appends the suffix

# packages/ai-parrot/src/parrot/observability/setup.py
    tracer_provider = TracerProvider(..., sampler=TraceIdRatioBased(config.sampling_ratio))  # line 146
```

### Does NOT Exist

- ~~`OBSERVABILITY_TRACES`~~ / ~~`OBSERVABILITY_ENABLE_TRACES`~~ — no such env
  var. `enable_traces` is code-only (`config.py:132`); `from_env` never reads it.
  **`OBSERVABILITY_SAMPLING=0.0` is the only env-level way to stop traces.**
- ~~`OBSERVABILITY_METRICS_INTERVAL`~~ — no env var for
  `metric_export_interval_ms` (`config.py:211`, default 60 000 ms, code-only).
- ~~a Prometheus OTLP **trace** endpoint~~ — Prometheus 2.x serves only
  `/api/v1/otlp/v1/metrics`. There is no `/v1/traces` there.
- ~~`OBSERVABILITY_OPENLIT` doing anything~~ — deprecated no-op since FEAT-462;
  it only raises a `DeprecationWarning` (`config.py:331-345`).

---

## Implementation Notes

### Key Constraints

- `OTEL_EXPORTER_OTLP_ENDPOINT` is a **BASE URL**. The exporter appends
  `/v1/metrics` itself (`exporters.py:152`). Writing the full
  `.../api/v1/otlp/v1/metrics` produces a doubled path and a 404.
- `env/.env` is git-ignored (`.gitignore:181`) and holds live API keys and AWS
  credentials. **Never `git add -f` it, never paste its other sections anywhere.**
  Only the `[observability]` block — which has no secrets — may be reproduced.
- `OBSERVABILITY_OPENLIT` is **deleted**, not set to `false`. Leaving it either
  way is dead config.

### References in Codebase

- `docker/prometheus/docker-compose.yml` — `parrot-prometheus`, prom/prometheus
  v2.51.0, `--enable-feature=otlp-write-receiver` (why `:9090` accepts a push)
- `docker/matrix/.env.example`, `llama_server/.env.example` — the committed
  `.env.example` precedent to follow

---

## Implementation Blueprint

### Steps (in order)

1. Confirm the Prometheus OTLP receiver is reachable before editing anything:
   `curl -fsS -o /dev/null -w '%{http_code}\n' -X POST http://localhost:9090/api/v1/otlp/v1/metrics`
   — *why*: the block was originally disabled because an unreachable endpoint
   made the atexit flush hang ~10 s+ on CTRL+C. A healthy endpoint is the
   documented precondition for re-enabling (AC-7).
2. Rewrite the `[observability]` block in `env/.env` to the block below —
   *why*: this is the entire wiring change; every other task depends on it.
3. Create `env/.env.observability.example` with the same block —
   *why*: `env/.env` is git-ignored, so without this the configuration is
   undiscoverable to anyone else (AC-2).
4. Do **not** restart anything else; the stack is already running.

### `env/.env` (MODIFY)

```ini
# occurrences: 1 (verified: grep -c '^\[observability\]' env/.env)
# REPLACE the whole block below `[observability]` (verified: env/.env:715)
[observability]
# Metrics are pushed over OTLP to the local parrot-prometheus, which runs with
# --enable-feature=otlp-write-receiver (docker/prometheus/docker-compose.yml).
# Traces are silenced: the endpoint below carries BOTH signals, Prometheus 2.x
# serves no /v1/traces, and enable_traces is not env-settable (config.py:132) —
# so sampling 0.0 is the kill-switch. Set it back to 1.0 (and repoint the
# endpoint, or set OTLP_TARGETS) to send traces somewhere trace-capable again.
OBSERVABILITY_ENABLED=true
OBSERVABILITY_BACKEND=otel
OBSERVABILITY_SERVICE_NAME=parrot
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:9090/api/v1/otlp
OBSERVABILITY_SAMPLING=0.0
OBSERVABILITY_COST=True
```

**Why this shape**: `OTEL_EXPORTER_OTLP_ENDPOINT` is the base URL — the
`/v1/metrics` suffix is appended by `make_metric_exporter` (exporters.py:152), so
adding it here would double the path. `OBSERVABILITY_SAMPLING=0.0` feeds
`TraceIdRatioBased(0.0)` (setup.py:146), marking every span non-recording so no
trace request is ever issued (AC-6). `OBSERVABILITY_OPENLIT=true` is **removed**,
not set false — it has been a no-op since FEAT-462. Do not change
`OBSERVABILITY_BACKEND`: `otel` is what routes through `setup_telemetry`.

### `env/.env.observability.example` (CREATE)

```ini
# AI-Parrot observability — copy this block into env/.env
#
# env/.env is git-ignored (.gitignore:181), so this committed example is the
# only versioned record of the block. It contains no secrets.
#
# Topology (all containers already run locally):
#   parrot --OTLP/http--> parrot-prometheus :9090 <--query-- parrot-grafana :3001
#
# Full reference: docs/architecture/10-observability.md

[observability]
# Master switch. When false, setup_telemetry() is a no-op and no OTel SDK
# imports are triggered.
OBSERVABILITY_ENABLED=true

# none | logging | prometheus | otel. `otel` routes through setup_telemetry
# (OTLP traces + metrics). `prometheus` is the unrelated prometheus_client
# recorder on :9464 — not this stack.
OBSERVABILITY_BACKEND=otel

# OTel service.name resource attribute.
OBSERVABILITY_SERVICE_NAME=parrot

# BASE URL ONLY — the exporter appends /v1/metrics and /v1/traces itself.
# Do NOT write .../api/v1/otlp/v1/metrics here; that doubles the path.
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:9090/api/v1/otlp

# Trace sampling ratio, 0.0-1.0. Set to 0.0 because the endpoint above carries
# BOTH signals and Prometheus 2.x serves no /v1/traces; enable_traces is a
# code-only field (config.py:132) so this is the only env-level trace switch.
# Raise to 1.0 once traces have a trace-capable destination.
OBSERVABILITY_SAMPLING=0.0

# In-process USD cost calculation, emitted on gen_ai.client.cost.total.
OBSERVABILITY_COST=True

# NOT SET ON PURPOSE:
#   OBSERVABILITY_OPENLIT   - deprecated no-op since FEAT-462 (warns only)
#   OTLP_TARGETS            - multi-endpoint export; traces only, not metrics
```

**Why this shape**: every key is one `ObservabilityConfig.from_env()` actually
reads (verified `config.py:251-360`), which TASK-3114 asserts as a test. The
"NOT SET ON PURPOSE" footer prevents someone re-adding `OBSERVABILITY_OPENLIT`
and expecting an effect.

### FILL IN checklist

- [ ] `env/.env` — confirm the block currently at 715-726 is the one replaced;
      line numbers drift as the file is edited elsewhere. Bounded by AC-1.
- [ ] Record the `curl` status code from step 1 in the completion note;
      bounded by AC-7.

---

## Acceptance Criteria

- [ ] **AC-1** `env/.env` `[observability]` matches the block above exactly:
      `OBSERVABILITY_ENABLED=true`, endpoint `http://localhost:9090/api/v1/otlp`,
      `OBSERVABILITY_SAMPLING=0.0`, `OBSERVABILITY_OPENLIT` removed.
- [ ] **AC-2** `env/.env.observability.example` is committed and secret-free.
- [ ] `env/.env` itself is **NOT** committed (`git status` must not list it).
- [ ] `grep -c 'v1/metrics' env/.env` returns 0 — the endpoint is a base URL.

---

## Test Specification

No automated test in this task; the contract test lives in TASK-3114
(`test_env_example_matches_config_contract`). Manual check:

```bash
# The example must parse and every key must be one from_env() reads.
grep -oE '^[A-Z_]+(?==)' env/.env.observability.example
# Expect: OBSERVABILITY_ENABLED, OBSERVABILITY_BACKEND, OBSERVABILITY_SERVICE_NAME,
#         OTEL_EXPORTER_OTLP_ENDPOINT, OBSERVABILITY_SAMPLING, OBSERVABILITY_COST
git check-ignore -v env/.env    # must report .gitignore:181 — proves it stays uncommitted
```

---

## Agent Instructions

Standard SDD task flow. **This task requires the operator's own machine** — it
edits a git-ignored file and depends on the local docker stack being up. An
unattended agent must not fabricate the `env/.env` edit; if `env/.env` is not
present, stop and report.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
