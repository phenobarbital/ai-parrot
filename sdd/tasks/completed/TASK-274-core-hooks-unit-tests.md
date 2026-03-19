# TASK-274: Core Hooks & Events Unit Tests

**Feature**: Shared Hooks Infrastructure (FEAT-040)
**Spec**: `sdd/specs/integrations-hooks.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-269, TASK-270, TASK-272, TASK-273
**Assigned-to**: claude-session

---

## Context

> Comprehensive unit tests for the migrated hooks, EventBus, HookableAgent mixin,
> and HookManager EventBus integration.

---

## Scope

### Test Files to Create

| File | Action | Description |
|---|---|---|
| `tests/core/__init__.py` | CREATE | Test package init |
| `tests/core/hooks/__init__.py` | CREATE | Test package init |
| `tests/core/hooks/test_imports.py` | CREATE | Import and lazy-loading tests |
| `tests/core/hooks/test_hookable_agent.py` | CREATE | HookableAgent mixin tests |
| `tests/core/hooks/test_manager_eventbus.py` | CREATE | HookManager dual-emit tests |
| `tests/core/events/__init__.py` | CREATE | Test package init |
| `tests/core/events/test_eventbus_imports.py` | CREATE | EventBus import tests |

### Test Cases

**`test_imports.py`:**
- `test_core_hooks_import` — `from parrot.core.hooks import BaseHook, HookManager, HookEvent, HookType`
- `test_lazy_hook_import` — `from parrot.core.hooks import SchedulerHook` (lazy)
- `test_config_imports` — All config models importable
- `test_lazy_loading_no_heavy_deps` — Importing `parrot.core.hooks` does NOT load `asyncpg`, `watchdog`, etc.
- `test_all_exports` — `__all__` contains expected symbols

**`test_hookable_agent.py`:**
- `test_mixin_init` — `HookableAgent._init_hooks()` creates HookManager
- `test_attach_hook` — Returns hook_id
- `test_start_stop_hooks` — Lifecycle with AsyncMock hook
- `test_handle_hook_event` — Event dispatched to handler
- `test_mixin_with_custom_class` — Mixin works on arbitrary host class

**`test_manager_eventbus.py`:**
- `test_set_event_bus` — Method exists and sets bus
- `test_dual_emit_with_bus` — Both callback and bus receive event
- `test_callback_only_without_bus` — Only callback when no bus set
- `test_eventbus_channel_format` — Channel matches `hooks.<type>.<event>`

**`test_eventbus_imports.py`:**
- `test_eventbus_import` — `from parrot.core.events import EventBus, Event, EventPriority`

---

## Acceptance Criteria

- [ ] All import tests pass
- [ ] Lazy loading verified — no heavy deps pulled in
- [ ] HookableAgent mixin tests pass
- [ ] HookManager dual-emit tests pass
- [ ] EventBus import tests pass
- [ ] No network calls in tests
- [ ] Tests run without external services (Redis, Postgres, etc.)

---

## Agent Instructions

1. Create test directory structure
2. Implement all test files
3. Run `pytest tests/core/ -v`
4. Verify all tests pass
5. Update status → `done`, move to `sdd/tasks/completed/`

---

## Completion Note

Completed 2026-03-10.

- Created `tests/core/hooks/test_imports.py` (12 tests): verifies eager imports (`BaseHook`, `HookManager`, `HookableAgent`, configs), lazy hook class imports (`SchedulerHook`, `FileWatchdogHook`), lazy-loading isolation (no `asyncpg`/`watchdog`/`apscheduler`/`aioimaplib` pulled in by package-level import), `__all__` completeness, and backward-compat shim (`parrot.autonomous.hooks`).
- Created `tests/core/events/__init__.py` — test package init.
- Created `tests/core/events/test_eventbus_imports.py` (5 tests): verifies `EventBus`, `Event`, `EventPriority`, `EventSubscription` importable, `__all__` is exact, `Event` model accepts correct fields.
- Existing files from prior tasks already covered HookableAgent mixin (13 tests) and HookManager dual-emit (11 tests).
- All 43 tests in `tests/core/` pass. `ruff check` clean.
