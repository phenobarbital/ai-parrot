---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot, docs]
tags: [observability, opentelemetry, metrics, otlp, configuration]
---

# Feature Specification: Observability — OTLP metrics fan-out and env-level trace/metric switches

**Feature ID**: FEAT-705
**Date**: 2026-10-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

> Closes the two gaps that FEAT-548 (OTel → Prometheus + Grafana) documented as
> "known limitations" instead of fixing, because they were outside its scope.

### Problem Statement

`parrot.observability` (FEAT-177, FEAT-462, FEAT-548) exports OTel traces and
metrics from `setup_telemetry()`. Two asymmetries in that function make common
deployments awkward:

**Gap 1 — metrics do not fan out.** FEAT-462 made traces multi-destination: one
`BatchSpanProcessor` per `config.otlp_targets` entry on the shared
`TracerProvider` (`setup.py:137-154`). Metrics never got the same treatment:
`setup_telemetry()` builds exactly one `OTLPMetricExporter` from
`config.otlp_endpoint` (`exporters.py:117-154`, `setup.py:201-209`) and ignores
`otlp_targets` entirely. So an operator who wants metrics in both Prometheus
and an OTLP collector (OpenLIT, SigNoz, Grafana Alloy) cannot; the docs say so
in three places (`README.md:101-107`, `10-observability.md:109`,
`env/.env.observability.example:39`). Per-target `headers` (e.g. a bearer token
for a hosted collector) also never reach the metric exporter.

**Gap 2 — three fields are code-only.** `enable_traces`, `enable_metrics`
(`config.py:132-133`) and `metric_export_interval_ms` (`config.py:211`) are
never read by `ObservabilityConfig.from_env()` (`config.py:251-367`). The env
auto-boot (`ensure_observability_bootstrapped`, `bootstrap.py:67`) builds its
config exclusively through `from_env()`, so a zero-code deployment cannot turn
traces off, cannot turn metrics off, and cannot tune the 60 s export interval.
The documented workaround for "no traces" is `OBSERVABILITY_SAMPLING=0.0`
(`10-observability.md:112-117`, `docker/grafana/README.md:126-130`), which
still constructs the trace subscriber and span processors and relies on the
sampler to discard every span. The 60 s interval makes every first-run
dashboard look broken for a minute, and the docs tell readers to wait rather
than letting them shorten it.

### Goals

- G1. `setup_telemetry()` attaches one `PeriodicExportingMetricReader` +
  OTLP metric exporter **per `OtlpTarget`** to the shared `MeterProvider`,
  honouring each target's `endpoint` and `headers`, so metrics and traces
  reach the same set of destinations.
- G2. With `otlp_targets` empty, behaviour is byte-for-byte the pre-FEAT-705
  single-exporter path: one reader, built from `otlp_endpoint` +
  `otlp_headers`, endpoint suffixed `/v1/metrics` (http) or bare (grpc).
- G3. `ObservabilityConfig.from_env()` reads three new keys:
  `OBSERVABILITY_TRACES` → `enable_traces`, `OBSERVABILITY_METRICS` →
  `enable_metrics`, `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS` →
  `metric_export_interval_ms`, with the same parsing rules as the existing
  boolean/int keys and the existing defaults (`True`, `True`, `60_000`).
- G4. `metric_export_interval_ms` is validated as a **positive** int: the
  Pydantic field rejects `<= 0`, and `from_env()` falls back to the default
  (with a warning log) on a non-numeric or non-positive string instead of
  raising for this key. Existing validation errors from unrelated env fields
  remain outside this feature's scope.
- G5. The env auto-boot honours the three keys with **no change** to
  `bootstrap.py`: it already calls `from_env()` and passes the config to
  `setup_telemetry()`.
- G6. Docs stop describing these as code-only/single-endpoint:
  `observability/README.md`, `docs/architecture/10-observability.md`,
  `env/.env.observability.example`, `docker/grafana/README.md`. The
  `OBSERVABILITY_SAMPLING=0.0` workaround keeps working and stays documented
  as a sampling knob, but is no longer presented as "the only way to turn
  traces off".

### Non-Goals (explicitly out of scope)

- Changing what `enable_traces=False` / `enable_metrics=False` **construct**.
  Today they only skip the subscriber (`setup.py:240-258`); the
  `TracerProvider` / `MeterProvider` are still built and registered globally.
  That stays as is (see §8 Q1): with no subscriber there are no parrot spans
  or metric points, so nothing is exported, which is the operator-visible
  outcome.
- Per-target protocol, sampling or export interval. `OtlpTarget` keeps only
  `name`/`endpoint`/`headers`; `otlp_protocol` and
  `metric_export_interval_ms` stay global (FEAT-462 decision, `config.py:22-40`).
- Any change to `clients/base.py`, the lifecycle event models, the pluggable
  usage recorders (`recorders/`), `OpenLitUsageRecorder`, or the Prometheus
  (`prometheus_client`) backend.
- Making `histogram_buckets`, `otlp_protocol`, `otlp_headers`,
  `service_version` or `service_instance_id` env-settable. Only the three
  fields named in the problem statement.
- Removing or deprecating `make_metric_exporter()`. It stays as the
  single-config helper (`test_endpoint_composition.py` pins it).

---

## 2. Architectural Design

### Overview

Two small, independent changes plus docs and tests.

**Metrics fan-out** mirrors the span path one-to-one. `exporters.py` gains
`make_metric_exporters(targets, protocol)` — the metric twin of
`make_span_exporters()` (`exporters.py:20-74`): one exporter per target,
http endpoint suffixed `/v1/metrics`, grpc endpoint bare, `headers` forwarded
in the shape each exporter expects (dict for http, tuple of pairs for grpc).
`setup_telemetry()` already computes `targets` (the explicit list, or the
single implicit `OtlpTarget("default", otlp_endpoint, otlp_headers)`,
`setup.py:137-143`) **before** the trace section; the metrics section reuses
that same list, wraps each exporter in its own
`PeriodicExportingMetricReader(exporter, export_interval_millis=config.metric_export_interval_ms)`
and passes the list as `MeterProvider(metric_readers=readers)` — the OTel SDK
supports N readers on one provider natively (verified on opentelemetry-sdk
1.45.1: each provider's `_metric_readers` holds its attached readers), so there is no
composite exporter to write. `shutdown_telemetry()` is unchanged:
`MeterProvider.shutdown()` already flushes every attached reader.

**Env switches** extend `from_env()` (`config.py:300-309` `values` dict) with
three lookups using the existing helpers (`_as_bool`, `config.py:380`; a new
`_as_positive_int` next to `_as_int`, `config.py:397`). The Pydantic field
becomes `metric_export_interval_ms: int = Field(default=60_000, gt=0)` so a
programmatic `ObservabilityConfig(metric_export_interval_ms=0)` fails at
construction, while `from_env()` degrades to the default with a warning on bad
input. Unlike `_as_float`, which only handles parse failures, the new helper
also handles out-of-range values before model validation. `_hash_config()`
(`setup.py:395`) serialises the whole model, so the
idempotency check picks the new values up automatically.

**Why bootstrap.py is untouched.** `_do_bootstrap()` (`bootstrap.py:62-108`)
calls `ObservabilityConfig.from_env()` and, on the `otel` backend, passes that
config straight to `setup_telemetry(config)`. The new fields ride that path
with no code change; a test pins it (§4).

### Routing compatibility and migration

Nonempty `OTLP_TARGETS` replaces `OTEL_EXPORTER_OTLP_ENDPOINT` for **both**
signals; the single endpoint is not an additional metrics destination. The
G2 compatibility guarantee applies only when `otlp_targets=[]`.

This changes the previously documented split configuration:

| Configuration | Before FEAT-705 | After FEAT-705 |
|---|---|---|
| Endpoint = Prometheus; targets = OpenLIT | Metrics to Prometheus; traces to OpenLIT | Both signals to OpenLIT; no metrics to Prometheus |
| Endpoint = Prometheus; targets empty; traces disabled | Metrics to Prometheus | Unchanged |
| Endpoint = collector; targets empty | Both signals to collector | Unchanged |

To preserve metrics-to-Prometheus and traces-to-OpenLIT routing, configure an
OTLP collector with separate signal pipelines: metrics to Prometheus's OTLP
receiver, traces to OpenLIT. Point `OTEL_EXPORTER_OTLP_ENDPOINT` at that
collector, unset `OTLP_TARGETS` (or set it to `[]`), and enable both subscribers
with `OBSERVABILITY_TRACES=true` and `OBSERVABILITY_METRICS=true`. Ensure trace
sampling is nonzero if the old Prometheus-only example set it to `0.0`.
Provisioning that collector is an operator prerequisite, not a new runtime
dependency or implementation module in this feature.

Listing Prometheus and OpenLIT together is not equivalent: both enabled
signals go to each target, and Prometheus rejects `/v1/traces`. Global signal
switches cannot express per-target routing. M4 must document this breaking
change and migration in the README and architecture guide, with a migration
pointer in the env example and Grafana guide.

### Component Diagram

```
ObservabilityConfig.from_env()           (config.py — M3)
   ├─ OBSERVABILITY_TRACES                → enable_traces
   ├─ OBSERVABILITY_METRICS               → enable_metrics
   └─ OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS → metric_export_interval_ms  (gt=0)
            │
            ▼
setup_telemetry(config)                  (setup.py — M2)
   targets = config.otlp_targets or [OtlpTarget("default", otlp_endpoint, otlp_headers)]
   ├─ TracerProvider  ── BatchSpanProcessor(span_exporter[i])   ∀ i   (unchanged, FEAT-462)
   └─ MeterProvider   ── PeriodicExportingMetricReader(metric_exporter[i], interval)  ∀ i   (NEW)
                                   ▲
                      make_metric_exporters(targets, protocol)   (exporters.py — M1)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `exporters.make_span_exporters` | mirrored | `make_metric_exporters` copies its loop/protocol/headers shape (`exporters.py:20-74`) |
| `exporters.make_metric_exporter` | kept | still used by `test_endpoint_composition.py`; no longer called by `setup_telemetry()` |
| `setup.setup_telemetry` | modifies | metrics section (`setup.py:179-209`) switches to the per-target reader list; the `targets` list at `setup.py:137` is reused |
| `config.ObservabilityConfig.from_env` | modifies | three new keys in the `values` dict (`config.py:300-309`) |
| `bootstrap.ensure_observability_bootstrapped` | unchanged | honours the keys through `from_env()` → `setup_telemetry()` (`bootstrap.py:67,89`) |
| `tests/unit/observability/test_env_contract.py` | modifies | `RECOGNISED_ENV_VARS` (`test_env_contract.py:20-29`) must list the three new keys or the updated example file fails AC-2 of FEAT-548 |

### Data Models

```python
# packages/ai-parrot/src/parrot/observability/config.py — changed field only
class ObservabilityConfig(BaseModel):
    ...
    # Metric export tuning
    metric_export_interval_ms: int = Field(default=60_000, gt=0)  # was: int = 60_000  (config.py:211)
```

`OtlpTarget` is unchanged.

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/observability/exporters.py
def make_metric_exporters(targets: list[OtlpTarget], protocol: str = "http/protobuf") -> list[Any]: ...
```

New env keys (all optional, read by `from_env()`):

| Env var | Field | Parsing | Default |
|---|---|---|---|
| `OBSERVABILITY_TRACES` | `enable_traces` | `_as_bool` (`true/1/yes/on`) | `true` |
| `OBSERVABILITY_METRICS` | `enable_metrics` | `_as_bool` | `true` |
| `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS` | `metric_export_interval_ms` | positive int; otherwise default + `logger.warning` | `60000` |

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `make_metric_exporters` | yes | Exact twin of `make_span_exporters` (`exporters.py:20-74`): same signature shape, same lazy imports, same `/v1/metrics` suffix rule as `make_metric_exporter` (`exporters.py:152`), grpc headers as tuple-of-pairs | — |
| M2: per-target metric readers in `setup_telemetry` | yes | Reuse `targets` (`setup.py:137`); one `PeriodicExportingMetricReader` per exporter; `MeterProvider(metric_readers=readers)`; one `logger.info` per target mirroring `setup.py:150-154`; log line at `setup.py:275` unchanged | — |
| M3: env keys + validation in `ObservabilityConfig` | yes | Key names, parsing helpers and fallback rule fixed in §2; `Field(gt=0)`; docstring table rows added | — |
| M4: docs + env example | yes | Exact passages to rewrite listed in §6 Edit Sites; wording constraints in §7 | — |
| M5: tests | yes | Test names and assertions fixed in §4 | — |

### Module 1: `make_metric_exporters`
- **Path**: `packages/ai-parrot/src/parrot/observability/exporters.py`
- **Responsibility**: Build one OTLP metric exporter per `OtlpTarget`, for either protocol, forwarding per-target headers.
- **Depends on**: `OtlpTarget` (`config.py:22`), existing `make_metric_exporter` for the suffix rule.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/observability/exporters.py  (adds after make_span_exporters, exporters.py:74)
  def make_metric_exporters(
      targets: list[OtlpTarget],              # OtlpTarget verified: config.py:22
      protocol: str = "http/protobuf",
  ) -> list[Any]:
      """Return one OTLP metric exporter per *targets* entry (FEAT-705).

      Multi-endpoint counterpart to :func:`make_metric_exporter`, shaped exactly
      like :func:`make_span_exporters` (exporters.py:20). http/protobuf targets get
      ``f"{endpoint.rstrip('/')}/v1/metrics"`` and ``headers`` as a dict (or
      ``None`` when empty); grpc targets get the bare endpoint and headers as a
      tuple of pairs (or ``None``). Same order as *targets*; ``[]`` for ``[]``.

      Raises:
          ImportError: ``protocol="grpc"`` without the grpc exporter package
              (same message as make_metric_exporter, exporters.py:137-140).
      """
  ```

### Module 2: per-target metric readers in `setup_telemetry`
- **Path**: `packages/ai-parrot/src/parrot/observability/setup.py`
- **Responsibility**: Attach one `PeriodicExportingMetricReader` per target to the shared `MeterProvider`, reusing the `targets` list the trace section already derives.
- **Depends on**: Module 1.
- **Interface Skeleton** (no signature change; the touched block is `setup.py:179-209`):
  ```python
  # packages/ai-parrot/src/parrot/observability/setup.py  (modifies setup.py:179 and setup.py:201-209)
  from parrot.observability.exporters import make_metric_exporters  # replaces make_metric_exporter import, setup.py:179

  # --- 3. MeterProvider with histogram Views (FEAT-705: one reader per OTLP target) --
  metric_exporters = make_metric_exporters(targets, protocol=config.otlp_protocol)  # targets verified: setup.py:137
  readers = [
      PeriodicExportingMetricReader(exporter, export_interval_millis=config.metric_export_interval_ms)
      for exporter in metric_exporters
  ]
  # one logger.info("setup_telemetry: attached OTLP metric target '%s' -> %s", target.name, target.endpoint) per target
  meter_provider = MeterProvider(resource=resource, metric_readers=readers, views=views)  # was metric_readers=[reader], setup.py:208
  ```
  Module docstring bullet 3 (`setup.py:13-14`) is updated to say "one
  `PeriodicExportingMetricReader` per OTLP target".

### Module 3: env keys + validation in `ObservabilityConfig`
- **Path**: `packages/ai-parrot/src/parrot/observability/config.py`
- **Responsibility**: Make `enable_traces`, `enable_metrics`, `metric_export_interval_ms` env-settable; validate the interval.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/observability/config.py
  class ObservabilityConfig(BaseModel):
      metric_export_interval_ms: int = Field(default=60_000, gt=0)   # modifies config.py:211

      @classmethod
      def from_env(cls) -> "ObservabilityConfig":                    # modifies config.py:251; docstring table gains 3 rows
          """... (existing docstring) ...
          ``OBSERVABILITY_TRACES``     ``enable_traces``  (FEAT-705)
          ``OBSERVABILITY_METRICS``    ``enable_metrics`` (FEAT-705)
          ``OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS``  ``metric_export_interval_ms``
                                        (FEAT-705; positive int, else default + warning)
          """
          # values dict (config.py:300-309) gains:
          #   "enable_traces": _as_bool(get("OBSERVABILITY_TRACES"), defaults.enable_traces),
          #   "enable_metrics": _as_bool(get("OBSERVABILITY_METRICS"), defaults.enable_metrics),
          #   "metric_export_interval_ms": _as_positive_int(
          #       get("OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS"), defaults.metric_export_interval_ms,
          #       key="OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS"),

  def _as_positive_int(raw: Optional[str], default: int, *, key: str) -> int:   # new, after _as_int (config.py:397-404)
      """Parse a strictly positive int; on None/blank return *default* silently,
      on non-numeric or ``<= 0`` log ``logger.warning("%s=%r is not a positive integer; using %d", key, raw, default)``
      and return *default*. Never raises."""
  ```

### Module 4: docs + env example
- **Path**: `packages/ai-parrot/src/parrot/observability/README.md`, `docs/architecture/10-observability.md`, `env/.env.observability.example`, `docker/grafana/README.md`
- **Responsibility**: Drop every "code-only" / "metrics go to one endpoint only" caveat; document the three keys; present `OBSERVABILITY_TRACES=false` as the way to silence traces and `OBSERVABILITY_SAMPLING` as sampling.
- **Depends on**: M1–M3 (documents what shipped).
- **Interface Skeleton**: not code. Required content, per file:
  - **Migration requirement** — apply §2's routing compatibility and migration contract to all four files. Update the architecture guide's endpoint table row at `:108` as well as its targets row; do not retain advice that the fallback endpoint still receives metrics when explicit targets are set.
  - **README.md** — `## navconfig / env-var keys` table (`README.md:217-233`) gains the three rows; the paragraph at `README.md:101-107` says `OTLP_TARGETS` fans out **traces and metrics** (one span processor and one metric reader per target); the field-table rows `README.md:201-202,211` gain "env: `OBSERVABILITY_…`" mentions; the note at `README.md:235` lists the new auto-boot keys.
  - **10-observability.md** — env block comment (`:64-71`) replaces the `enable_traces is a code-only field` justification with `OBSERVABILITY_TRACES=false`; the `OTLP_TARGETS` paragraph (`:84-88`) says metrics fan out too; table rows `:107,109` rewritten (`OBSERVABILITY_SAMPLING` is a sampling ratio; `OTLP_TARGETS` carries both signals; `OTEL_EXPORTER_OTLP_ENDPOINT` is the single implicit target); the blockquote `:112-117` becomes the three new rows plus "set `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS` to see metrics sooner than 60 s".
  - **env/.env.observability.example** — replace `OBSERVABILITY_SAMPLING=0.0` + its comment (`:28-32`) with `OBSERVABILITY_TRACES=false` + comment; add commented `OBSERVABILITY_METRICS=true` and `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS=60000` examples; fix line `:39` (`OTLP_TARGETS - multi-endpoint export; traces AND metrics`). Every uncommented key must be in `RECOGNISED_ENV_VARS` (M5).
  - **docker/grafana/README.md** — the `.env` block (`:118-123`) uses `OBSERVABILITY_TRACES=false`; the paragraph `:126-130` no longer says the interval "has no env var".

### Module 5: tests
- **Path**: `packages/ai-parrot/tests/unit/observability/` (existing files extended, one new file)
- **Responsibility**: Pin M1–M4. Full list in §4.
- **Depends on**: M1–M4.
- **Interface Skeleton**: see §4 Unit Tests table (names are the contract).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `TestMakeMetricExporters::test_multi_target` | M1 | 2 targets → 2 `OTLPMetricExporter` constructions (patch `opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter`, the origin module — see `test_endpoint_composition.py:19-34`) |
| `TestMakeMetricExporters::test_empty_targets` | M1 | `make_metric_exporters([]) == []` |
| `TestMakeMetricExporters::test_headers_passed_through` | M1 | per-target `headers` reach the exporter kwargs; empty → `None` |
| `TestMakeMetricExporters::test_endpoint_suffix_matches_single_helper` | M1 | one http target yields the same endpoint string as `make_metric_exporter(ObservabilityConfig(otlp_endpoint=…))` — the G2 byte-for-byte guarantee |
| `TestMakeMetricExporters::test_grpc_protocol` | M1 | grpc branch builds the grpc exporter with bare endpoint and tuple headers |
| `TestMakeMetricExporters::test_multiple_targets_preserve_order` | M1 | exporter order == target order |
| `TestSetupTelemetryMetricsFanOut::test_two_targets_attach_two_metric_readers` | M2 | `setup_telemetry` with 2 `otlp_targets` → `len(otel_metrics.get_meter_provider()._metric_readers) == 2` (private attr verified on opentelemetry-sdk 1.45.1; assert `hasattr` first, same discipline as `conftest.py:43-53`) |
| `TestSetupTelemetryMetricsFanOut::test_single_endpoint_fallback_one_reader` | M2 | empty `otlp_targets` → exactly 1 reader |
| `TestSetupTelemetryMetricsFanOut::test_readers_use_configured_interval` | M2 | `metric_export_interval_ms=5_000` reaches every reader (patch `PeriodicExportingMetricReader` where `setup.py` imports it and assert `export_interval_millis=5000` on each call) |
| `TestSetupTelemetryMetricsFanOut::test_span_and_metric_target_counts_match` | M2 | 3 targets → 3 span processors **and** 3 metric readers |
| `TestSetupTelemetryMetricsFanOut::test_reader_count_excludes_other_providers` | M2 | Keep an unrelated `MeterProvider` with an `InMemoryMetricReader` alive while configuring two targets. Assert the configured provider has exactly its two readers and excludes the unrelated reader; shut down the unrelated provider in `finally`. Do not mutate the SDK-wide registry |
| `TestSetupTelemetryMetricsFanOut::test_explicit_targets_override_single_endpoint_for_both_signals` | M2 | Set `otlp_endpoint` to Prometheus and explicit targets to OpenLIT. Capture exporter constructor arguments at their origin modules; assert only OpenLIT receives both signal exporters and no metric exporter uses Prometheus. Use fake exporters to avoid network traffic |
| `TestSetupTelemetryMetricsFanOut::test_signal_switches_skip_subscribers_keep_providers` | M2/M3 | Parametrize traces off, metrics off, and both off. Call real `setup_telemetry()` with fake exporters; assert the corresponding subscribers are absent while both SDK providers and their configured processors/readers still exist |
| `test_from_env_reads_trace_and_metric_switches` | M3 | `OBSERVABILITY_TRACES=false`, `OBSERVABILITY_METRICS=0` → both fields `False` |
| `test_from_env_reads_metric_export_interval` | M3 | `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS=5000` → `5000` |
| `test_from_env_interval_bad_values_fall_back` (parametrized: `""`, `"abc"`, `"0"`, `"-5"`) | M3 | field stays `60_000`; non-blank bad values emit one `WARNING` on `parrot.observability.config` (`caplog`) |
| `test_from_env_switches_absent_use_defaults` | M3 | no env → `True`, `True`, `60_000` (extend `test_absent_env_uses_defaults`, `test_config_from_env.py:16`) |
| `test_metric_export_interval_must_be_positive` | M3 | `ObservabilityConfig(metric_export_interval_ms=0)` raises `pydantic.ValidationError` |
| `test_config_hash_changes_with_new_fields` | M3 | two configs differing only in `enable_traces` have different `_hash_config` digests (so a reconfigure is detected, `setup.py:395`) |
| `test_otel_backend_passes_env_switches_to_setup_telemetry` | M3/boot | in `test_bootstrap.py`, pattern of `test_otel_backend_delegates_to_setup_telemetry` (`:65-85`): with the three env vars set, the config handed to the fake `setup_telemetry` carries `enable_traces=False`, `enable_metrics=True`, `metric_export_interval_ms=5000` |
| `test_every_declared_key_is_read_by_from_env` (existing) | M4/M5 | keeps passing after the example file gains the new keys — `RECOGNISED_ENV_VARS` (`test_env_contract.py:20-29`) extended with the three keys |
| `test_docs_do_not_call_fields_code_only` | M4 | new test in `test_env_contract.py`: none of the four doc files contains the strings `code-only field`, `not settable from the environment`, `traces only, not metrics` or `only env-level way` |

### Integration Tests

| Test | Description |
|---|---|
| `tests/integration/observability/test_poc.py` (existing, unchanged) | Scenarios 1 and 2 keep passing as subscriber-level regression coverage. They construct subscribers manually and do not exercise setup or its config switches; `test_signal_switches_skip_subscribers_keep_providers` in the unit-test table pins those semantics |

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/observability/test_exporters_multi.py
- packages/ai-parrot/tests/unit/observability/test_exporters.py
- packages/ai-parrot/tests/unit/observability/test_endpoint_composition.py
- packages/ai-parrot/tests/unit/observability/test_setup_multi_target.py
- packages/ai-parrot/tests/unit/observability/test_setup_metrics_fanout.py
- packages/ai-parrot/tests/unit/observability/test_setup.py
- packages/ai-parrot/tests/unit/observability/test_config_from_env.py
- packages/ai-parrot/tests/unit/observability/test_config.py
- packages/ai-parrot/tests/unit/observability/test_bootstrap.py
- packages/ai-parrot/tests/unit/observability/test_env_contract.py
- packages/ai-parrot/tests/integration/observability/test_poc.py
markers: none

### Test Data / Fixtures

Nothing new. The package `conftest.py` already resets parrot's setup globals and
the OTel provider latches around every test (`conftest.py:75-82`) and pins
`from_env()` to a clean `os.environ` (`conftest.py:94-126`); the three new keys
start with `OBSERVABILITY` so the hermetic fixture clears them automatically
(`conftest.py:122`).

The reader-isolation regression adds an unrelated provider inside its test and
owns its teardown. Existing global-reset fixtures do not clear the SDK-wide
reader registry and must not be extended to do so. Every reader-count assertion
uses the configured provider's own readers, regardless of other live providers.

---

## 5. Acceptance Criteria

- [ ] AC1. `setup_telemetry()` with N `otlp_targets` registers a `MeterProvider` carrying exactly N `PeriodicExportingMetricReader`s, each wrapping an exporter built from that target's `endpoint` and `headers`.
- [ ] AC2. With `otlp_targets=[]`, exactly one reader is built from `otlp_endpoint`/`otlp_headers`, and its http endpoint string equals what `make_metric_exporter()` produces for the same config (endpoint-routing compatibility for existing configurations with empty targets only; see §2 migration).
- [ ] AC3. Every reader uses `config.metric_export_interval_ms`; `shutdown_telemetry()` is unchanged and still flushes all readers (`MeterProvider.shutdown()`).
- [ ] AC4. `from_env()` maps `OBSERVABILITY_TRACES`, `OBSERVABILITY_METRICS`, `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS` with the parsing rules in §2; absent keys yield `True`/`True`/`60_000`; non-blank invalid interval strings fall back to `60_000` with one warning and never raise for this key; absent or blank values use the default silently.
- [ ] AC5. `ObservabilityConfig(metric_export_interval_ms=<=0)` raises `ValidationError`.
- [ ] AC6. `OBSERVABILITY_ENABLED=true OBSERVABILITY_BACKEND=otel OBSERVABILITY_TRACES=false` reaches `setup_telemetry()` with `enable_traces=False` through `ensure_observability_bootstrapped()` with **no change** to `bootstrap.py` (`git diff --stat` shows no hunk there).
- [ ] AC7. `env/.env.observability.example` uses `OBSERVABILITY_TRACES=false` instead of `OBSERVABILITY_SAMPLING=0.0`, documents the other two keys, and `test_env_contract.py` passes.
- [ ] AC8. None of `observability/README.md`, `docs/architecture/10-observability.md`, `env/.env.observability.example`, `docker/grafana/README.md` still contains `code-only field`, `not settable from the environment`, `traces only, not metrics` or `only env-level way` (test-enforced).
- [ ] AC9. `make_metric_exporter()` still exists with its current signature and `test_endpoint_composition.py` passes unchanged.
- [ ] AC10. All files in the Validation Contract pass; `ruff check` clean on every touched Python file; no new third-party dependency.
- [ ] AC11. With a distinct single endpoint and nonempty explicit targets, both signal exporters use only the explicit targets. Docs explain the breaking change for existing split routing and the collector migration in §2; they do not recommend keeping Prometheus solely in the fallback endpoint to preserve its metrics.
- [ ] AC12. Reader-count tests remain correct with an unrelated live provider, use provider-local readers or constructor capture, and never count or clear the SDK-wide `_all_metric_readers` registry.

---

## 6. Codebase Contract

> Verified against `dev` @ `a32e7d22e` (2026-10-19). Line numbers refer to that commit.

### Verified Imports
```python
from parrot.observability.config import ObservabilityConfig, OtlpTarget   # verified: config.py:22,43; exporters.py:17
from parrot.observability.exporters import make_span_exporters, make_metric_exporter  # verified: exporters.py:20,117
from parrot.observability.setup import setup_telemetry, shutdown_telemetry  # verified: setup.py:63,324
from parrot.observability.errors import ConfigurationError                 # verified: setup.py:39
from pydantic import BaseModel, Field, model_validator                      # verified: config.py:15
from opentelemetry.sdk.metrics import MeterProvider                         # verified: setup.py:100 (lazy, inside setup_telemetry)
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader  # verified: setup.py:103-105 (lazy)
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter   # verified: exporters.py:148-150 (lazy)
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter   # verified: exporters.py:133-135 (lazy)
from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope  # verified: test_bootstrap.py:7
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/observability/config.py
class OtlpTarget(BaseModel):                       # line 22
    name: str                                      # line 37
    endpoint: str                                  # line 38
    headers: dict[str, str] = Field(default_factory=dict)   # line 39

class ObservabilityConfig(BaseModel):              # line 43
    otlp_endpoint: str = "http://localhost:4318"   # line 125
    otlp_protocol: Literal["http/protobuf", "grpc"] = "http/protobuf"  # line 126
    otlp_headers: dict[str, str] = Field(default_factory=dict)        # line 127
    otlp_targets: list[OtlpTarget] = Field(default_factory=list)      # line 128
    enable_traces: bool = True                     # line 132
    enable_metrics: bool = True                    # line 133
    sampling_ratio: float = Field(default=1.0, ge=0.0, le=1.0)        # line 206
    metric_export_interval_ms: int = 60_000        # line 211
    @classmethod
    def from_env(cls) -> "ObservabilityConfig":    # line 251; values dict at 300-309; return cls(**values) at 367

def _env_getter(): ...                             # line 370
def _as_bool(raw: Optional[str], default: bool) -> bool      # line 380
def _as_float(raw: Optional[str], default: float) -> float   # line 387
def _as_int(raw: Optional[str], default: int) -> int         # line 397
def _as_log_level(raw: Optional[str], default: int) -> int   # line 407

# packages/ai-parrot/src/parrot/observability/exporters.py
def make_span_exporters(targets: list[OtlpTarget], protocol: str = "http/protobuf") -> list[Any]  # line 20
def make_span_exporter(config: ObservabilityConfig) -> Any     # line 77
def make_metric_exporter(config: ObservabilityConfig) -> Any   # line 117; http suffix at 152, grpc headers tuple at 141

# packages/ai-parrot/src/parrot/observability/setup.py
_STATE: dict[str, ParrotTelemetryProvider]         # line 46
_METER_PROVIDER: Optional[object]                  # line 49
def setup_telemetry(config: ObservabilityConfig) -> Optional[ParrotTelemetryProvider]  # line 63
#   targets: list[OtlpTarget] = config.otlp_targets or [OtlpTarget(name="default", ...)]  # line 137-143
#   span_exporters = make_span_exporters(targets, protocol=config.otlp_protocol)         # line 148
#   from parrot.observability.exporters import make_metric_exporter                      # line 179
#   metric_exporter = make_metric_exporter(config)                                       # line 201
#   reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=config.metric_export_interval_ms)  # 202-205
#   meter_provider = MeterProvider(resource=resource, metric_readers=[reader], views=views)  # 206-210
#   trace_sub = ... if config.enable_traces else None   # 240-248
#   metrics_sub = ... if config.enable_metrics else None  # 250-258
def shutdown_telemetry() -> None                   # line 324
def _hash_config(config: ObservabilityConfig) -> str   # line 395

# packages/ai-parrot/src/parrot/observability/bootstrap.py  (NOT modified)
def _do_bootstrap() -> None                        # line 62; config = ObservabilityConfig.from_env() at 67; setup_telemetry(config) at 89

# opentelemetry-sdk 1.45.1 (installed; pyproject pins >=1.25,<2.0 at packages/ai-parrot/pyproject.toml:809)
class MeterProvider:  __init__(..., metric_readers: Sequence[MetricReader] = (), ...);  ._metric_readers  (private, instance-owned attached readers)
class PeriodicExportingMetricReader:  __init__(self, exporter, export_interval_millis: float | None = None, export_timeout_millis: float | None = None)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `make_metric_exporters` | `setup_telemetry` metrics section | replaces `make_metric_exporter(config)` call | `setup.py:201` |
| per-target readers | `MeterProvider(metric_readers=…)` | list instead of `[reader]` | `setup.py:208` |
| `from_env` new keys | `ensure_observability_bootstrapped` | `ObservabilityConfig.from_env()` | `bootstrap.py:67` |
| `_as_positive_int` | `from_env` values dict | new entry | `config.py:300-309` |
| env example keys | `test_env_contract.RECOGNISED_ENV_VARS` | frozenset membership | `test_env_contract.py:20-29` |

### Does NOT Exist (Anti-Hallucination)
- ~~`exporters.make_metric_exporters`~~ — created by M1; only the singular `make_metric_exporter` exists today.
- ~~`CompositeMetricExporter` / `MultiMetricExporter`~~ — no such class in the OTel SDK or in parrot; fan-out is N readers on one `MeterProvider`.
- ~~`OtlpTarget.protocol` / `OtlpTarget.export_interval_ms`~~ — per-target protocol/interval are out of scope (§1 Non-Goals); `OtlpTarget` has only `name`, `endpoint`, `headers`.
- ~~`OBSERVABILITY_ENABLE_TRACES` / `OBSERVABILITY_METRIC_INTERVAL`~~ — the key names are exactly `OBSERVABILITY_TRACES`, `OBSERVABILITY_METRICS`, `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS`.
- ~~`MeterProvider._sdk_config.metric_readers`~~ — on opentelemetry-sdk 1.45.1 `SdkConfiguration` has only `exemplar_filter`, `resource`, `views`; attached readers live in the instance’s `_metric_readers`. `_all_metric_readers` is a class-wide weak set for duplicate-registration detection, not a per-provider list.
- ~~`config.py` events.py / `parrot.core.events.lifecycle.events`~~ — the typed events now come from `navigator_eventbus`; nothing in this feature touches them.
- ~~`ensure_observability_bootstrapped(config=...)`~~ — takes no arguments (`bootstrap.py:41`); the env is the only input.
- A blanket claim that `from_env()` never raises is incorrect: for example, `OBSERVABILITY_SAMPLING=2` parses but fails model validation. Only invalid values of the new interval key must fall back without raising.

### Edit Sites (Blueprint Anchors)

Verified against: `a32e7d22e`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/observability/exporters.py` | MODIFY | `def make_metric_exporter(config: ObservabilityConfig) -> Any:` (insert `make_metric_exporters` **before** it, after `make_span_exporter`) | `exporters.py:117` | 1 |
| `packages/ai-parrot/src/parrot/observability/setup.py` | MODIFY | `        from parrot.observability.exporters import make_metric_exporter  # noqa: PLC0415` | `setup.py:179` | 1 |
| `packages/ai-parrot/src/parrot/observability/setup.py` | MODIFY | `        metric_exporter = make_metric_exporter(config)` | `setup.py:201` | 1 |
| `packages/ai-parrot/src/parrot/observability/setup.py` | MODIFY | `            metric_readers=[reader],` | `setup.py:208` | 1 |
| `packages/ai-parrot/src/parrot/observability/setup.py` | MODIFY | `3. Configures a \`\`MeterProvider\`\` with \`\`PeriodicExportingMetricReader\`\` + histogram` (module docstring) | `setup.py:13` | 1 |
| `packages/ai-parrot/src/parrot/observability/config.py` | MODIFY | `    metric_export_interval_ms: int = 60_000` | `config.py:211` | 1 |
| `packages/ai-parrot/src/parrot/observability/config.py` | MODIFY | `            "prometheus_addr": get("OBSERVABILITY_PROM_ADDR") or defaults.prometheus_addr,` (append the three entries after it, inside the `values` dict) | `config.py:309` | 1 |
| `packages/ai-parrot/src/parrot/observability/config.py` | MODIFY | `        \`\`OTLP_TARGETS\`\`             \`\`otlp_targets\`\` (FEAT-462, JSON list)` (docstring table; add rows after) | `config.py:278` | 1 |
| `packages/ai-parrot/src/parrot/observability/config.py` | MODIFY | `def _as_int(raw: Optional[str], default: int) -> int:` (add `_as_positive_int` after this function, before `_as_log_level` at :407) | `config.py:397` | 1 |
| `packages/ai-parrot/src/parrot/observability/README.md` | MODIFY | `set \`OTLP_TARGETS\` instead of the single \`OTEL_EXPORTER_OTLP_ENDPOINT\` — one` | `README.md:102` | 1 |
| `packages/ai-parrot/src/parrot/observability/README.md` | MODIFY | `\| \`OBSERVABILITY_SAMPLING\` \| \`config.sampling_ratio\` \| Float string \`"0.1"\` → 10% sampling. \|` (add three rows after) | `README.md:232` | 1 |
| `packages/ai-parrot/src/parrot/observability/README.md` | MODIFY | `Note: \`setup_telemetry\` itself only auto-reads \`PARROT_PRICING_PATH\`. To build a` | `README.md:235` | 1 |
| `docs/architecture/10-observability.md` | MODIFY | `# Prometheus 2.x serves no /v1/traces, and enable_traces is a code-only field` | `10-observability.md:68` | 1 |
| `docs/architecture/10-observability.md` | MODIFY | `\| \`OBSERVABILITY_SAMPLING\` \| trace sampling ratio (0.0–1.0). **\`0.0\` is the only env-level way to switch traces off** — \`enable_traces\` is code-only (\`config.py:132\`) \| \`1.0\` \|` | `10-observability.md:107` | 1 |
| `docs/architecture/10-observability.md` | MODIFY | `> **Not settable from the environment.** \`enable_traces\` / \`enable_metrics\`` | `10-observability.md:112` | 1 |
| `env/.env.observability.example` | MODIFY | `OBSERVABILITY_SAMPLING=0.0` | `.env.observability.example:32` | 1 |
| `env/.env.observability.example` | MODIFY | `#   OTLP_TARGETS            - multi-endpoint export; traces only, not metrics` | `.env.observability.example:39` | 1 |
| `docker/grafana/README.md` | MODIFY | `\`/v1/traces\`, and \`enable_traces\` is not settable from the environment` | `docker/grafana/README.md:128` | 1 |
| `packages/ai-parrot/tests/unit/observability/test_env_contract.py` | MODIFY | `    "OBSERVABILITY_OPENLIT_RECORDER", "OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT",` (add the three keys to the frozenset) | `test_env_contract.py:28` | 1 |
| `packages/ai-parrot/tests/unit/observability/test_exporters_multi.py` | MODIFY | `class TestMakeSpanExporters:` (append `TestMakeMetricExporters` after the class) | `test_exporters_multi.py:15` | 1 |
| `packages/ai-parrot/tests/unit/observability/test_config_from_env.py` | MODIFY | `def test_from_env_does_not_import_opentelemetry(monkeypatch) -> None:` (append new tests after) | `test_config_from_env.py:62` | 1 |
| `packages/ai-parrot/tests/unit/observability/test_bootstrap.py` | MODIFY | `def test_openlit_flag_no_longer_escalates_to_otel(monkeypatch) -> None:` (insert the new test before it) | `test_bootstrap.py:88` | 1 |
| `packages/ai-parrot/tests/unit/observability/test_setup_metrics_fanout.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Copy the span path, don't redesign it.** `make_metric_exporters` is `make_span_exporters` with `trace_exporter`→`metric_exporter` and `/v1/traces`→`/v1/metrics`; the metrics block in `setup_telemetry` is the span loop at `setup.py:148-154` with readers instead of processors. Lazy imports inside functions, `# noqa: PLC0415`, as everywhere in the package.
- **One log line per target** for metrics, mirroring `setup.py:150-154`, so the boot log shows both signal fan-outs.
- **Invalid interval input must not raise.** Non-blank non-numeric or non-positive values of the new key → default + `logger.warning` on `parrot.observability.config` (same logger the `OTLP_TARGETS` branch uses, `config.py:353`).
- **Patch at the origin module in tests.** `make_metric_exporter(s)` import the exporter class inside the function, so tests patch `opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter` (see `test_endpoint_composition.py:19-34`), and patch `PeriodicExportingMetricReader` on `opentelemetry.sdk.metrics.export` for the interval assertion.
- **Private OTel attribute discipline.** Count only the provider instance’s `_metric_readers`; assert `hasattr` with an explanatory message before using it (the convention `conftest.py:43-53` sets). Never count or clear `_all_metric_readers`: it is a process-wide weak set shared by all providers, and shutdown does not remove its entries. Constructor-argument capture is also valid when testing reader wiring.
- Docs stay in the existing register: short, table-first, line references to code where the current docs have them (update the `config.py:NNN` references you touch, since §3 moves `metric_export_interval_ms` by zero lines but `from_env`'s body grows).

### Known Risks / Gotchas
- **Prometheus has no `/v1/traces`.** With `OTEL_EXPORTER_OTLP_ENDPOINT` pointed at Prometheus and traces left on, every span batch 404s — today's docs solve it with sampling 0.0; after this feature the documented answer is `OBSERVABILITY_TRACES=false`. Keep `OBSERVABILITY_SAMPLING=0.0` working (it does; nothing changes in the sampler) so existing `.env` files are not broken.
- **Fan-out changes existing split routing.** Explicit targets replace the single endpoint for both signals; keeping Prometheus only in `OTEL_EXPORTER_OTLP_ENDPOINT` while listing OpenLIT in `OTLP_TARGETS` drops Prometheus metrics. Follow the collector migration in §2 for separate destinations. Listing Prometheus alongside OpenLIT sends traces to Prometheus too; it is not a supported split-routing workaround. Duplicate entries inside `OTLP_TARGETS` produce duplicate pushes, but an endpoint also present in the ignored fallback does not.
- **N readers = N export threads.** Each `PeriodicExportingMetricReader` runs its own timer thread and collects the provider's instruments independently; with 2–3 targets this is negligible, with a long list it is N collections per interval. Note it in the README; no cap is enforced (same as span processors today).
- **Idempotency hash.** `_hash_config` serialises every field, so merely *reading* the new env keys cannot change the hash of an unchanged `.env`; but a test that sets `OBSERVABILITY_TRACES` and reuses a cached provider from a previous test would hit `ConfigurationError` — the `conftest.py` autouse reset already prevents this.
- **`Field(gt=0)` is a behaviour change for programmatic misuse.** `ObservabilityConfig(metric_export_interval_ms=0)` previously passed model validation, but the OTel reader rejects non-positive intervals during setup; it now raises earlier, at config construction. No in-repo caller passes `<= 0` (`grep -rn metric_export_interval_ms` finds only the field, `setup.py:204`, `test_config.py:28`, docs).
- **`test_env_contract.py` is a tripwire.** Adding a key to the example file without extending `RECOGNISED_ENV_VARS` fails `test_every_declared_key_is_read_by_from_env`. That is intentional (FEAT-548 AC-2); M4 and M5 land in the same task or the test set is red between them.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `opentelemetry-sdk` | `>=1.25,<2.0` (already pinned, `pyproject.toml:809`) | `MeterProvider(metric_readers=[…])` with N readers |
| `opentelemetry-exporter-otlp-proto-http` / `-grpc` | `>=1.25,<2.0` (already pinned, `pyproject.toml:816-817`) | metric exporters per protocol |

No new dependency.

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-705 (`feat-FEAT-705-observability-metrics-fanout-and-env-config`, from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (M2 imports `make_metric_exporters` from M1).
  - M3 has no edge to M1/M2 (different file, different concern) — expected to run concurrently with M1/M2.
  - M4 → M1, M2, M3 (documents what shipped, including the exact log/field names).
  - M5 → M1, M2, M3, M4 (tests pin all of them; the `test_env_contract.py` change must land with M4 — see Known Risks).
- **Shared files**: `setup.py` is touched only by M2; `config.py` only by M3; `exporters.py` only by M1. No file is shared between code modules. `test_env_contract.py` is shared by M4 (through the example file) and M5 — serialize those two tasks or make them one task.
- **Exclusive resources**: none (no extension rebuild, no lockfile, no migration).
- **Cross-feature dependencies**: none. FEAT-548 is merged (`observability-otel-grafana.spec.md`); this spec removes caveats that spec introduced.

---

## 8. Open Questions

- [x] Q1. Should `enable_traces=False` / `enable_metrics=False` also skip building the `TracerProvider` / `MeterProvider` and their exporters? — *Resolved at spec time (author)*: **No.** Keep today's construct-but-skip-subscriber semantics (`setup.py:235-256`, to be pinned by `test_signal_switches_skip_subscribers_keep_providers`; the PoC scenarios only exercise subscribers directly). Without a subscriber no parrot spans/points exist, so nothing is exported; changing construction would widen the diff and risk the global-provider latch behaviour the test suite resets around. Revisit only if a non-parrot span source on the global tracer turns out to matter.
- [x] Q2. Fallback or raise on a bad `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS`? — *Resolved at spec time (author)*: fall back to the default with a warning (G4); invalid values of this new key must not raise, because the auto-boot swallows exceptions at DEBUG (`bootstrap.py:56-57`), which would otherwise silently disable observability on a typo.
- [x] Q3. Keep `make_metric_exporter()`? — *Resolved at spec time (author)*: yes, unchanged; it is the single-config helper that `test_endpoint_composition.py` uses to pin the Prometheus endpoint composition (FEAT-548 AC-1), and `make_metric_exporters` must produce the identical string for one target (AC2).
- [ ] Q4. Should `docker/grafana/README.md`'s `.env` block keep `OBSERVABILITY_SAMPLING=0.0` alongside `OBSERVABILITY_TRACES=false` for one release as a belt-and-braces example, or switch outright? — *Owner: Jesus Lara* (does not block implementation; default is switch outright, consistent with `env/.env.observability.example`).

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: skipped (no accepted exploration document — this spec was seeded from inline notes, and §3b requires an accepted brainstorm/proposal as the neutral brief)
> · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-19 | Jesus Lara | Initial draft (seeded from inline notes; closes the two gaps FEAT-548 left documented) |
| 0.2 | 2026-10-19 | Codex | Resolve review issues `a6bdcdea233a` and `d2985cf2a1bc`: explicit routing migration, provider-local reader contracts and regression tests; correct env-validation and PoC coverage claims. |
