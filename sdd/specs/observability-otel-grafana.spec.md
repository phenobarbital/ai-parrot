---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Observability — OTEL to Prometheus + Grafana usage/cost dashboard

**Feature ID**: FEAT-548
**Date**: 2026-09-10
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.x

> **Source**: `sdd/proposals/observability-otel-grafana.proposal.md` (accepted)
> **Research audit**: `sdd/state/FEAT-548/` — 14 findings, overall confidence **high**

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's telemetry emitter is complete but disconnected. `MetricsSubscriber`
already emits a USD cost counter, token histograms and request/error counters,
every one labelled with `parrot.agent.name`, a model attribute and
`gen_ai.provider.name` — so "usage total / by agent / by LLM model / cost" is
answerable **today** with no instrumentation change. Nothing consumes it.

Two concrete gaps:

1. **Nothing is flowing.** `env/.env` has `OBSERVABILITY_ENABLED=false` and
   `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` — OpenLIT's receiver, not
   the `parrot-prometheus` OTLP receiver on `:9090`. The live instance confirms
   it: 291 metric names, of which **zero** begin with `gen_ai_` or `parrot_`,
   while `codex_*` (54) and `claude_*` (8) prove the same infrastructure path
   works end to end for other producers.
   *Evidence*: F004, F010

2. **Both shipped example dashboards are fiction.** `parrot-usage.json` queries
   `parrot_llm_*`, which belong to the *non-OTel* `PrometheusUsageRecorder` on
   port 9464. `parrot-overview.json` queries `gen_ai_client_token_usage_total`,
   `gen_ai_client_cost_usd_total`, `gen_ai_client_error_total` and
   `gen_ai_client_operation_total` — none of which exist under **either**
   backend. Neither dashboard has a single by-agent panel, despite
   `parrot.agent.name` being on every LLM metric since FEAT-228.
   *Evidence*: F009, F002

### Goals

- G1 — Metrics from a running parrot process land in `parrot-prometheus`.
- G2 — The change is a **pure env-variable move** from OpenLIT to Prometheus:
  no new container, no second export destination, no source change to the
  observability package.
- G3 — A Grafana dashboard on the running `parrot-grafana` renders usage total,
  usage by agent, usage by LLM model, usage by provider, and cost — sourced from
  the real instrument catalog.
- G4 — The two stale package example dashboards stop advertising metric names
  that nothing emits.
- G5 — A committed, secret-free reference for the `[observability]` block exists,
  since `env/.env` itself is git-ignored.
- G6 — A regression guard makes the F009 class of defect (dashboard PromQL
  drifting away from the emitted instruments) fail a test rather than silently
  render empty panels.

### Non-Goals (explicitly out of scope)

- Any change to `MetricsSubscriber` instruments, labels or histogram buckets —
  the emitter is complete and pinned by 29 existing test modules. *F002, F012*
- Per-user or per-session dashboards. `user_id`/`session_id` are span attributes
  only, deliberately excluded from metric labels as a cardinality guard; this is
  structurally unavailable from Prometheus. *F002*
- Removing the OpenLIT stack, the `OpenLitUsageRecorder`, or the
  `ai-parrot-openlit-bridge` distribution. `parrot-openlit-ui` keeps running; it
  simply stops receiving parrot data. *F013*
- Multi-destination export (`OTLP_TARGETS`), a new OTel Collector service, or a
  code change making `enable_traces` env-settable. Rejected by the requester in
  proposal §5 U1 — this is an env-variable move, not an architecture change.
  A collector is retained *only* as the documented fallback for AC-13. *F014*
- The `PrometheusUsageRecorder` path (`OBSERVABILITY_BACKEND=prometheus`, port
  9464) stays exactly as-is. *F006*
- Alerting rules, recording rules, retention changes, or auth/TLS on the local
  stack.

---

## 2. Architectural Design

### Overview

Move the existing `env/.env` `[observability]` variables from OpenLIT to
Prometheus and let the already-running stack do the rest. `parrot-prometheus`
runs 2.51.0 with `--enable-feature=otlp-write-receiver`, so it accepts an OTLP
metric push directly at `/api/v1/otlp/v1/metrics` with no collector in front.

The one subtlety is that the endpoint move carries **both** signals. Metrics use
`config.otlp_endpoint` alone, while traces fall back to it when `otlp_targets`
is empty — so traces would POST to `/api/v1/otlp/v1/traces`, which Prometheus
2.x does not serve. Because `enable_traces` is **not settable from the
environment** (it is a code-only field that `from_env()` never reads), traces
are silenced inside the same env move with `OBSERVABILITY_SAMPLING=0.0`:
`TraceIdRatioBased(0.0)` marks every span non-recording, so no span ever reaches
an exporter and no request is issued. One variable, fully reversible.

The dashboard is then authored against the verified instrument catalog and
provisioned into the running Grafana under its own `AI-Parrot` folder, following
the Codex dashboard integration as a working template.

### Component Diagram

```
  parrot process (OBSERVABILITY_ENABLED=true, BACKEND=otel)
        │
        │  MetricsSubscriber  ──→  MeterProvider
        │                            └─ PeriodicExportingMetricReader (60s)
        │                                 └─ OTLPMetricExporter (http/protobuf)
        │  GenAIOpenTelemetrySubscriber ──→ TracerProvider
        │                                     └─ TraceIdRatioBased(0.0)  ✂ inert
        ▼
  POST http://localhost:9090/api/v1/otlp/v1/metrics
        │                    (base URL in .env; /v1/metrics appended by exporter)
        ▼
  parrot-prometheus :9090  ── otlp-write-receiver ──→ TSDB (90d retention)
        │
        │  network: parrot-metrics   (Grafana reaches it as http://prometheus:9090)
        ▼
  parrot-grafana :3001
        └─ provisioning/dashboards/parrot/parrot-usage-cost.json
             folder: AI-Parrot   ·   datasource uid: claudestats-prometheus
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ObservabilityConfig.from_env` | reads (unchanged) | consumes the moved env vars; no code change |
| `make_metric_exporter` | reads (unchanged) | appends `/v1/metrics` to the base URL |
| `setup_telemetry` | reads (unchanged) | `TraceIdRatioBased(config.sampling_ratio)` is the trace kill-switch |
| `MetricsSubscriber` | reads (unchanged) | the instrument catalog the PromQL targets |
| `parrot-prometheus` (docker) | configures | already OTLP-enabled; no compose change |
| `docker/grafana/provisioning/dashboards/dashboards.yml` | extends | second provider entry → `AI-Parrot` folder |
| `docker/grafana/provisioning/datasources/prometheus.yml` | reads (unchanged) | datasource uid `claudestats-prometheus` |

### Data Models

No new Python data models. The configuration surface is existing fields on
`ObservabilityConfig` (`config.py:42`), driven entirely through environment
variables — see §6 for the verified contract.

### New Public Interfaces

None. This feature adds no Python API. Its deliverables are configuration
(`env/.env` + a committed example), provisioning YAML, dashboard JSON, docs, and
one regression test.

---

## 3. Module Breakdown

> Interface Skeletons for the non-Python modules below give the exact **file
> contract** (INI / YAML / JSON shape) instead of Python signatures — that is the
> honest analogue here, and it is what `/sdd-task` turns into blueprints.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: env wiring + committed example | yes | exact variable set and values fixed below; `.env.example` follows `docker/matrix/.env.example` precedent | — |
| M2: verification & series-name capture | no | the whole point is to *discover* the real series names; the output shape is fixed but the values are not knowable in advance | resolves Q1/Q2 in §8 |
| M3: Grafana folder provisioning | yes | second provider entry, exact YAML keys fixed below | — |
| M4: parrot dashboard JSON | no | panel inventory is fixed, but PromQL cannot be finalized until M2 reports the real series names | depends on M2 output |
| M5: retire stale example dashboards | yes | delete-and-replace with M4's JSON; paths fixed | — |
| M6: docs sync | yes | exact files and the passages to change are identified | — |

### Module 1: Env wiring + committed example
- **Path**: `env/.env` (operator action, git-ignored) · `env/.env.observability.example` (new, committed)
- **Responsibility**: Move the `[observability]` block from OpenLIT to Prometheus and enable telemetry; ship a secret-free committed copy since the real file cannot be versioned.
- **Depends on**: nothing
- **Interface Skeleton** *(file contract — INI block; `env/.env` is git-ignored, `.gitignore:181`)*:
  ```ini
  # env/.env  (modifies the existing [observability] block, currently at lines 715-726)
  # env/.env.observability.example  (new, committed, identical minus any secrets — this block has none)
  [observability]
  OBSERVABILITY_ENABLED=true                                     # was: false
  OBSERVABILITY_BACKEND=otel                                     # unchanged
  OBSERVABILITY_SERVICE_NAME=parrot                              # unchanged
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:9090/api/v1/otlp  # was: http://localhost:4318
                                                                 # BASE URL — exporter appends /v1/metrics
  OBSERVABILITY_SAMPLING=0.0                                     # NEW — silences traces (see §7 Risks)
  OBSERVABILITY_COST=True                                        # unchanged
  # OBSERVABILITY_OPENLIT=true  -> DELETED: deprecated no-op since FEAT-462, warns only
  ```
  The stale "Disabled: with no reachable OTLP collector…" comment above the block
  is replaced with one naming the new target and the sampling rationale.

### Module 2: Verification & series-name capture
- **Path**: `sdd/state/FEAT-548/verification/series-names.md` (new artifact)
- **Responsibility**: Run a real agent call with M1 applied, then record the actual Prometheus series names and confirm counters are cumulative. Unblocks M4 and closes §8 Q1/Q2.
- **Depends on**: Module 1
- **Interface Skeleton** *(file contract — the recorded evidence)*:
  ```markdown
  # FEAT-548 — verified Prometheus series names   (captured <date>)
  ## Name map   (OTel instrument -> actual Prometheus series)
  | OTel instrument              | Prometheus series (verbatim from TSDB) |
  |------------------------------|----------------------------------------|
  | gen_ai.client.request.count  | <exact>                                |
  | gen_ai.client.cost.total     | <exact — note how the USD unit renders>|
  | gen_ai.client.token.usage    | <exact _bucket/_sum/_count>            |
  | ...                          | ...                                    |
  ## Label map      (OTel attribute -> Prometheus label)
  ## Temporality    monotonic increase observed over N scrapes: yes | no
  ```
  Capture commands (both already proven against this stack in
  `docker/grafana/README.md`):
  ```bash
  curl -fsSG http://localhost:9090/api/v1/label/__name__/values \
    | python3 -c "import json,sys;print([n for n in json.load(sys.stdin)['data'] if n.startswith(('gen_ai','parrot'))])"
  curl -fsSG http://localhost:9090/api/v1/query \
    --data-urlencode 'query=count by (__name__) ({__name__=~"gen_ai_.*|parrot_.*"})'
  ```

### Module 3: Grafana folder provisioning
- **Path**: `docker/grafana/provisioning/dashboards/dashboards.yml` (modify) · `docker/grafana/provisioning/dashboards/parrot/` (new dir)
- **Responsibility**: Give parrot dashboards their own Grafana folder so they do not land in the folder literally named `Claude Code`.
- **Depends on**: nothing
- **Interface Skeleton** *(file contract — YAML; appends a second provider, existing `claudestats` entry untouched)*:
  ```yaml
  # docker/grafana/provisioning/dashboards/dashboards.yml
  #   (modifies dashboards.yml:1-16 — existing `claudestats` provider is left as-is)
  providers:
    - name: claudestats            # existing — unchanged, keeps scanning the flat dir
      folder: Claude Code
      options:
        path: /etc/grafana/provisioning/dashboards
        foldersFromFilesStructure: false
    - name: parrot                 # NEW
      orgId: 1
      folder: AI-Parrot
      type: file
      disableDeletion: false
      allowUiUpdates: false        # matches the existing convention; "Save as" to customise
      updateIntervalSeconds: 30
      options:
        path: /etc/grafana/provisioning/dashboards/parrot
        foldersFromFilesStructure: false
  ```
  > **Gotcha to verify in implementation**: the existing `claudestats` provider
  > scans the parent directory. Confirm the new `parrot/` subdirectory is not
  > *also* picked up by it (which would provision each dashboard twice, in two
  > folders). If it is, the subdirectory must move outside that path or
  > `claudestats` must be narrowed.

### Module 4: The parrot usage & cost dashboard
- **Path**: `docker/grafana/provisioning/dashboards/parrot/parrot-usage-cost.json` (new)
- **Responsibility**: Render usage total, by agent, by model, by provider, and cost, against the verified catalog.
- **Depends on**: Module 2 (real series names), Module 3 (folder)
- **Interface Skeleton** *(file contract — Grafana dashboard JSON; PromQL below is written against the OTel instrument names of §6 and MUST be rewritten verbatim from M2's name map before merge)*:
  ```jsonc
  {
    "uid": "parrot-usage-cost",              // stable uid — required for deep links
    "title": "AI-Parrot — LLM Usage & Cost",
    "templating": { "list": [
      { "name": "agent",    "type": "query", "includeAll": true, "multi": true },  // label_values(parrot_agent_name)
      { "name": "model",    "type": "query", "includeAll": true, "multi": true },
      { "name": "provider", "type": "query", "includeAll": true, "multi": true }
    ]},
    "panels": [
      // Row: Totals
      { "type": "stat",       "title": "Total cost (USD)"          /* sum(<cost_total>) */ },
      { "type": "stat",       "title": "Total requests"            /* sum(<request_count_total>) */ },
      { "type": "stat",       "title": "Total tokens"              /* sum(<token_usage_sum>) */ },
      { "type": "stat",       "title": "Requests without cost"     /* unpriced-model guard, see §7 */ },
      // Row: By agent   — the dimension neither existing dashboard had
      { "type": "timeseries", "title": "Cost rate by agent (USD/h)" },
      { "type": "timeseries", "title": "Tokens/s by agent"          /* split by gen_ai_token_type */ },
      { "type": "table",      "title": "Cumulative cost by agent" },
      // Row: By model / provider
      { "type": "timeseries", "title": "Cost rate by model (USD/h)" },
      { "type": "timeseries", "title": "Tokens/s by model" },
      { "type": "table",      "title": "Cumulative cost by model + provider" },
      // Row: Health
      { "type": "timeseries", "title": "Request rate by agent" },
      { "type": "timeseries", "title": "Error rate by agent"        /* error_count / request_count */ },
      { "type": "timeseries", "title": "p50 / p95 latency"          /* histogram_quantile over _bucket */ }
    ]
  }
  ```
  **PromQL rules this dashboard must obey** (each traces to a §6 constraint):
  - Token totals come from the **`_sum`** of the `gen_ai.client.token.usage`
    histogram. There is no token `_total` counter — assuming one is the exact
    defect in the current `parrot-overview.json`.
  - Never add `parrot.client.round.token.usage` to `gen_ai.client.token.usage`;
    they are separate instruments precisely to avoid double counting (FEAT-397).
  - Group by the translated label names (`parrot_agent_name`,
    `gen_ai_response_model`, `gen_ai_provider_name`), **not** bare `model` /
    `provider` — those exist only on the `parrot_llm_*` recorder path.
  - Reference the datasource by uid `claudestats-prometheus`.

### Module 5: Retire the stale package example dashboards
- **Path**: `packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/parrot-overview.json` (replace) · `parrot-usage.json` (delete)
- **Responsibility**: Stop shipping queries for metrics nothing emits.
- **Depends on**: Module 4
- **Interface Skeleton** *(file contract)*:
  ```text
  grafana-dashboards/
    parrot-usage-cost.json   <- NEW: byte-identical copy of M4's dashboard
    parrot-overview.json     <- DELETE (queries gen_ai_client_*_total: no such series)
    parrot-usage.json        <- DELETE (queries parrot_llm_*: the 9464 recorder path)
  ```
  A single shipped example replaces two broken ones. If the `parrot_llm_*`
  dashboard is judged worth keeping for the `BACKEND=prometheus` path, it must be
  renamed to say so explicitly (see §8 Q3).

### Module 6: Documentation sync
- **Path**: `docs/architecture/10-observability.md` · `packages/ai-parrot/src/parrot/observability/examples/README.md` · `docker/grafana/README.md`
- **Responsibility**: Remove advice that now contradicts the wiring.
- **Depends on**: Modules 1, 4
- **Interface Skeleton** *(file contract — the passages that must change)*:
  ```text
  docs/architecture/10-observability.md
    :66  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   -> the Prometheus base URL
    :78  "OBSERVABILITY_BACKEND=prometheus and import the dashboards under
          packages/.../grafana-dashboards/"                  -> BACKEND=otel + the provisioned path
    :94  env table row for OTEL_EXPORTER_OTLP_ENDPOINT       -> note it is a BASE url
    +    NEW rows: OBSERVABILITY_SAMPLING (trace kill-switch), and a pointer to
         env/.env.observability.example
    +    NEW note: enable_traces/enable_metrics are code-only (verified config.py:132-133)
  examples/README.md
    :26-48  reframe: metrics -> Prometheus; OpenLIT remains a trace destination only
  docker/grafana/README.md
    +    NEW "AI-Parrot side" section mirroring the existing "Codex side" shape:
         topology diagram, the .env block, empty-dashboard curl diagnostics
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_shipped_dashboards_reference_real_metrics` | M4/M5 | Parse every shipped dashboard JSON; extract each PromQL `expr`; assert every `gen_ai_*`/`parrot_*` metric name maps to an instrument created by `MetricsSubscriber`. **This is the G6 regression guard — it would have caught F009.** |
| `test_shipped_dashboards_reference_real_labels` | M4 | Assert every `by (...)` / label matcher uses a label the emitter actually attaches (`parrot_agent_name`, `gen_ai_response_model`, `gen_ai_provider_name`, `gen_ai_token_type`), never bare `model`/`provider`. |
| `test_dashboard_json_is_valid_and_has_uid` | M4 | Dashboard parses as JSON, declares a non-empty stable `uid`, and references datasource uid `claudestats-prometheus`. |
| `test_no_round_token_double_count` | M4 | No panel sums `parrot.client.round.token.usage` together with `gen_ai.client.token.usage` (FEAT-397 invariant). |
| `test_env_example_matches_config_contract` | M1 | Every key in `env/.env.observability.example` is a variable `ObservabilityConfig.from_env()` actually reads — guards against documenting a variable that does nothing (as `OBSERVABILITY_OPENLIT` became). |
| `test_provisioning_yaml_parses` | M3 | `dashboards.yml` parses; both providers present; the parrot provider points at the parrot subdirectory and declares `folder: AI-Parrot`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_otlp_endpoint_composes_to_prometheus_path` | With `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:9090/api/v1/otlp`, assert `make_metric_exporter` produces exactly `.../api/v1/otlp/v1/metrics` (guards the base-URL-vs-full-path trap). No network required. |
| `test_zero_sampling_emits_no_spans` | With `sampling_ratio=0.0`, run a synthetic call and assert the span exporter receives nothing while the metric reader still records — the M1 trace kill-switch working as designed. |
| *(manual, M2)* `verify_live_series` | With the stack up and M1 applied, run a real agent call and confirm `gen_ai_*` series appear in Prometheus within ~90 s and that counters increase monotonically across ≥3 scrapes. |

### Test Data / Fixtures

```python
# Discover shipped dashboards for the metric-name guard.
@pytest.fixture
def shipped_dashboards() -> list[Path]:
    """Every dashboard JSON this repo ships, package examples + provisioning."""
    roots = [
        Path("packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards"),
        Path("docker/grafana/provisioning/dashboards/parrot"),
    ]
    return [p for r in roots for p in r.glob("*.json")]

@pytest.fixture
def emitted_metric_names() -> set[str]:
    """Prometheus-translated names of every instrument MetricsSubscriber creates.

    Built from the catalog in spec §6 rather than by importing the OTel SDK, so
    the guard runs without the `observability` extra installed.
    """
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC-1** `env/.env` `[observability]` matches the M1 block exactly:
      `OBSERVABILITY_ENABLED=true`, endpoint `http://localhost:9090/api/v1/otlp`,
      `OBSERVABILITY_SAMPLING=0.0`, and `OBSERVABILITY_OPENLIT` removed.
- [ ] **AC-2** `env/.env.observability.example` is committed, contains no secrets,
      and every key in it is read by `ObservabilityConfig.from_env()`.
- [ ] **AC-3** After a real agent run, `curl -fsSG
      http://localhost:9090/api/v1/label/__name__/values` returns at least one
      `gen_ai_*` series — the direct inversion of F010's zero-series baseline.
- [ ] **AC-4** `gen_ai.client.cost.total` is present as a series with a non-zero
      value for at least one priced model.
- [ ] **AC-5** Counters increase monotonically across ≥3 consecutive scrapes
      (cumulative temporality confirmed — closes §8 Q2).
- [ ] **AC-6** No request to `/api/v1/otlp/v1/traces` is issued during a run
      (trace kill-switch confirmed), and no OTLP export error appears in the logs.
- [ ] **AC-7** CTRL+C after a crew run exits promptly (no ~10 s+ atexit flush
      block — the symptom that got telemetry disabled originally).
- [ ] **AC-8** `sdd/state/FEAT-548/verification/series-names.md` records the
      verbatim OTel→Prometheus name and label maps (closes §8 Q1).
- [ ] **AC-9** The dashboard appears in Grafana at `http://localhost:3001` in an
      **AI-Parrot** folder, and the two existing dashboards remain in
      `Claude Code`, each provisioned exactly once.
- [ ] **AC-10** Every dashboard panel renders non-empty data after a real agent
      run — specifically including at least one panel grouped by agent, one by
      model, and one showing cost.
- [ ] **AC-11** `packages/.../grafana-dashboards/` no longer contains any query
      for a metric name the emitter does not produce.
- [ ] **AC-12** All new unit tests pass: `pytest packages/ai-parrot/tests/unit/observability/ -v`
- [ ] **AC-13** If AC-5 fails, the collector fallback is documented in
      `docker/grafana/README.md` with the concrete config, and the failure is
      recorded in the M2 artifact — the feature is not "done" by silently
      leaving broken counters.
- [ ] **AC-14** The existing observability suite still passes with no new
      failures: `pytest packages/ai-parrot/tests/unit/observability/ -q`
- [ ] **AC-15** `docs/architecture/10-observability.md` contains no remaining
      instruction to point `OTEL_EXPORTER_OTLP_ENDPOINT` at `:4318` for metrics.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every line below was re-verified against the working tree on 2026-09-10, after
> rebasing 33 upstream commits onto `dev`. The observability package was **not**
> touched by those commits.

### Verified Imports

```python
from parrot.observability.config import ObservabilityConfig, OtlpTarget  # verified: config.py:22,42
from parrot.observability.exporters import make_metric_exporter, make_span_exporters  # verified: exporters.py:117,20
from parrot.observability.setup import setup_telemetry, shutdown_telemetry  # verified: setup.py:63,285
from parrot.observability.subscribers.metrics import MetricsSubscriber  # verified: subscribers/metrics.py
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/observability/config.py
class OtlpTarget(BaseModel):                       # line 22
    name: str
    endpoint: str
    headers: dict[str, str]

class ObservabilityConfig(BaseModel):              # line 42
    enabled: bool = False                          # line 119
    otlp_endpoint: str = "http://localhost:4318"   # line 125  <- BASE url
    otlp_targets: list[OtlpTarget] = []            # line 128  (FEAT-462; TRACES ONLY)
    enable_traces: bool = True                     # line 132  <- NOT env-settable
    enable_metrics: bool = True                    # line 133  <- NOT env-settable
    sampling_ratio: float = 1.0                    # line 206  (ge=0.0, le=1.0)
    metric_export_interval_ms: int = 60_000        # line 211  <- no env var
    usage_backend: UsageBackend = "none"           # line 218  none|logging|prometheus|otel|traceloop

    @classmethod
    def from_env(cls) -> "ObservabilityConfig": ...  # line 251
        # OTEL_EXPORTER_OTLP_ENDPOINT -> otlp_endpoint            line 325
        # OBSERVABILITY_SAMPLING      -> sampling_ratio           line 306
        # OTLP_TARGETS (JSON list)    -> otlp_targets             line 348

# packages/ai-parrot/src/parrot/observability/exporters.py
def make_metric_exporter(config) -> Any:           # line 117
    endpoint = f"{config.otlp_endpoint.rstrip('/')}/v1/metrics"   # line 152
def make_span_exporter(config) -> Any:             # line 77
    endpoint = f"{config.otlp_endpoint.rstrip('/')}/v1/traces"    # line 112

# packages/ai-parrot/src/parrot/observability/setup.py
def setup_telemetry(...):                          # line 63
    targets = config.otlp_targets or [OtlpTarget(name="default", endpoint=config.otlp_endpoint, ...)]  # line 137
    tracer_provider = TracerProvider(..., sampler=TraceIdRatioBased(config.sampling_ratio))            # line 146
    reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=...)                # line 202
```

### The metric catalog — the dashboard's contract

```python
# packages/ai-parrot/src/parrot/observability/subscribers/metrics.py
"gen_ai.client.request.count"        # counter,   line 97   labels: gen_ai.system, gen_ai.provider.name, gen_ai.request.model, parrot.agent.name
"gen_ai.client.error.count"          # counter,   line 101  + error.type
"gen_ai.client.cost.total"           # counter,   line 105  unit="USD"   + gen_ai.response.model
"parrot.tool.failure.count"          # counter,   line 110  labels: parrot.tool.name, error.type
"parrot.agent.invoke.failure.count"  # counter,   line 114  labels: parrot.agent.name, parrot.invoke.method
"parrot.client.rounds"               # counter,   line 119  + parrot.round.number
"gen_ai.client.operation.duration"   # histogram, line 129  unit="s"      + gen_ai.operation.name="chat"
"gen_ai.client.token.usage"          # histogram, line 134  unit="tokens" + gen_ai.token.type in {input,output}
"parrot.client.round.token.usage"    # histogram, line 143  unit="tokens" + parrot.round.number  (NEVER summed with the above)
"parrot.tool.execution.duration"     # histogram, line 153  unit="s"      labels: parrot.tool.name
"parrot.agent.invoke.duration"       # histogram, line 158  unit="s"      labels: parrot.agent.name, parrot.invoke.method
```

### Configuration & Infrastructure References

| Artifact | Verified fact |
|---|---|
| `env/.env` | `[observability]` block at lines 715-726; file is git-ignored via `.gitignore:181` |
| `docker/prometheus/docker-compose.yml` | `parrot-prometheus`, prom/prometheus:v2.51.0, `--enable-feature=otlp-write-receiver`, 90d retention, network `parrot-metrics` |
| `docker/grafana/docker-compose.yml` | `parrot-grafana` on `127.0.0.1:3001->3000`, provisioning dirs mounted read-only |
| `docker/grafana/provisioning/datasources/prometheus.yml` | datasource uid `claudestats-prometheus`, url `http://prometheus:9090`, isDefault |
| `docker/grafana/provisioning/dashboards/dashboards.yml` | provider `claudestats`, folder `Claude Code`, `updateIntervalSeconds: 30`, `foldersFromFilesStructure: false` |
| `docker/grafana/provisioning/dashboards/` | contains `claude-code-metrics.json`, `codex-overview.json` — both working precedents |
| `.env.example` precedent | `docker/matrix/.env.example`, `llama_server/.env.example`, `examples/matrix_swarm/.env.example` |

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `.env` `[observability]` | `ObservabilityConfig.from_env()` | env var read | `config.py:251,306,325` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `make_metric_exporter` | base URL + `/v1/metrics` | `exporters.py:152` |
| `OBSERVABILITY_SAMPLING=0.0` | `TraceIdRatioBased` | sampler construction | `setup.py:146` |
| `parrot-usage-cost.json` | Grafana provider `parrot` | file scan every 30 s | `dashboards.yml:1-16` |
| dashboard PromQL | `MetricsSubscriber` instruments | Prometheus series | `subscribers/metrics.py:96-160` |

### Does NOT Exist (Anti-Hallucination)

- ~~`OBSERVABILITY_TRACES` / `OBSERVABILITY_ENABLE_TRACES`~~ — no such env var.
  `enable_traces` is code-only (`config.py:132`); `from_env` never reads it.
  Use `OBSERVABILITY_SAMPLING=0.0`.
- ~~`OBSERVABILITY_METRICS_INTERVAL`~~ — no env var for
  `metric_export_interval_ms` (`config.py:211`). Code-only, default 60 000 ms.
- ~~`gen_ai_client_token_usage_total`~~ — token usage is a **histogram**, not a
  counter. Currently queried by `parrot-overview.json`; it has never existed.
- ~~`gen_ai_client_cost_usd_total`~~, ~~`gen_ai_client_error_total`~~,
  ~~`gen_ai_client_operation_total`~~ — none exist. The real instruments are
  `gen_ai.client.cost.total`, `.error.count`, `.request.count`.
- ~~metric labels `model` / `provider`~~ (bare) — those exist only on the
  `parrot_llm_*` `PrometheusUsageRecorder` path. The OTel path uses
  `gen_ai_request_model` / `gen_ai_response_model` / `gen_ai_provider_name`.
- ~~metric labels `user_id` / `session_id`~~ — span attributes only, excluded
  from metrics by design (`attributes.py:126-133`).
- ~~a Prometheus OTLP **trace** endpoint~~ — Prometheus 2.x serves only
  `/api/v1/otlp/v1/metrics`.
- ~~`otlp_targets` affecting metrics~~ — it is consulted for traces only
  (`setup.py:137`); `make_metric_exporter` reads `otlp_endpoint` alone.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **The Codex integration is the template.** `docker/grafana/README.md`'s
  "Codex side" section is the shape to mirror: topology diagram, the exact
  producer config block, the caveat that bit them, a deep link to the dashboard,
  and copy-paste `curl` diagnostics for an empty dashboard. *F011*
- **Provisioning, not manual import.** File-based provider, 30 s scan,
  datasource by uid. *F008*
- **Stable `uid` on every dashboard.** The existing `parrot-usage.json` has none,
  so a provisioned copy gets a generated uid and cannot be deep-linked. *F009*
- **Verify before authoring PromQL.** M2 gates M4. Do not write a query against a
  predicted series name.

### Known Risks / Gotchas

- **Delta vs cumulative temporality** *(the one low-confidence claim, C11)*.
  Prometheus 2.51 has no delta→cumulative conversion, and this repo's own README
  documents Codex 0.154.0 breaking on exactly this path. Direct push assumes OTel
  Python exports cumulative. *Mitigation*: AC-5 tests it explicitly; AC-13 makes
  the collector fallback a required deliverable if it fails. *F011, F006*
- **Trace 404s if `OBSERVABILITY_SAMPLING` is forgotten.** The endpoint move
  carries traces along, and `enable_traces` is not env-settable, so omitting the
  sampling variable yields a failed POST per batch — log noise, retry backoff,
  slower atexit flush: a milder version of the very symptom that got telemetry
  disabled. *Mitigation*: AC-6. *F014, F006, F004*
- **Losing trace visibility is a deliberate trade.** Sampling 0.0 means no
  per-call timelines and no per-user/session attribution anywhere.
  `parrot-openlit-ui` simply stops receiving parrot data. Reversible with one
  variable. *F002, F014*
- **Unpriced models are invisible in cost.** `cost_usd()` returns `None` for a
  model absent from the pricing tables and that call silently adds nothing to the
  counter. *Mitigation*: the "Requests without cost" stat panel in M4 makes the
  gap visible instead of silently under-reporting spend. *F003*
- **First data takes up to a minute.** `metric_export_interval_ms` is 60 000 with
  no env override, so an empty dashboard immediately after a run is expected, not
  a bug. *F005*
- **Double provisioning.** The existing `claudestats` provider scans the parent
  of the new `parrot/` subdirectory — verify dashboards are not provisioned into
  both folders (M3 gotcha).
- **Cardinality.** `parrot.round.number` multiplies series count by round depth
  (bounded by `max_turns`, typically 10-15). Prefer per-call instruments over
  per-round ones in the default dashboard views. *F002*
- **`env/.env` holds live credentials.** It is git-ignored and must never be
  pasted into an SDD artifact, a commit, or a dashboard annotation. Only the
  `[observability]` block — which contains no secrets — is reproduced. *F004*

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | No new Python dependencies. The `observability` extra is already required for `BACKEND=otel` and is already installed. |
| `prom/prometheus` | `v2.51.0` (running) | OTLP write receiver; already deployed |
| `grafana` (local build `parrot-grafana`) | running | dashboard host; already deployed |

---

## 8. Open Questions

### Resolved (carried forward from the proposal)

- [x] **Once metrics point at Prometheus, where should traces go?** — *Resolved*:
      nowhere. A straight move of the existing env variables from OpenLIT to
      Prometheus; no `OTLP_TARGETS` split, no collector. Traces silenced via
      `OBSERVABILITY_SAMPLING=0.0`. → §2 Overview, M1, AC-6
- [x] **Which artifact is "the example grafana dashboard"?** — *Resolved*: both —
      a new dashboard provisioned into the running Grafana **and** replacement of
      the stale package-example files. → M4, M5, AC-9, AC-11
- [x] **Direct OTLP push, or route through an OTel Collector?** — *Resolved*:
      direct push to `http://localhost:9090/api/v1/otlp`; collector retained only
      as the AC-13 fallback. → §2 Overview, M1
- [x] **Where should the dashboard appear in Grafana?** — *Resolved*: a new
      `AI-Parrot` folder via a second provider entry. → M3, AC-9
- [x] **A committed, secret-free reference for the `[observability]` block?** —
      *Resolved*: both a committed example file and the docs block. → M1, M6, AC-2, AC-15

### Unresolved

- [ ] **Q1 — What are the real Prometheus series and label names after the first
      export?** *Owner*: implementation (M2, gates M4). Specifically how the
      `USD` unit renders on `gen_ai.client.cost.total`. Must be read off
      `/api/v1/label/__name__/values`, never assumed. *Blocks*: AC-8, AC-10
- [ ] **Q2 — Does the direct push deliver cumulative counters?** *Owner*:
      implementation (M2). If not, AC-13's collector fallback is required.
      *Blocks*: AC-5
- [ ] **Q3 — Should a `parrot_llm_*` dashboard be kept for the
      `OBSERVABILITY_BACKEND=prometheus` recorder path?** *Owner*: Jesus Lara.
      M5 currently deletes `parrot-usage.json` outright. Keeping it would require
      renaming it to name its backend explicitly, so it can never again be
      mistaken for the OTel dashboard. *Plausible answers*: a) delete (current
      plan) · b) keep, renamed `parrot-usage-prometheus-recorder.json`.
- [x] **Q4 — Should `/sdd-proposal`'s max+1 ID allocation be fixed to use the CAS
      ledger?** *Owner*: Jesus Lara. Out of scope here, but this feature exposed
      it: the proposal series had drifted ~17 ahead (FEAT-565 vs the real 548),
      and FEAT-560/561/563/564 are similarly proposal-local numbers. Filed as an
      observation, not a deliverable: Yes

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` ·
> **Status: skipped (model probe failed for gpt-5.6-luna — rc=124, timed out after 120s)**
> · Transcript: `sdd/state/FEAT-548/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | *(no suggestions — the seat was skipped)* | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

The brief was rendered and staged (`design_research/brief.md`, 17 319 chars) but
the model probe timed out, so no review was obtained. Per CLAUDE.md the `agy`
reviewer is banned and was **not** substituted. Re-running is cheap:
`codex exec --ephemeral --sandbox read-only -m gpt-5.6-luna -c model_reasoning_effort=high
--ignore-user-config --output-schema sdd/templates/design_research.schema.json
-o suggestions.json - < sdd/state/FEAT-548/design_research/brief.md`

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree.
- **Rationale**: the modules form a hard chain (M1 wire → M2 verify → M4 author →
  M5/M6 propagate). Only M3 is independent, and it is a six-line YAML edit — not
  worth a second worktree.
- **Cross-feature dependencies**: none. The observability package is untouched,
  so this cannot conflict with in-flight work there.
- **Note**: M1 and M2 require the operator's own machine (the running docker
  stack and a real LLM call). They are not executable by an unattended agent in a
  clean worktree — a `sdd-worker` run should stop at M2 and hand back.

```bash
git worktree add -b feat-548-observability-otel-grafana \
  .claude/worktrees/feat-548-observability-otel-grafana HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-10 | Jesus Lara | Initial draft from the accepted proposal (FEAT-548, 14 findings) |
