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
| `packages/ai-parrot/tests/observability/test_integrations_removed.py` | CREATE | Verification tests |

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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
