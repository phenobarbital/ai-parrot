---
type: Wiki Overview
title: 'TASK-1228: ObservabilityConfig + parrot.observability package skeleton'
id: doc:sdd-tasks-completed-task-1228-observability-config-skeleton-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 1. Create the `parrot.observability` top-level subpackage
  with public re-exports and the central Pydantic v2 config model. All subsequent
  tasks import from this skeleton.
relates_to:
- concept: mod:parrot.observability
  rel: mentions
- concept: mod:parrot.observability.subscribers.trace
  rel: mentions
---

# TASK-1228: ObservabilityConfig + parrot.observability package skeleton

**Feature**: FEAT-177 — OpenTelemetry + Cost Observability
**Spec**: `sdd/specs/otel-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1227
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Create the `parrot.observability` top-level subpackage with public re-exports and the central Pydantic v2 config model. All subsequent tasks import from this skeleton.

---

## Scope

- Create directory layout for `parrot/observability/` (with `__init__.py`).
- Create `config.py` with `ObservabilityConfig` (Pydantic v2 BaseModel).
- Create `subscribers/__init__.py` and `cost/__init__.py` placeholders so later tasks can `import parrot.observability.subscribers.trace` etc.
- Add two new extras to `pyproject.toml`: `observability` and `observability-openlit`.
- Public re-exports placeholder in `__init__.py` — fill the actual class re-exports as each later task lands.
- Unit tests for `ObservabilityConfig` defaults and validation.

**NOT in scope**: implementing any subscriber, `setup_telemetry`, `CostCalculator`, or exporter helpers — those are later tasks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/__init__.py` | CREATE | Public re-export aggregator (start with `ObservabilityConfig`). |
| `packages/ai-parrot/src/parrot/observability/config.py` | CREATE | `ObservabilityConfig(BaseModel)` per spec §2 Data Models. |
| `packages/ai-parrot/src/parrot/observability/subscribers/__init__.py` | CREATE | Empty namespace package. |
| `packages/ai-parrot/src/parrot/observability/cost/__init__.py` | CREATE | Empty namespace package. |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add `observability` and `observability-openlit` extras. |
| `packages/ai-parrot/tests/unit/observability/test_config.py` | CREATE | Defaults + validation tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pydantic import BaseModel, Field          # used elsewhere in parrot — verify version constraint is v2
from typing import Optional, Literal
```

### Existing Signatures to Use

```python
# packages/ai-parrot/pyproject.toml:458-460 (added by FEAT-176)
otel = [
    "opentelemetry-api>=1.25",
    "opentelemetry-sdk>=1.25",
]
```

Add (do NOT replace the `otel` extra):

```toml
observability = [
    "opentelemetry-api>=1.25,<2.0",
    "opentelemetry-sdk>=1.25,<2.0",
    "opentelemetry-exporter-otlp-proto-http>=1.25,<2.0",
    "opentelemetry-exporter-otlp-proto-grpc>=1.25,<2.0",
]
observability-openlit = [
    "openlit>=1.0",
]
```

### Does NOT Exist

- ~~`parrot.observability.*`~~ — the package does not exist yet; this task creates it.
- ~~Replacing the `otel` extra~~ — the FEAT-176 stub still depends on it. Keep it.

---

## Implementation Notes

### `ObservabilityConfig` — exact field list per spec §2 Data Models

```python
class ObservabilityConfig(BaseModel):
    enabled: bool = False
    service_name: str = "ai-parrot"
    service_version: Optional[str] = None
    service_instance_id: Optional[str] = None
    otlp_endpoint: str = "http://localhost:4318"
    otlp_protocol: Literal["http/protobuf", "grpc"] = "http/protobuf"
    otlp_headers: dict[str, str] = Field(default_factory=dict)
    enable_traces: bool = True
    enable_metrics: bool = True
    enable_cost_tracking: bool = True
    enable_openlit: bool = False
    sampling_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    capture_prompts: bool = False
    capture_completions: bool = False
    metric_export_interval_ms: int = 60_000
    histogram_buckets: Optional[list[float]] = None
    pricing_override_path: Optional[str] = None
```

### Key Constraints

- Pydantic v2 (`BaseModel`, `Field`). If the repo is on v1, escalate to the user before continuing — do not silently downgrade.
- All defaults match the spec — `enabled=False`, `capture_*=False`, `sampling_ratio=1.0`.
- `__init__.py` re-export pattern: start with just `ObservabilityConfig`; later tasks append.

---

## Acceptance Criteria

- [ ] `from parrot.observability import ObservabilityConfig` resolves.
- [ ] `ObservabilityConfig()` constructs successfully with all defaults from spec §2.
- [ ] `ObservabilityConfig(sampling_ratio=1.5)` raises `ValidationError`.
- [ ] Both new pyproject extras present; `otel` extra unchanged.
- [ ] `ruff check packages/ai-parrot/src/parrot/observability/` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_config.py
import pytest
from pydantic import ValidationError
from parrot.observability import ObservabilityConfig


def test_config_defaults():
    cfg = ObservabilityConfig()
    assert cfg.enabled is False
    assert cfg.capture_prompts is False
    assert cfg.capture_completions is False
    assert cfg.sampling_ratio == 1.0
    assert cfg.otlp_endpoint == "http://localhost:4318"
    assert cfg.otlp_protocol == "http/protobuf"
    assert cfg.enable_cost_tracking is True


def test_config_rejects_invalid_sampling():
    with pytest.raises(ValidationError):
        ObservabilityConfig(sampling_ratio=1.5)


def test_config_rejects_unknown_protocol():
    with pytest.raises(ValidationError):
        ObservabilityConfig(otlp_protocol="thrift")
```

---

## Agent Instructions

1. Confirm TASK-1227 is complete.
2. Confirm pydantic v2 is in use (`grep "pydantic" packages/ai-parrot/pyproject.toml`).
3. Create the files per the table.
4. Run `pytest packages/ai-parrot/tests/unit/observability/ -v`.

---

## Completion Note

Implemented by sdd-worker on 2026-05-19. Created `parrot/observability/__init__.py` (with `ObservabilityConfig` re-export), `config.py` (Pydantic v2 model with all spec-mandated fields), `subscribers/__init__.py` placeholder, `cost/__init__.py` placeholder. Added `observability` and `observability-openlit` extras to pyproject.toml without removing the existing `otel` extra. All config defaults verified: `enabled=False`, `capture_prompts=False`, `sampling_ratio=1.0`, etc. Validation rejects `sampling_ratio=1.5` and `otlp_protocol="thrift"` as expected.
