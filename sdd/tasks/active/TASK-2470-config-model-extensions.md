# TASK-2470: Config Model Extensions

**Feature**: FEAT-462 — Unified Telemetry Bus
**Spec**: `sdd/specs/unified-telemetry-bus.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-462. It adds the `OtlpTarget` Pydantic
model and new config fields to `ObservabilityConfig` that all downstream tasks
depend on: multi-endpoint OTLP targets, OpenLIT recorder enablement, and
deprecation warnings for the legacy `enable_openlit`/`enable_traceloop` flags.

Implements spec §3 Module 1.

---

## Scope

- Add `OtlpTarget` Pydantic model (name, endpoint, headers)
- Add `otlp_targets: list[OtlpTarget]` field to `ObservabilityConfig`
- Add `openlit_recorder_endpoint: str | None` field to `ObservabilityConfig`
- Add `OTLP_TARGETS` env var (JSON list) parsing to `from_env()`
- Add `OBSERVABILITY_OPENLIT_RECORDER` env var parsing to `from_env()`
- Deprecate `enable_openlit` and `enable_traceloop`: emit `DeprecationWarning` on truthy
- Deprecate `"traceloop"` as a `UsageBackend` value: map to `"otel"` with a warning
- Write unit tests for all new/modified behavior

**NOT in scope**: Multi-endpoint exporter factory (TASK-2471), setup_telemetry refactor (TASK-2474), bootstrap changes (TASK-2475).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/config.py` | MODIFY | Add `OtlpTarget`, `otlp_targets`, `openlit_recorder_endpoint`, deprecation validators, env var parsing |
| `packages/ai-parrot/tests/observability/test_config_extensions.py` | CREATE | Unit tests for new config fields and deprecation warnings |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot.observability.config import ObservabilityConfig  # config.py:18
# ObservabilityConfig is a Pydantic BaseModel
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/config.py:18
class ObservabilityConfig(BaseModel):
    enabled: bool = False                                    # line 88
    otlp_endpoint: str = "http://localhost:4318"             # line 94
    otlp_protocol: Literal["http/protobuf", "grpc"]          # line 95
    otlp_headers: dict[str, str] = Field(default_factory=dict)  # line 96
    enable_openlit: bool = False                              # line 102
    enable_traceloop: bool = False                            # line 103
    openlit_disabled_instrumentors: list[str]                 # line 128
    openlit_log_level: int = logging.WARNING                  # line 149
    openlit_disable_metrics: bool = True                      # line 162
    usage_backend: UsageBackend = "none"                     # line 177
    # classmethod
    def from_env(cls) -> ObservabilityConfig:                # line 183
```

### Does NOT Exist
- ~~`OtlpTarget`~~ — does not exist yet; must be created in this task
- ~~`ObservabilityConfig.otlp_targets`~~ — does not exist; must be added
- ~~`ObservabilityConfig.openlit_recorder_endpoint`~~ — does not exist; must be added
- ~~`OTLP_TARGETS` env var handling~~ — not in `from_env()` today
- ~~`OBSERVABILITY_OPENLIT_RECORDER` env var handling~~ — not in `from_env()` today

---

## Implementation Notes

### Pattern to Follow
```python
# OtlpTarget model — define ABOVE ObservabilityConfig in the same file
class OtlpTarget(BaseModel):
    """One OTLP export destination."""
    name: str                          # human label ("openlit", "tempo")
    endpoint: str                      # OTLP base URL
    headers: dict[str, str] = Field(default_factory=dict)  # auth headers

# Deprecation — use a model_validator for the boolean fields
import warnings

@model_validator(mode="after")
def _warn_deprecated_flags(self) -> "ObservabilityConfig":
    if self.enable_openlit:
        warnings.warn(
            "enable_openlit is deprecated — configure an OTLP target instead. "
            "See FEAT-462.",
            DeprecationWarning,
            stacklevel=2,
        )
    if self.enable_traceloop:
        warnings.warn(
            "enable_traceloop is deprecated — configure an OTLP target instead. "
            "See FEAT-462.",
            DeprecationWarning,
            stacklevel=2,
        )
    return self

# OTLP_TARGETS env var parsing in from_env()
import json
targets_raw = os.environ.get("OTLP_TARGETS")
if targets_raw:
    try:
        targets = [OtlpTarget(**t) for t in json.loads(targets_raw)]
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Malformed OTLP_TARGETS env var, ignoring: %s", e)
        targets = []

# "traceloop" backend deprecation — in from_env() or a validator
if usage_backend == "traceloop":
    logger.warning("usage_backend='traceloop' is deprecated, mapping to 'otel'")
    usage_backend = "otel"
```

### Key Constraints
- Keep `enable_openlit` and `enable_traceloop` fields present (backward compat) — only warn
- `OtlpTarget` must be defined BEFORE `ObservabilityConfig` in the same file
- `OTLP_TARGETS` is a JSON list; malformed JSON must be caught, logged, and ignored
- `otlp_targets` defaults to empty list (single-endpoint fallback via `otlp_endpoint`)

---

## Acceptance Criteria

- [ ] `OtlpTarget` model can be constructed: `OtlpTarget(name="x", endpoint="http://...")`
- [ ] `ObservabilityConfig(otlp_targets=[...])` accepts a list of `OtlpTarget`
- [ ] `ObservabilityConfig.from_env()` reads `OTLP_TARGETS` JSON env var
- [ ] `ObservabilityConfig.from_env()` reads `OBSERVABILITY_OPENLIT_RECORDER` env var
- [ ] `ObservabilityConfig(enable_openlit=True)` emits `DeprecationWarning`
- [ ] `ObservabilityConfig(enable_traceloop=True)` emits `DeprecationWarning`
- [ ] `usage_backend="traceloop"` maps to `"otel"` with a warning log
- [ ] All tests pass: `pytest packages/ai-parrot/tests/observability/test_config_extensions.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/observability/config.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/observability/test_config_extensions.py
import json
import os
import warnings
import pytest
from parrot.observability.config import ObservabilityConfig, OtlpTarget


class TestOtlpTarget:
    def test_construction(self):
        t = OtlpTarget(name="openlit", endpoint="http://localhost:4318")
        assert t.name == "openlit"
        assert t.endpoint == "http://localhost:4318"
        assert t.headers == {}

    def test_with_headers(self):
        t = OtlpTarget(
            name="tempo",
            endpoint="http://tempo:4318",
            headers={"Authorization": "Bearer tok"},
        )
        assert t.headers["Authorization"] == "Bearer tok"


class TestOtlpTargetsEnvParsing:
    def test_parses_json_list(self, monkeypatch):
        targets = [{"name": "a", "endpoint": "http://a:4318"}]
        monkeypatch.setenv("OTLP_TARGETS", json.dumps(targets))
        monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
        cfg = ObservabilityConfig.from_env()
        assert len(cfg.otlp_targets) == 1
        assert cfg.otlp_targets[0].name == "a"

    def test_malformed_json_falls_back(self, monkeypatch):
        monkeypatch.setenv("OTLP_TARGETS", "not json")
        monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
        cfg = ObservabilityConfig.from_env()
        assert cfg.otlp_targets == []


class TestDeprecationWarnings:
    def test_enable_openlit_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ObservabilityConfig(enable_openlit=True)
            depr = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert any("enable_openlit" in str(d.message) for d in depr)

    def test_enable_traceloop_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ObservabilityConfig(enable_traceloop=True)
            depr = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert any("enable_traceloop" in str(d.message) for d in depr)

    def test_traceloop_backend_maps_to_otel(self, monkeypatch):
        monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
        monkeypatch.setenv("OBSERVABILITY_BACKEND", "traceloop")
        cfg = ObservabilityConfig.from_env()
        assert cfg.usage_backend == "otel"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/unified-telemetry-bus.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `ObservabilityConfig` is still at config.py:18 with the listed fields
4. **Update status** in `sdd/tasks/index/unified-telemetry-bus.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2470-config-model-extensions.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
