# TASK-2475: Bootstrap Cleanup

**Feature**: FEAT-462 — Unified Telemetry Bus
**Spec**: `sdd/specs/unified-telemetry-bus.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2470, TASK-2473
**Assigned-to**: unassigned

---

## Context

Cleans up `bootstrap.py` by removing the `enable_traceloop` / `enable_openlit`
branching from `_do_bootstrap()` and `ensure_observability_bootstrapped()`.
Adds the `OpenLitUsageRecorder` path to the bootstrap flow when
`OBSERVABILITY_OPENLIT_RECORDER=true`. Removes the traceloop-specific flush
from `shutdown_observability()`.

Implements spec §3 Module 6.

---

## Scope

- Remove `enable_traceloop` branching from `_do_bootstrap()` / `ensure_observability_bootstrapped()`
- Remove `enable_openlit` branching from `_do_bootstrap()` / `ensure_observability_bootstrapped()`
- Remove traceloop-specific flush from `shutdown_observability()`
- When `OBSERVABILITY_OPENLIT_RECORDER=true`, ensure `OpenLitUsageRecorder` is in the recorder list
- The `"traceloop"` backend value maps to `"otel"` with a deprecation log (may already be handled by TASK-2470 config validator — verify and wire up if needed)
- Write unit tests

**NOT in scope**: Deleting `openlit_integration.py` / `traceloop_integration.py` (TASK-2476). Modifying `setup_telemetry()` (TASK-2474).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/bootstrap.py` | MODIFY | Remove traceloop/openlit branching, add recorder path |
| `packages/ai-parrot/tests/unit/observability/test_bootstrap_cleanup.py` | CREATE | Unit tests (corrected path — see TASK-2470) |
| `packages/ai-parrot/tests/unit/observability/test_bootstrap.py` | MODIFY (not originally listed) | 3 pre-existing tests (`test_openlit_escalates_to_otel`, `test_traceloop_backend_activates`, `test_traceloop_and_openlit_are_mutually_exclusive`) asserted the OLD branching this task explicitly removes; replaced with tests asserting the new no-op behavior. Unavoidable direct consequence of this task's own acceptance criteria — not scope creep. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.bootstrap import ensure_observability_bootstrapped  # bootstrap.py:36
from parrot.observability.config import ObservabilityConfig    # config.py:18
from parrot.observability.recorders.openlit_recorder import OpenLitUsageRecorder  # added by TASK-2473
from parrot.observability.recorders.factory import build_recorders_from_config  # factory.py:22
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/bootstrap.py:36
def ensure_observability_bootstrapped():
    """Env-driven idempotent auto-boot. Has branching for traceloop, openlit,
    and lightweight backends."""
    # Contains: if config.enable_traceloop: ... (TO BE REMOVED)
    #           if config.enable_openlit: ... (TO BE REMOVED)
    # Contains: traceloop-specific shutdown (TO BE REMOVED)
```

### Does NOT Exist
- After this task, the traceloop/openlit import branches in bootstrap.py will no longer exist
- ~~`shutdown_traceloop()`~~ — currently called from bootstrap; will be removed from this call site

---

## Implementation Notes

### What to Remove
```python
# Remove from _do_bootstrap() / ensure_observability_bootstrapped():
#   - Any `if config.enable_traceloop:` block (imports + calls to init_traceloop/setup_traceloop)
#   - Any `if config.enable_openlit:` block (imports + calls to init_openlit)
#
# Remove from shutdown_observability():
#   - Any call to shutdown_traceloop() or traceloop-specific flush
```

### What to Add
```python
# In the recorder setup path (where build_recorders_from_config is called):
# The factory (modified in TASK-2473) already handles the "openlit" backend.
# Verify that when OBSERVABILITY_OPENLIT_RECORDER=true env var is set,
# the config's usage_backend or openlit_recorder_endpoint is populated
# so the factory produces the OpenLitUsageRecorder.
```

### Key Constraints
- The `"traceloop"` → `"otel"` mapping should already be handled by the config
  validator (TASK-2470). If not, add a fallback here.
- Do NOT delete the integration files themselves — only remove references to them
  in bootstrap.py. Deletion is TASK-2476.
- Maintain the idempotent boot pattern (`_bootstrapped` flag).
- Keep `shutdown_observability()` working for the OTLP-only path.

---

## Acceptance Criteria

- [ ] `_do_bootstrap()` does NOT import or call `init_traceloop`, `setup_traceloop`, or `init_openlit`
- [ ] `shutdown_observability()` does NOT call `shutdown_traceloop()`
- [ ] `OBSERVABILITY_OPENLIT_RECORDER=true` adds `OpenLitUsageRecorder` to the recorder list
- [ ] Existing `OBSERVABILITY_ENABLED=true` + `OBSERVABILITY_BACKEND=otel` path still works unchanged
- [ ] All tests pass: `pytest packages/ai-parrot/tests/observability/test_bootstrap_cleanup.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/observability/bootstrap.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/observability/test_bootstrap_cleanup.py
import pytest
from unittest.mock import patch, MagicMock


class TestBootstrapNoTraceloop:
    def test_no_traceloop_import(self):
        """_do_bootstrap() does not import traceloop.sdk."""
        import parrot.observability.bootstrap as mod
        source = open(mod.__file__).read()
        assert "traceloop" not in source.lower() or "deprecated" in source.lower()

    def test_no_openlit_init_call(self):
        """_do_bootstrap() does not call init_openlit."""
        import parrot.observability.bootstrap as mod
        source = open(mod.__file__).read()
        assert "init_openlit" not in source


class TestBootstrapOpenLitRecorder:
    @patch.dict("os.environ", {
        "OBSERVABILITY_ENABLED": "true",
        "OBSERVABILITY_OPENLIT_RECORDER": "true",
        "OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT": "http://openlit:4318",
    })
    def test_openlit_recorder_created(self):
        """When OBSERVABILITY_OPENLIT_RECORDER=true, an OpenLitUsageRecorder is created."""
        from parrot.observability.config import ObservabilityConfig
        config = ObservabilityConfig.from_env()
        from parrot.observability.recorders.factory import build_recorders_from_config
        recorders = build_recorders_from_config(config)
        recorder_names = [r.name for r in recorders]
        assert "openlit" in recorder_names
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/unified-telemetry-bus.spec.md` for full context
2. **Check dependencies** — verify TASK-2470 (config) and TASK-2473 (recorder) are done
3. **Verify the Codebase Contract** — read `bootstrap.py` in full to find all traceloop/openlit references
4. **Update status** in `sdd/tasks/index/unified-telemetry-bus.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2475-bootstrap-cleanup.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-26
**Notes**: Removed the `enable_traceloop`/`enable_openlit` mutual-exclusivity
and backend-escalation branching from `_do_bootstrap()` (replaced with a
comment explaining the deprecated flags are now no-ops and that
`usage_backend="traceloop"` is already remapped to `"otel"` by
`ObservabilityConfig`'s `model_validator`). Removed the
`if backend == "traceloop": setup_traceloop(...)` branch entirely — dead
code, since `usage_backend` can never be `"traceloop"` after config
validation. Removed the Traceloop-specific `try/except` flush block from
`shutdown_observability()`. Did NOT modify the "otel" branch's early
return or the lightweight-path recorder wiring — `build_recorders_from_config()`
(TASK-2473) already additively includes `OpenLitUsageRecorder` whenever
`openlit_recorder_endpoint` is set, for any backend that reaches the
lightweight path, with no bootstrap.py changes needed for that AC. 7 new
unit tests added (`test_bootstrap_cleanup.py`): no-traceloop-reference
source scans, no-init_openlit scan, openlit-recorder factory + bootstrap
subscriber wiring, and an otel-backward-compat regression check. Also
updated 3 pre-existing `test_bootstrap.py` tests that asserted the removed
behavior (openlit escalation, traceloop activation, mutual exclusivity) to
assert the new no-op behavior, plus added a 4th test confirming the
`usage_backend="traceloop"` → `"otel"` config-level remap still reaches
the otel path. Full `tests/unit/observability/` suite (171 tests) passes.
`ruff check` on `bootstrap.py` shows 22 pre-existing violations (down from
25 before this change — net negative, 0 new); `test_bootstrap.py` shows 3
(down from 5 baseline — 0 new); `test_bootstrap_cleanup.py` is fully clean.

**Deviations from spec**: (1) Test file path corrected to
`tests/unit/observability/` (same correction as prior FEAT-462 tasks).
(2) Modified `test_bootstrap.py` (not originally listed) — required
because 3 of its pre-existing tests directly asserted the OLD branching
this task's own acceptance criteria mandate removing; see the note added
to the task's Files to Create/Modify table.
