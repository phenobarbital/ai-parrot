# TASK-2476: Delete Monkey-Patching Integrations & Dependency Cleanup

**Feature**: FEAT-462 — Unified Telemetry Bus
**Spec**: `sdd/specs/unified-telemetry-bus.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2474, TASK-2475
**Assigned-to**: unassigned

---

## Context

With `setup_telemetry()` (TASK-2474) and `bootstrap.py` (TASK-2475) no longer
referencing the OpenLIT or Traceloop integration modules, this task deletes
those files, cleans up `__init__.py` exports, and removes the `openlit` /
`traceloop-sdk` dependencies and `conflicting-groups` entries from the
workspace `pyproject.toml`.

Consolidates spec §3 Module 7 (Delete Integrations) and Module 8 (Dependency Cleanup)
into a single task since they are tightly coupled and both small.

---

## Scope

- DELETE `packages/ai-parrot/src/parrot/observability/openlit_integration.py`
- DELETE `packages/ai-parrot/src/parrot/observability/traceloop_integration.py`
- Update `packages/ai-parrot/src/parrot/observability/__init__.py`: remove `init_traceloop`, `setup_traceloop`, `shutdown_traceloop` from `__all__` and imports
- Remove `init_openlit` from any internal references (only used in `setup.py` — should already be gone from TASK-2474)
- Change `observability-openlit` extra in `packages/ai-parrot/pyproject.toml` to point to `ai-parrot-openlit-bridge` (or empty deps list if bridge package isn't ready)
- Change `observability-traceloop` extra similarly (or remove if bridge is deferred)
- Remove all 11 openlit-related `conflicting-groups` entries from workspace `pyproject.toml`
- Write verification tests

**NOT in scope**: Creating the bridge package itself (TASK-2477).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/openlit_integration.py` | DELETE | No longer needed |
| `packages/ai-parrot/src/parrot/observability/traceloop_integration.py` | DELETE | No longer needed |
| `packages/ai-parrot/src/parrot/observability/__init__.py` | MODIFY | Remove traceloop/openlit exports |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Repurpose observability extras |
| `pyproject.toml` (workspace root) | MODIFY | Remove conflicting-groups entries |
| `packages/ai-parrot/tests/unit/observability/test_integrations_removed.py` | CREATE | Verification tests (corrected path — see TASK-2470) |
| `packages/ai-parrot/tests/unit/observability/test_openlit_integration.py` | DELETE (not originally listed) | Tested the deleted `openlit_integration` module directly — cannot import, must be removed |
| `packages/ai-parrot/tests/unit/observability/test_traceloop_integration.py` | DELETE (not originally listed) | Tested the deleted `traceloop_integration` module directly — cannot import, must be removed |
| `packages/ai-parrot/tests/unit/observability/test_bootstrap.py` | MODIFY (not originally listed) | 1 remaining test directly imported `traceloop_integration` to patch it — updated for the now-deleted module |
| `packages/ai-parrot/tests/unit/observability/conftest.py` | MODIFY (not originally listed) | Removed a dead (but now-stale) `openlit_integration._reset_for_tests()` reset call + docstring mention |
| `packages/ai-parrot/tests/integration/observability/test_perf.py` | MODIFY (not originally listed) | 1 test directly called the deleted `openlit_integration.init_openlit` — replaced with an equivalent benchmark against `OpenLitUsageRecorder` |
| `packages/ai-parrot/tests/integration/observability/test_poc.py` | MODIFY (not originally listed) | 1 test directly called the deleted `openlit_integration.init_openlit` — replaced with an equivalent scenario using `OpenLitUsageRecorder` alongside tracing |

---

## Codebase Contract (Anti-Hallucination)

### Verified References
```python
# packages/ai-parrot/src/parrot/observability/__init__.py exports (to be removed):
# Line 59: init_traceloop
# Line 60: setup_traceloop
# Line 61: shutdown_traceloop
# Lines 80-82: same names in __all__
# NOTE: init_openlit is NOT exported from __init__.py — it's only used internally in setup.py
```

### Files to Delete
```
packages/ai-parrot/src/parrot/observability/openlit_integration.py  (4.8K)
packages/ai-parrot/src/parrot/observability/traceloop_integration.py  (7.8K)
```

### Does NOT Exist (After This Task)
- ~~`parrot.observability.openlit_integration`~~ — deleted
- ~~`parrot.observability.traceloop_integration`~~ — deleted
- ~~`init_traceloop` in parrot.observability~~ — removed from exports
- ~~`setup_traceloop` in parrot.observability~~ — removed from exports
- ~~`shutdown_traceloop` in parrot.observability~~ — removed from exports
- ~~`conflicting-groups` openlit entries in workspace pyproject.toml~~ — removed

---

## Implementation Notes

### __init__.py Cleanup
```python
# Remove these lines from __init__.py:
# from parrot.observability.traceloop_integration import (
#     init_traceloop,
#     setup_traceloop,
#     shutdown_traceloop,
# )
# And remove from __all__:
# "init_traceloop", "setup_traceloop", "shutdown_traceloop"
```

### pyproject.toml (ai-parrot package)
```toml
# BEFORE:
# [project.optional-dependencies]
# observability-openlit = ["openlit>=1.40.0"]
# observability-traceloop = ["traceloop-sdk>=0.40.0,<1.0"]

# AFTER (if bridge package exists):
# observability-openlit = ["ai-parrot-openlit-bridge"]
# observability-traceloop = []  # or remove entirely

# AFTER (if bridge package not ready — TASK-2477 pending):
# observability-openlit = []    # placeholder until bridge package
# observability-traceloop = []  # deprecated, kept for backward compat
```

### Workspace pyproject.toml — conflicting-groups removal
Search for `conflicting-groups` entries that mention `openlit` and remove them.
There are 11 such entries. Example pattern:
```toml
[[tool.uv.conflicting-groups]]
# ... entries pairing openlit with openai or other packages
```

### Key Constraints
- Verify NO remaining imports of `openlit_integration` or `traceloop_integration` exist in the codebase after TASK-2474 and TASK-2475
- Run `grep -r "openlit_integration\|traceloop_integration\|init_openlit\|init_traceloop\|setup_traceloop\|shutdown_traceloop" packages/ai-parrot/src/` to confirm
- Keep the extra names (`observability-openlit`, `observability-traceloop`) in pyproject.toml for backward compat — just empty their dependency lists or point them to the bridge

---

## Acceptance Criteria

- [ ] `openlit_integration.py` and `traceloop_integration.py` are deleted
- [ ] `from parrot.observability import init_traceloop` raises `ImportError`
- [ ] `from parrot.observability import setup_traceloop` raises `ImportError`
- [ ] No references to `openlit_integration` or `traceloop_integration` remain in `packages/ai-parrot/src/`
- [ ] All 11 openlit-related `conflicting-groups` entries removed from workspace `pyproject.toml`
- [ ] `observability-openlit` and `observability-traceloop` extras still exist in `packages/ai-parrot/pyproject.toml` (with updated/empty deps)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/observability/test_integrations_removed.py -v`
- [ ] No linting errors across observability package

---

## Test Specification

```python
# packages/ai-parrot/tests/observability/test_integrations_removed.py
import pytest
import importlib
import subprocess


class TestIntegrationsDeleted:
    def test_openlit_integration_not_importable(self):
        with pytest.raises(ImportError):
            import parrot.observability.openlit_integration

    def test_traceloop_integration_not_importable(self):
        with pytest.raises(ImportError):
            import parrot.observability.traceloop_integration

    def test_no_traceloop_in_init_all(self):
        import parrot.observability as obs
        assert "init_traceloop" not in obs.__all__
        assert "setup_traceloop" not in obs.__all__
        assert "shutdown_traceloop" not in obs.__all__


class TestDependencyCleanup:
    def test_no_conflicting_groups_for_openlit(self):
        """Workspace pyproject.toml has no openlit conflicting-groups."""
        with open("pyproject.toml") as f:
            content = f.read()
        # After cleanup, "openlit" should not appear in conflicting-groups
        # (it may still appear in comments or the extras section)
        sections = content.split("[[tool.uv.conflicting-groups]]")
        for section in sections[1:]:  # skip preamble
            block = section.split("[[")[0]  # until next section
            assert "openlit" not in block.lower(), (
                f"Found openlit in conflicting-groups: {block[:100]}"
            )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/unified-telemetry-bus.spec.md` for full context
2. **Check dependencies** — verify TASK-2474 (setup) and TASK-2475 (bootstrap) are done
3. **Run grep** to confirm no remaining references: `grep -r "openlit_integration\|traceloop_integration\|init_openlit\|init_traceloop\|setup_traceloop\|shutdown_traceloop" packages/ai-parrot/src/ --include="*.py"`
4. **Update status** in `sdd/tasks/index/unified-telemetry-bus.json` → `"in-progress"`
5. **Implement** following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2476-delete-integrations-and-cleanup.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-26
**Notes**: Deleted `openlit_integration.py` and `traceloop_integration.py`.
Removed the `traceloop_integration` import and `init_traceloop`/
`setup_traceloop`/`shutdown_traceloop` from `parrot.observability.__init__`'s
imports and `__all__` (updated the docstring's public-surface section to
describe the FEAT-462 OTLP-target/recorder replacement instead). Emptied
`observability-openlit`/`observability-traceloop` in
`packages/ai-parrot/pyproject.toml` (kept the extra names for backward
compat, per the task's "not ready" placeholder pattern — TASK-2477
repurposes `observability-openlit`). Removed all 11
`observability-openlit` conflicts entries (and their 2 explanatory comment
blocks) from the workspace root `pyproject.toml`'s `tool.uv.conflicts`,
replacing them with one comment documenting the removal. Verified via
`tomllib` that both TOML files remain syntactically valid and that no
`tool.uv.conflicts` entry still references `observability-openlit`.
Verified via the specified grep that `packages/ai-parrot/src/` has zero
remaining references to the deleted modules (the only textual hits are in
`__init__.py`'s docstring explaining the removal). 9 new unit tests added
(`test_integrations_removed.py`): import-failure checks for both deleted
modules, `__all__`/`ImportError` checks for the 3 removed re-exports, a
full source-tree scan for stray references, and 3 dependency-cleanup
checks (no `observability-openlit` in `tool.uv.conflicts`, both extras
still present but SDK-free, no `openlit`/`traceloop-sdk` string anywhere
under any `pyproject.toml` in the workspace). `uv lock --dry-run` was
attempted but times out at 90s without completing even in dry-run mode —
consistent with this workspace's own documented "45GB RSS, OOM-prone"
resolution cost (see the `constraint-dependencies` comment in the root
`pyproject.toml`); TOML structural validity was instead verified via
`tomllib.load()` on both files. Full `tests/unit/observability/` +
`tests/integration/observability/` suite (184 tests) passes.

**Deviations from spec**: (1) Test file path corrected to
`tests/unit/observability/` (same correction as prior FEAT-462 tasks).
(2) Deleted 2 pre-existing test files (`test_openlit_integration.py`,
`test_traceloop_integration.py`) that directly imported the now-deleted
modules — unavoidable, direct consequence of this task's own deletion
scope. (3) Modified `test_bootstrap.py`, `conftest.py`, `test_perf.py`,
and `test_poc.py` (none originally listed) — each had at least one test
or fixture directly importing/calling the deleted modules
(`traceloop_integration.setup_traceloop`, `openlit_integration.
_reset_for_tests`/`init_openlit`); updated in place to either drop the
now-impossible assertion or exercise the FEAT-462 replacement
(`OpenLitUsageRecorder` via `UsageRecordingSubscriber`) instead, per the
note added to the task's Files to Create/Modify table. (4) Did not modify
the `override-dependencies`/`constraint-dependencies` otel-version-pinning
entries in the root `pyproject.toml`, even though their comments still
reference "openlit" as part of the rationale — those aren't
`conflicting-groups`/`conflicts` entries (out of the AC's explicit scope)
and other packages (e.g. livekit-agents) may still depend on the same otel
version floor; touching them without a full `uv lock` run to verify was
judged too risky for this task's scope.

**Post-hoc fix (after TASK-2477)**: `test_openlit_not_a_dependency_anywhere`
used a raw substring scan that false-positived on
`ai-parrot-openlit-bridge`'s own `pyproject.toml` (TASK-2477) once it
existed — its `keywords` list legitimately contains `"openlit"`. Fixed to
parse `project.dependencies`/`optional-dependencies` structurally via
`tomllib` and check for an actual dependency declaration instead of any
text mention. See commit "fix(unified-telemetry-bus): make
test_openlit_not_a_dependency_anywhere structural".
