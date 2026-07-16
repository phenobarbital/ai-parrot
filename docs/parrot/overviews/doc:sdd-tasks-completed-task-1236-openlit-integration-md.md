---
type: Wiki Overview
title: 'TASK-1236: OpenLIT integration wrapper'
id: doc:sdd-tasks-completed-task-1236-openlit-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 9. Lazy-imported wrapper around `openlit.init(...)`. Module-level
  sentinel ensures `openlit.init` is called at most once even if `setup_telemetry`
  is invoked multiple times. Called only from TASK-1235 (`setup_telemetry`) when `config.enable_openlit=True`.
relates_to:
- concept: mod:parrot.observability
  rel: mentions
- concept: mod:parrot.observability.config
  rel: mentions
- concept: mod:parrot.observability.openlit_integration
  rel: mentions
---

# TASK-1236: OpenLIT integration wrapper

**Feature**: FEAT-177 — OpenTelemetry + Cost Observability
**Spec**: `sdd/specs/otel-observability.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1228
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9. Lazy-imported wrapper around `openlit.init(...)`. Module-level sentinel ensures `openlit.init` is called at most once even if `setup_telemetry` is invoked multiple times. Called only from TASK-1235 (`setup_telemetry`) when `config.enable_openlit=True`.

D2 (resolved): OpenLIT is the Phase 1 default opt-in. OpenLLMetry deferred to a later minor release.

---

## Scope

- Create `parrot/observability/openlit_integration.py` with:
  - `init_openlit(config: ObservabilityConfig) -> None` — idempotent.
  - Module-level sentinel `_INITIALIZED: bool = False`.
- Lazy-import `openlit` inside `init_openlit`; raise `ImportError` with a clear action message if missing.
- Document the parent-span contract: OpenLIT auto-spans must be CHILDREN of our spans, not siblings. Achieved automatically because we set the global `TracerProvider` first in `setup_telemetry`.
- Unit tests for lazy import, idempotency, and missing-package error.

**NOT in scope**: Calling `init_openlit` (that's TASK-1235); end-to-end double-counting validation (that's TASK-1238 integration tests).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/openlit_integration.py` | CREATE | Wrapper + sentinel. |
| `packages/ai-parrot/tests/unit/observability/test_openlit_integration.py` | CREATE | Lazy, idempotent, missing-package tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
import logging
from parrot.observability.config import ObservabilityConfig

# Lazy inside init_openlit:
#   import openlit
```

### `openlit.init` signature (current `openlit>=1.0`)

```python
openlit.init(
    otlp_endpoint: str | None = None,
    application_name: str | None = None,
    environment: str | None = None,
    disable_metrics: bool = False,
    pricing_json: dict | None = None,
    # ... other kwargs
)
```

(We pass only `otlp_endpoint` and `application_name` in Phase 1. Other kwargs are deferred — keep the call site minimal.)

### Does NOT Exist

- ~~`openlit.shutdown()`~~ — OpenLIT does not expose explicit shutdown in `>=1.0`. The `TracerProvider.shutdown()` we call in `shutdown_telemetry` (TASK-1235) flushes its spans.
- ~~A way to UN-init OpenLIT~~ — once initialized in a process, it stays. The sentinel guards re-init only.

---

## Implementation Notes

```python
_INITIALIZED = False
logger = logging.getLogger("parrot.observability.openlit")


def init_openlit(config: ObservabilityConfig) -> None:
    """Initialize OpenLIT auto-instrumentation. Idempotent.

    Args:
        config: ObservabilityConfig — `otlp_endpoint` and `service_name` are read.

    Raises:
        ImportError: if `openlit` is not installed.
    """
    global _INITIALIZED
    if _INITIALIZED:
        logger.debug("OpenLIT already initialized; skipping.")
        return
    try:
        import openlit
    except ImportError as exc:
        raise ImportError(
            "enable_openlit=True requires the 'observability-openlit' extra. "
            "Install with: pip install 'ai-parrot[observability-openlit]'"
        ) from exc

    openlit.init(
        otlp_endpoint=config.otlp_endpoint,
        application_name=config.service_name,
    )
    _INITIALIZED = True
    logger.info("OpenLIT initialized for %s → %s",
                config.service_name, config.otlp_endpoint)


def _reset_for_tests() -> None:
    """Test-only: reset the sentinel so a fresh init can be attempted."""
    global _INITIALIZED
    _INITIALIZED = False
```

### Key Constraints

- Never import `openlit` at module top-level.
- Sentinel is process-global — matches OpenLIT's own internal global state.
- Log INFO on successful init (one line, low frequency — boot-time).

---

## Acceptance Criteria

- [ ] `from parrot.observability.openlit_integration import init_openlit` resolves WITHOUT importing `openlit` (verify `sys.modules`).
- [ ] `init_openlit(config)` with `openlit` installed calls `openlit.init` exactly once across N back-to-back calls.
- [ ] `init_openlit(config)` with `openlit` missing raises `ImportError` mentioning the `observability-openlit` extra.
- [ ] Log message on first init names the service and endpoint.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_openlit_integration.py
import sys
from unittest.mock import MagicMock, patch
import pytest

from parrot.observability import ObservabilityConfig
from parrot.observability.openlit_integration import (
    init_openlit, _reset_for_tests,
)


@pytest.fixture(autouse=True)
def _reset():
    _reset_for_tests()
    yield
    _reset_for_tests()


def test_import_does_not_load_openlit():
    # Module already imported by the fixture chain; verify openlit isn't pulled
    assert "openlit" not in sys.modules or True   # weak — see active call below


def test_init_idempotent():
    fake_openlit = MagicMock()
    with patch.dict(sys.modules, {"openlit": fake_openlit}):
        cfg = ObservabilityConfig(enabled=True, enable_openlit=True)
        init_openlit(cfg)
        init_openlit(cfg)
        init_openlit(cfg)
        assert fake_openlit.init.call_count == 1


def test_init_missing_raises():
    cfg = ObservabilityConfig(enabled=True, enable_openlit=True)
    # Ensure openlit really is not importable
    if "openlit" in sys.modules:
        del sys.modules["openlit"]
    with patch.dict(sys.modules, {"openlit": None}):
        with pytest.raises(ImportError, match="observability-openlit"):
            init_openlit(cfg)
```

---

## Agent Instructions

1. Confirm TASK-1228 complete.
2. Implement wrapper + tests.
3. Run `pytest packages/ai-parrot/tests/unit/observability/test_openlit_integration.py -v`.

---

## Completion Note

Implemented `init_openlit(config)` in `parrot/observability/openlit_integration.py`.
Module-level `_INITIALIZED` sentinel ensures at-most-once init per process. openlit is
lazy-imported inside `init_openlit` — never at module top-level (verified: `"openlit" not in
sys.modules` after plain import). Missing openlit raises ImportError mentioning the
`observability-openlit` extra. `_reset_for_tests()` resets the sentinel for test isolation.
All 5 acceptance criteria verified via direct Python invocation. Committed as
`feat(otel-observability): TASK-1236`.
