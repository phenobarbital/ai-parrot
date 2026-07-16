---
type: Wiki Overview
title: 'TASK-1246: Lifecycle Unit Tests'
id: doc:sdd-tasks-completed-task-1246-lifecycle-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task adds unit tests verifying the new aiohttp lifecycle integration
  in
relates_to:
- concept: mod:parrot.forms
  rel: mentions
- concept: mod:parrot.forms.registry
  rel: mentions
- concept: mod:parrot.forms.storage
  rel: mentions
---

# TASK-1246: Lifecycle Unit Tests

**Feature**: FEAT-185 — Refactor FormRegistry
**Spec**: `sdd/specs/refactor-formregistry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1242, TASK-1243, TASK-1244, TASK-1245
**Assigned-to**: unassigned

---

## Context

This task adds unit tests verifying the new aiohttp lifecycle integration in
`FormRegistry`, the self-managed pool in `PostgresFormStorage`, and backward
compatibility of both packages. Also verifies the existing tests still pass.

Implements spec §3 Module 7 and §4 Test Specification.

---

## Scope

- Create tests for the **parrot-formdesigner** package:
  - `FormStorage.close()` default no-op
  - `FormRegistry.__init__` with and without `app`
  - Signal registration (`on_startup`/`on_shutdown` in `app.on_startup`/`app.on_shutdown`)
  - `on_startup` calls `storage.initialize()` and `load_from_storage()`
  - `on_shutdown` calls `storage.close()`
  - `PostgresFormStorage` construction without pool
  - `PostgresFormStorage` construction with external pool
  - `PostgresFormStorage.initialize()` creates pool
  - `PostgresFormStorage.close()` for self-owned vs external pool
  - `close()` idempotency

- Create tests for the **core** (`parrot.forms`) package:
  - Same lifecycle tests as above, adapted to the simpler core signatures

- Verify the `setup_form_api` guard: `app['form_registry']` not overwritten
  if already set

- Run all existing form tests to confirm no regressions

**NOT in scope**: Implementation code changes (those are in TASK-1242–1245).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/unit/test_registry_lifecycle.py` | CREATE | Lifecycle tests for FormRegistry + FormStorage |
| `packages/parrot-formdesigner/tests/unit/test_storage_pool.py` | CREATE | Pool management tests for PostgresFormStorage |
| `packages/ai-parrot/tests/unit/forms/test_registry_lifecycle.py` | CREATE | Core package lifecycle tests |
| `packages/parrot-formdesigner/tests/unit/api/test_setup_form_api_guard.py` | CREATE | Guard test for setup_form_api |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# parrot-formdesigner tests
from parrot_formdesigner.services.registry import FormRegistry, FormStorage  # verified
from parrot_formdesigner.services.storage import PostgresFormStorage         # verified
from aiohttp.web import Application                                          # standard aiohttp

# Core tests
from parrot.forms.registry import FormRegistry, FormStorage                  # verified
from parrot.forms.storage import PostgresFormStorage                         # verified

# Test utilities
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
```

### Existing Test Patterns

```python
# Reference: packages/parrot-formdesigner/tests/unit/test_services.py
# Uses pytest-asyncio, direct instantiation, mock storage

# Reference: packages/parrot-formdesigner/tests/unit/test_clone_form.py
# Pattern: create FormRegistry(), register forms, test methods

# Reference: packages/ai-parrot/tests/unit/forms/test_registry.py
# Pattern: core package FormRegistry tests
```

### Does NOT Exist

- ~~`test_registry_lifecycle.py`~~ — does not exist; you are creating it
- ~~`test_storage_pool.py`~~ — does not exist; you are creating it
- ~~`pytest.fixture` for aiohttp app in existing form tests~~ — not present; create your own

---

## Implementation Notes

### Pattern to Follow

Use `AsyncMock` for the storage backend. For `aiohttp.web.Application`, use
a real instance (it's lightweight and doesn't need a running server).

```python
@pytest.fixture
def mock_storage():
    storage = AsyncMock(spec=FormStorage)
    storage.initialize = AsyncMock()
    storage.close = AsyncMock()
    storage.list_forms = AsyncMock(return_value=[])
    return storage

@pytest.fixture
def app():
    return Application()
```

For `PostgresFormStorage` pool creation tests, mock `asyncpg.create_pool`:

```python
@pytest.fixture
def mock_create_pool():
    with patch("parrot_formdesigner.services.storage.asyncpg") as mock_asyncpg:
        mock_pool = AsyncMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
        yield mock_asyncpg, mock_pool
```

### Key Constraints

- Tests must work without a real PostgreSQL database.
- Use `pytest.mark.asyncio` for all async tests.
- Verify `on_startup` and `on_shutdown` by calling them directly (no need
  to start a full aiohttp server).

---

## Acceptance Criteria

- [ ] `test_registry_lifecycle.py` covers: no-app compat, app registration, signal hooks, on_startup, on_shutdown
- [ ] `test_storage_pool.py` covers: no-pool construction, external pool, initialize creates pool, close owns/doesn't-own, idempotent close
- [ ] Core `test_registry_lifecycle.py` covers the same patterns for the core package
- [ ] `test_setup_form_api_guard.py` verifies the `app['form_registry']` guard
- [ ] All new tests pass: `pytest packages/parrot-formdesigner/tests/unit/ -v`
- [ ] All new tests pass: `pytest packages/ai-parrot/tests/unit/forms/ -v`
- [ ] All existing form tests still pass (no regressions)

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_registry_lifecycle.py
import pytest
from unittest.mock import AsyncMock
from aiohttp.web import Application
from parrot_formdesigner.services.registry import FormRegistry, FormStorage


@pytest.fixture
def mock_storage():
    s = AsyncMock(spec=FormStorage)
    s.initialize = AsyncMock()
    s.close = AsyncMock()
    s.list_forms = AsyncMock(return_value=[])
    return s


@pytest.fixture
def app():
    return Application()


class TestFormRegistryLifecycle:
    async def test_no_app_backward_compat(self):
        registry = FormRegistry()
        assert len(registry) == 0

    async def test_app_registers_self(self, app, mock_storage):
        registry = FormRegistry(app=app, storage=mock_storage)
        assert app['form_registry'] is registry

    async def test_signals_registered(self, app, mock_storage):
        registry = FormRegistry(app=app, storage=mock_storage)
        assert registry.on_startup in app.on_startup
        assert registry.on_shutdown in app.on_shutdown

    async def test_on_startup_calls_initialize(self, app, mock_storage):
        registry = FormRegistry(app=app, storage=mock_storage)
        await registry.on_startup(app)
        mock_storage.initialize.assert_awaited_once()

    async def test_on_shutdown_calls_close(self, app, mock_storage):
        registry = FormRegistry(app=app, storage=mock_storage)
        await registry.on_shutdown(app)
        mock_storage.close.assert_awaited_once()


class TestFormStorageClose:
    async def test_default_close_noop(self):
        """A concrete subclass with close() inherited should not raise."""
        class DummyStorage(FormStorage):
            async def save(self, form, style=None, *, tenant=None): return ""
            async def load(self, form_id, version=None, *, tenant=None): return None
            async def delete(self, form_id, *, tenant=None): return False
            async def list_forms(self, *, tenant=None): return []

        storage = DummyStorage()
        await storage.close()  # should not raise
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — verify TASK-1242 through TASK-1245 are complete
2. **Read** the completed task files to understand what was implemented
3. **Write** the test files following the specification above
4. **Run** `pytest` on the new test files to verify they pass
5. **Run** existing form tests to verify no regressions
6. **Move this file** to `sdd/tasks/completed/TASK-1246-lifecycle-tests.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: SDD Worker (claude-sonnet-4-6)
**Date**: 2026-05-19
**Notes**: Created 4 test files with 44 total tests. All tests pass. Used `sys.modules` patching for lazy `import asyncpg` inside `initialize()`. Fixed AsyncMock context manager setup for pool.acquire(). asyncio_mode="auto" in pyproject.toml so no explicit @pytest.mark.asyncio needed.

**Deviations from spec**: none
