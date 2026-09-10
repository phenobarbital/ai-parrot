# TASK-3114: Contract tests for the env example, provisioning and OTLP endpoint

**Feature**: FEAT-548 — Observability — OTEL to Prometheus + Grafana usage/cost dashboard
**Spec**: `sdd/specs/observability-otel-grafana.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3107
**Assigned-to**: unassigned

---

## Context

Implements the remaining rows of spec §4 (unit rows 5-6, both integration rows).
These lock down the three facts most likely to be silently broken by a future
edit:

1. The committed env example documents only variables that actually do something
   — `OBSERVABILITY_OPENLIT` became a no-op and stayed in `.env` for months.
2. `OTEL_EXPORTER_OTLP_ENDPOINT` is a **base** URL; writing the full
   `/v1/metrics` path doubles it.
3. `OBSERVABILITY_SAMPLING=0.0` really does stop span export while metrics keep
   recording — the mechanism the whole wiring depends on.

Shares no files with any other task in this feature — safe to run in parallel.

---

## Scope

- `test_env_example_matches_config_contract`
- `test_provisioning_yaml_parses` (may live with TASK-3109's test file — see note)
- `test_otlp_endpoint_composes_to_prometheus_path`
- `test_zero_sampling_emits_no_spans`

**NOT in scope**: dashboard content assertions (TASK-3113); any live-stack query.
All four must pass offline.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/unit/observability/test_env_contract.py` | CREATE | Env example ↔ `from_env()` contract |
| `packages/ai-parrot/tests/unit/observability/test_endpoint_composition.py` | CREATE | Base-URL composition + sampling kill-switch |

> `test_provisioning_yaml_parses` is specified in TASK-3109's Test Specification.
> Implement it there; do not duplicate it here.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.observability.config import ObservabilityConfig  # verified: config.py:42
from parrot.observability.exporters import make_metric_exporter  # verified: exporters.py:117
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/observability/config.py
class ObservabilityConfig(BaseModel):              # line 42
    otlp_endpoint: str = "http://localhost:4318"   # line 125
    otlp_protocol: Literal["http/protobuf", "grpc"] = "http/protobuf"
    sampling_ratio: float = 1.0                    # line 206  (ge=0.0, le=1.0)
    @classmethod
    def from_env(cls) -> "ObservabilityConfig": ...  # line 251

# packages/ai-parrot/src/parrot/observability/exporters.py
def make_metric_exporter(config: ObservabilityConfig) -> Any:      # line 117
    endpoint = f"{config.otlp_endpoint.rstrip('/')}/v1/metrics"    # line 152
    return OTLPMetricExporter(endpoint=endpoint, headers=headers)  # line 154

# The env vars from_env() recognises (verified config.py:264-360) — the exact set
# test_env_example_matches_config_contract validates against:
#   OBSERVABILITY_ENABLED, OBSERVABILITY_BACKEND, OBSERVABILITY_SERVICE_NAME,
#   OBSERVABILITY_COST, OBSERVABILITY_LOG_LEVEL, OBSERVABILITY_SAMPLING,
#   OBSERVABILITY_OPENLIT, OBSERVABILITY_OPENLIT_DISABLE,
#   OBSERVABILITY_OPENLIT_LOG_LEVEL, OBSERVABILITY_OPENLIT_DISABLE_METRICS,
#   OBSERVABILITY_TRACELOOP, OBSERVABILITY_CAPTURE_CONTENT,
#   OTEL_EXPORTER_OTLP_ENDPOINT, OBSERVABILITY_PROM_PORT, OBSERVABILITY_PROM_ADDR,
#   PARROT_PRICING_PATH, OTLP_TARGETS, OBSERVABILITY_OPENLIT_RECORDER,
#   OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT

# Existing conventions to match:
# packages/ai-parrot/tests/unit/observability/test_config_from_env.py
# packages/ai-parrot/tests/unit/observability/test_exporters.py
```

### Does NOT Exist

- ~~`OBSERVABILITY_TRACES`~~ / ~~`OBSERVABILITY_METRICS_INTERVAL`~~ — no such env
  vars; the example file must not invent them and the test enforces that.
- ~~`make_metric_exporter` reading `otlp_targets`~~ — metrics use
  `otlp_endpoint` alone (`exporters.py:152`). Only traces fan out
  (`setup.py:137`).
- ~~a public accessor for the composed endpoint~~ — `OTLPMetricExporter` stores
  it privately. See Key Constraints for how to assert it.

---

## Implementation Notes

### Key Constraints

- `OTLPMetricExporter` does not expose the endpoint as a documented public
  attribute. Do **not** assert on a private attribute without a fallback:
  prefer monkeypatching the exporter class and capturing the `endpoint` kwarg.
  That asserts the contract this feature depends on — the URL passed in — rather
  than an SDK internal.
- These tests need the `observability` extra for the exporter import. Guard with
  `pytest.importorskip("opentelemetry")` so the suite still collects without it —
  the opposite of TASK-3113, where skipping would defeat the purpose.
- Use `monkeypatch.setenv` / `delenv`; never mutate `os.environ` directly.
  `from_env()` reads through navconfig with an `os.environ` fallback
  (`config.py:472-482`).

---

## Implementation Blueprint

### Steps (in order)

1. Write the env-example contract test — *why*: it is pure file parsing, no
   optional deps, and it is the one that catches dead config.
2. Write the endpoint composition test by capturing the constructor kwarg —
   *why*: asserting the passed URL is stable across SDK versions, unlike poking
   at a private attribute.
3. Write the sampling test asserting spans stop *and* metrics continue — *why*:
   only asserting "no spans" would also pass if telemetry were entirely broken.

### `packages/ai-parrot/tests/unit/observability/test_env_contract.py` (CREATE)

```python
"""The committed env example must document only variables that do something.

FEAT-548 AC-2. ``OBSERVABILITY_OPENLIT`` sat in ``env/.env`` long after FEAT-462
turned it into a no-op; this test stops the example file from acquiring the same
kind of dead entry.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLE = REPO_ROOT / "env/.env.observability.example"

# Verified from ObservabilityConfig.from_env() (config.py:264-360).
RECOGNISED_ENV_VARS: frozenset[str] = frozenset({
    "OBSERVABILITY_ENABLED", "OBSERVABILITY_BACKEND", "OBSERVABILITY_SERVICE_NAME",
    "OBSERVABILITY_COST", "OBSERVABILITY_LOG_LEVEL", "OBSERVABILITY_SAMPLING",
    "OBSERVABILITY_OPENLIT", "OBSERVABILITY_OPENLIT_DISABLE",
    "OBSERVABILITY_OPENLIT_LOG_LEVEL", "OBSERVABILITY_OPENLIT_DISABLE_METRICS",
    "OBSERVABILITY_TRACELOOP", "OBSERVABILITY_CAPTURE_CONTENT",
    "OTEL_EXPORTER_OTLP_ENDPOINT", "OBSERVABILITY_PROM_PORT",
    "OBSERVABILITY_PROM_ADDR", "PARROT_PRICING_PATH", "OTLP_TARGETS",
    "OBSERVABILITY_OPENLIT_RECORDER", "OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT",
})

_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _declared_keys() -> set[str]:
    """Uncommented KEY=VALUE assignments in the example file."""
    body = "\n".join(
        line for line in EXAMPLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    return set(_ASSIGNMENT.findall(body))


def test_example_file_exists_and_is_committed():
    """env/.env is git-ignored, so the example is the only versioned record."""
    assert EXAMPLE.is_file(), f"{EXAMPLE} is missing (AC-2)"


def test_every_declared_key_is_read_by_from_env():
    """No dead configuration: every key must actually reach ObservabilityConfig."""
    unknown = _declared_keys() - RECOGNISED_ENV_VARS
    assert not unknown, (
        f"{EXAMPLE.name} declares {sorted(unknown)}, which "
        f"ObservabilityConfig.from_env() never reads"
    )


def test_endpoint_is_a_base_url():
    """The exporter appends /v1/metrics; a full path here doubles it."""
    text = EXAMPLE.read_text(encoding="utf-8")
    # FILL IN: assert the OTEL_EXPORTER_OTLP_ENDPOINT value has no /v1/ segment —
    # bounded by exporters.py:152 (the suffix is appended, never supplied)


def test_example_contains_no_secrets():
    """The [observability] block has no credentials; keep it that way."""
    # FILL IN: assert no key/value resembling an API key or password —
    # bounded by "env/.env holds live credentials and must never be echoed"
```

**Why this shape**: parsing the file rather than importing config keeps this test
dependency-free, so it runs everywhere. `RECOGNISED_ENV_VARS` is a literal copy
of `from_env`'s recognised set — if someone adds a variable to the config, this
test correctly fails until the list is updated deliberately.

### `packages/ai-parrot/tests/unit/observability/test_endpoint_composition.py` (CREATE)

```python
"""OTLP endpoint composition and the sampling kill-switch.

FEAT-548 AC-1/AC-6. The endpoint in .env is a BASE url; the exporter appends the
signal path. Traces are silenced by sampling because ``enable_traces`` is not
env-settable (config.py:132).
"""
from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry")  # needs the `observability` extra

from parrot.observability.config import ObservabilityConfig  # noqa: E402
from parrot.observability import exporters  # noqa: E402

PROM_BASE = "http://localhost:9090/api/v1/otlp"


def test_otlp_endpoint_composes_to_prometheus_path(monkeypatch):
    """The Prometheus base URL must yield exactly .../api/v1/otlp/v1/metrics."""
    captured: dict[str, str] = {}

    class _Spy:
        def __init__(self, endpoint: str, headers=None):
            captured["endpoint"] = endpoint

    # FILL IN: monkeypatch the OTLPMetricExporter symbol that make_metric_exporter
    # imports at call time (it is a function-local import, exporters.py:148-154) —
    # bounded by "assert the URL passed in, never an SDK private attribute"

    make = exporters.make_metric_exporter
    make(ObservabilityConfig(otlp_endpoint=PROM_BASE))
    assert captured["endpoint"] == f"{PROM_BASE}/v1/metrics"


@pytest.mark.parametrize("given", [PROM_BASE, PROM_BASE + "/"])
def test_trailing_slash_is_tolerated(given):
    """A trailing slash must not produce a doubled separator."""
    # FILL IN: same capture as above; assert the result never contains '//v1/'
    # — bounded by exporters.py:152 (`.rstrip('/')`)


def test_zero_sampling_emits_no_spans():
    """sampling_ratio=0.0 stops span export while metrics keep recording.

    Asserting only "no spans" would also pass if telemetry were entirely broken,
    so this must assert the metric side still works.
    """
    # FILL IN: build a TracerProvider with TraceIdRatioBased(0.0) exactly as
    # setup_telemetry does (setup.py:144-146), start a span, and assert it is
    # non-recording; then assert an InMemoryMetricReader still receives a
    # recorded counter — bounded by AC-6.
```

**Why this shape**: capturing the constructor kwarg pins the one thing this
feature actually depends on — the URL handed to the exporter — without coupling
to SDK internals that change between versions. The sampling test deliberately
asserts both halves so it cannot pass vacuously.

### FILL IN checklist

- [ ] `test_endpoint_is_a_base_url` assertion — bounded by `exporters.py:152`.
- [ ] `test_example_contains_no_secrets` heuristic — bounded by "env/.env holds
      live credentials".
- [ ] Monkeypatch target for `OTLPMetricExporter` — it is a **function-local**
      import (`exporters.py:148`), so patching the module attribute will not work;
      patch where it is looked up. Bounded by "assert the URL, not an internal".
- [ ] `test_zero_sampling_emits_no_spans` body — bounded by AC-6 and by
      "must also assert metrics still record".

---

## Acceptance Criteria

- [ ] **AC-12** `pytest packages/ai-parrot/tests/unit/observability/test_env_contract.py packages/ai-parrot/tests/unit/observability/test_endpoint_composition.py -v` passes.
- [ ] `test_env_contract.py` imports no `opentelemetry` symbol and passes without
      the `observability` extra.
- [ ] `test_endpoint_composition.py` skips cleanly (not errors) when the extra is
      absent.
- [ ] No test asserts on a private attribute of an SDK exporter object.
- [ ] **AC-14** The existing suite still passes:
      `pytest packages/ai-parrot/tests/unit/observability/ -q`

---

## Test Specification

This task *is* the tests. Meta-criterion: temporarily set the example's endpoint
to `http://localhost:9090/api/v1/otlp/v1/metrics` and confirm
`test_endpoint_is_a_base_url` fails — proving it catches the doubled-path trap.

---

## Agent Instructions

Standard SDD task flow. Depends on TASK-3107 only for the example file's
existence; everything else is offline. Safe to run in a parallel worktree.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
