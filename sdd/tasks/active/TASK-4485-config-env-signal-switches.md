# TASK-4485: Env keys for `enable_traces` / `enable_metrics` / `metric_export_interval_ms`

**Feature**: FEAT-705 — Observability — OTLP metrics fan-out and env-level trace/metric switches
**Spec**: `sdd/specs/observability-metrics-fanout-and-env-config.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, AC4, AC5, AC6. Three `ObservabilityConfig` fields are
code-only: `ObservabilityConfig.from_env()` never reads them, and the env
auto-boot builds its config only through `from_env()`. This task adds three
env keys and validates the interval as strictly positive.

`bootstrap.py` is **not** modified: it already calls `from_env()` and passes
the result to `setup_telemetry()` (`bootstrap.py:67,89`). A test pins that path.

This task is independent of TASK-4483/4484 (different files, different concern).

---

## Scope

- Make `metric_export_interval_ms` a `Field(default=60_000, gt=0)`.
- Add `OBSERVABILITY_TRACES`, `OBSERVABILITY_METRICS`, `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS` to the `from_env()` `values` dict.
- Add three rows to the `from_env()` docstring table.
- Add the helper `_as_positive_int(raw, default, *, key)` after `_as_int`.
- Add the M3 tests of spec §4 to `test_config_from_env.py`, `test_config.py` and `test_bootstrap.py`.

**NOT in scope**:
- `bootstrap.py` — must show no diff (AC6).
- Making any other field env-settable (`histogram_buckets`, `otlp_protocol`, `otlp_headers`, …) — spec Non-Goals.
- Changing `_as_int`, `_as_float` or `_as_bool`.
- `test_env_contract.py` and the docs — TASK-4486.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/config.py` | MODIFY | Three env keys, `Field(gt=0)`, `_as_positive_int` |
| `packages/ai-parrot/tests/unit/observability/test_config_from_env.py` | MODIFY | Env-key tests |
| `packages/ai-parrot/tests/unit/observability/test_config.py` | MODIFY | Positive-interval and hash tests |
| `packages/ai-parrot/tests/unit/observability/test_bootstrap.py` | MODIFY | Auto-boot carries the switches |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified on `dev` @ `89a052ec0` (2026-10-19).

### Verified Imports
```python
from pydantic import BaseModel, Field, model_validator      # verified: config.py:15
from parrot.observability import ObservabilityConfig        # verified: test_config.py:11
from parrot.observability.config import ObservabilityConfig  # verified: test_config_from_env.py:7
from parrot.observability.setup import _hash_config          # verified: setup.py:395 (module-level function)
from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope  # verified: test_bootstrap.py:7
from parrot.observability import bootstrap as boot          # verified: test_bootstrap.py:8
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/config.py
logger = logging.getLogger(__name__)               # line 19 → logger name "parrot.observability.config"
class ObservabilityConfig(BaseModel):              # line 43
    enable_traces: bool = True                     # line 132
    enable_metrics: bool = True                    # line 133
    sampling_ratio: float = Field(default=1.0, ge=0.0, le=1.0)  # line 206
    metric_export_interval_ms: int = 60_000        # line 211
    @classmethod
    def from_env(cls) -> "ObservabilityConfig":    # line 251; docstring table row OTLP_TARGETS at 278; values dict 300-310
def _as_bool(raw: Optional[str], default: bool) -> bool    # line 380
def _as_int(raw: Optional[str], default: int) -> int       # line 397 (ends 404)
def _as_log_level(raw: Optional[str], default: int) -> int # line 407

# packages/ai-parrot/src/parrot/observability/setup.py
def _hash_config(config: ObservabilityConfig) -> str       # line 395 — sha256 of model_dump()

# packages/ai-parrot/tests/unit/observability/test_bootstrap.py
def test_otel_backend_delegates_to_setup_telemetry(monkeypatch) -> None  # line 65 — THE PATTERN for the new bootstrap test
def test_openlit_flag_no_longer_escalates_to_otel(monkeypatch) -> None   # line 88 — insert the new test BEFORE it

# packages/ai-parrot/tests/unit/observability/conftest.py
# _hermetic_observability_env (autouse) clears every OBSERVABILITY* key from os.environ (line 122);
# the three new keys start with OBSERVABILITY, so tests start clean.
```

### Does NOT Exist
- ~~`OBSERVABILITY_ENABLE_TRACES` / `OBSERVABILITY_METRIC_INTERVAL`~~ — the key names are exactly `OBSERVABILITY_TRACES`, `OBSERVABILITY_METRICS`, `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS`.
- ~~`_as_positive_int`~~ — this task creates it.
- ~~`ensure_observability_bootstrapped(config=...)`~~ — takes no arguments; the env is the only input.
- ~~"`from_env()` never raises"~~ — false in general (`OBSERVABILITY_SAMPLING=2` fails model validation). Only the new interval key must never raise.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/observability/config.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_config_from_env.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_config.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_bootstrap.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/config.py#ObservabilityConfig",
    "sym:packages/ai-parrot/src/parrot/observability/config.py#ObservabilityConfig.from_env",
    "sym:packages/ai-parrot/src/parrot/observability/config.py#_as_bool",
    "sym:packages/ai-parrot/src/parrot/observability/config.py#_as_int",
    "sym:packages/ai-parrot/src/parrot/observability/setup.py#_hash_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Absent or blank interval → default, **silently**. Non-blank non-numeric or `<= 0` → default **plus exactly one** `logger.warning` (AC4).
- The helper validates range *before* model construction, so `Field(gt=0)` never fires from the env path.
- `_as_bool` already returns the default for `None`, so absent switches stay `True`.

---

## Implementation Blueprint

### Steps (in order)
1. Change the field at `config.py:211` — *why*: AC5, programmatic misuse fails at construction.
2. Add the three docstring rows after the `OTLP_TARGETS` row — *why*: the docstring table is the in-code reference for the env keys.
3. Add the three `values` entries after `prometheus_addr` — *why*: G3.
4. Add `_as_positive_int` after `_as_int` — *why*: G4, typo-tolerant boot.
5. Add the tests, then run the Validation Commands.

### `packages/ai-parrot/src/parrot/observability/config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    metric_export_interval_ms: int = 60_000' config.py)
# REPLACE line 211 with:
    metric_export_interval_ms: int = Field(default=60_000, gt=0)

# occurrences: 1 (verified: grep -c '``OTLP_TARGETS``             ``otlp_targets`` (FEAT-462, JSON list)' config.py)
# AFTER — insert below the OTLP_TARGETS docstring row (verified: config.py:278), same column alignment:
        ``OBSERVABILITY_TRACES``     ``enable_traces`` (FEAT-705)
        ``OBSERVABILITY_METRICS``    ``enable_metrics`` (FEAT-705)
        ``OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS``  ``metric_export_interval_ms``
                                      (FEAT-705; positive int, else the
                                      default plus one warning)

# occurrences: 1 (verified: grep -c '"prometheus_addr": get("OBSERVABILITY_PROM_ADDR") or defaults.prometheus_addr,' config.py)
# AFTER — insert below that line, still inside the `values` dict (verified: config.py:309):
            "enable_traces": _as_bool(get("OBSERVABILITY_TRACES"), defaults.enable_traces),
            "enable_metrics": _as_bool(get("OBSERVABILITY_METRICS"), defaults.enable_metrics),
            "metric_export_interval_ms": _as_positive_int(
                get("OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS"),
                defaults.metric_export_interval_ms,
                key="OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS",
            ),

# occurrences: 1 (verified: grep -c 'def _as_int(raw: Optional\[str\], default: int) -> int:' config.py)
# AFTER — insert below the whole `_as_int` function (lines 397-404), before `def _as_log_level(` (line 407):
def _as_positive_int(raw: Optional[str], default: int, *, key: str) -> int:
    """Parse a strictly positive int (FEAT-705).

    Absent or blank input returns *default* silently. Non-numeric or
    non-positive input logs one warning naming *key* and returns *default*.
    Never raises, so a typo cannot disable the env auto-boot.

    Args:
        raw: Raw env value, or ``None`` when unset.
        default: Value to use when *raw* is unusable.
        key: Env var name, used only in the warning.

    Returns:
        The parsed positive int, or *default*.
    """
    if raw is None or str(raw).strip() == "":
        return default
    # FILL IN: int(str(raw).strip()); on (TypeError, ValueError) or value <= 0 →
    #          logger.warning("%s=%r is not a positive integer; using %d", key, raw, default) and
    #          return default — bounded by AC4 (exactly one warning, never raise)
```
**Why**: spec §3 Module 3 skeleton fixes the helper name, its keyword-only
`key` and the warning text.

### `packages/ai-parrot/tests/unit/observability/test_config_from_env.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_from_env_does_not_import_opentelemetry(monkeypatch) -> None:' test_config_from_env.py)
# AFTER — append at end of file (that function ends at line 73). Add `import pytest` to the imports.
def test_from_env_reads_trace_and_metric_switches(monkeypatch) -> None:
    # FILL IN: OBSERVABILITY_TRACES=false, OBSERVABILITY_METRICS=0 → both False
    ...


def test_from_env_reads_metric_export_interval(monkeypatch) -> None:
    # FILL IN: OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS=5000 → 5000
    ...


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5"])
def test_from_env_interval_bad_values_fall_back(monkeypatch, caplog, raw) -> None:
    # FILL IN: field stays 60_000; caplog at WARNING on "parrot.observability.config";
    #          blank → 0 warnings, the others → exactly 1 warning — AC4
    ...


def test_from_env_switches_absent_use_defaults() -> None:
    # FILL IN: no env → enable_traces True, enable_metrics True, metric_export_interval_ms 60_000
    ...
```

### `packages/ai-parrot/tests/unit/observability/test_config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_config_custom_histogram_buckets() -> None:' test_config.py)
# AFTER — append at end of file (line 89):
@pytest.mark.parametrize("value", [0, -1])
def test_metric_export_interval_must_be_positive(value: int) -> None:
    """metric_export_interval_ms <= 0 is rejected at construction (FEAT-705 AC5)."""
    with pytest.raises(ValidationError):
        ObservabilityConfig(metric_export_interval_ms=value)


def test_config_hash_changes_with_new_fields() -> None:
    """A reconfigure that only flips enable_traces is detected by _hash_config."""
    from parrot.observability.setup import _hash_config

    # FILL IN: assert _hash_config(ObservabilityConfig(enable_traces=True)) !=
    #          _hash_config(ObservabilityConfig(enable_traces=False))
```

### `packages/ai-parrot/tests/unit/observability/test_bootstrap.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_openlit_flag_no_longer_escalates_to_otel(monkeypatch) -> None:' test_bootstrap.py)
# BEFORE — insert above that function (line 88), with two blank lines after:
def test_otel_backend_passes_env_switches_to_setup_telemetry(monkeypatch) -> None:
    """FEAT-705 AC6: the three env keys reach setup_telemetry via the auto-boot."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_BACKEND", "otel")
    monkeypatch.setenv("OBSERVABILITY_TRACES", "false")
    monkeypatch.setenv("OBSERVABILITY_METRICS", "true")
    monkeypatch.setenv("OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS", "5000")
    # FILL IN: copy the fake-setup + monkeypatch.setattr(setup_mod, "setup_telemetry", _fake_setup)
    #          + `with scope(): boot.ensure_observability_bootstrapped()` pattern from
    #          test_otel_backend_delegates_to_setup_telemetry (line 65); assert the captured config has
    #          enable_traces False, enable_metrics True, metric_export_interval_ms 5000
```

### FILL IN checklist
- [ ] `config.py::_as_positive_int` body — AC4
- [ ] four `test_config_from_env.py` bodies
- [ ] `test_config_hash_changes_with_new_fields` assertion
- [ ] `test_otel_backend_passes_env_switches_to_setup_telemetry` body — AC6

---

## Acceptance Criteria

- [ ] `from_env()` maps the three keys; absent → `True`/`True`/`60_000` (spec AC4).
- [ ] Non-blank invalid interval → `60_000` with exactly one warning; blank → `60_000` silently; never raises (AC4).
- [ ] `ObservabilityConfig(metric_export_interval_ms=0)` raises `ValidationError` (AC5).
- [ ] The auto-boot hands `setup_telemetry` a config carrying the env values, and `git diff --stat` shows no change to `bootstrap.py` (AC6).
- [ ] Existing tests in the three test files still pass.
- [ ] `ruff check` clean on all four files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_config_from_env.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_config.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_bootstrap.py -q`

---

## Test Specification

See the three test blueprint blocks above; names are fixed by spec §4.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug observability-metrics-fanout-and-env-config --feature-id FEAT-705`).
2. **Check dependencies**: none.
3. **Verify the Codebase Contract** before writing code.
4. **Update status** → `"in-progress"` in `sdd/tasks/index/observability-metrics-fanout-and-env-config.json`.
5. **Implement** from the blueprint; complete every `FILL IN`.
6. **Run** the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
7. **Commit** only the four listed files.
8. **Close** with `scripts/sdd/close_task.sh TASK-4485 observability-metrics-fanout-and-env-config verified`.
9. **Fill in** the Completion Note and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
