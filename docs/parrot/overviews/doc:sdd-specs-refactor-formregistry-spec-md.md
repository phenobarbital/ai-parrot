---
type: Wiki Overview
title: 'Feature Specification: Refactor FormRegistry — aiohttp App-Integrated Lifecycle'
id: doc:sdd-specs-refactor-formregistry-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: has no awareness of the aiohttp application lifecycle. This forces every
relates_to:
- concept: mod:parrot.forms
  rel: mentions
- concept: mod:parrot.forms.registry
  rel: mentions
- concept: mod:parrot.forms.storage
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Refactor FormRegistry — aiohttp App-Integrated Lifecycle

**Feature ID**: FEAT-185
**Date**: 2026-05-19
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

`FormRegistry` currently accepts only an optional `FormStorage` instance and
has no awareness of the aiohttp application lifecycle. This forces every
deployment to manually:

1. Create `FormStorage` and `FormRegistry` as separate objects.
2. Wire up `app['form_registry']` by hand.
3. Call `storage.initialize()` at the right time (after the event loop is
   running, during `on_startup`).
4. Remember to close the asyncpg pool on shutdown — which today is **not
   done at all**, leaking database connections.

Similarly, `PostgresFormStorage` (in `parrot-formdesigner`) requires a
pre-created `asyncpg.Pool` to be injected at construction time, pushing
pool lifecycle management onto the caller.

The result is boilerplate-heavy, error-prone setup code scattered across
`app.py` and any other aiohttp entry point.

### Goals

- **G1**: `FormRegistry` accepts an `aiohttp.web.Application` instance and
  self-registers into `app['form_registry']`.
- **G2**: `FormRegistry.__init__` automatically registers `on_startup` and
  `on_shutdown` aiohttp signals.
- **G3**: `FormRegistry.on_startup` calls `storage.initialize()` (and
  `load_from_storage()` if desired).
- **G4**: `FormRegistry.on_shutdown` calls `storage.close()` to cleanly
  tear down resources.
- **G5**: `PostgresFormStorage` (parrot-formdesigner package) no longer
  requires an externally-created `asyncpg.Pool`; it creates its own pool
  in `initialize()` and closes it in `close()`.
- **G6**: Simplify the call site to:
  ```python
  FormRegistry(
      app=app,
      storage=PostgresFormStorage(
          schema="navigator",
          table_name="form_schemas",
          tenant=None,
      ),
  )
  ```

### Non-Goals (explicitly out of scope)

- Changing the `FormStorage` ABC interface beyond adding `close()`.
- Modifying the core `parrot.forms` backward-compatibility shim (it will
  continue to re-export from `parrot_formdesigner`).
- Adding multi-storage support (only one storage backend per registry).
- Changing the REST API routes or handler signatures.
- Touching the `parrot/forms/registry.py` core fallback (it will be updated
  to match the new signature for consistency but remains a simpler version
  without aiohttp coupling).

---

## 2. Architectural Design

### Overview

The refactoring introduces **aiohttp lifecycle integration** into
`FormRegistry` and **self-contained pool management** into
`PostgresFormStorage`.

**FormRegistry** gains an optional `app` parameter. When provided:
- It stores itself as `app['form_registry']`.
- It appends `self.on_startup` to `app.on_startup`.
- It appends `self.on_shutdown` to `app.on_shutdown`.

When `app` is not provided, `FormRegistry` works exactly as before (pure
in-memory, no lifecycle hooks) — this preserves backward compatibility for
non-aiohttp contexts (tests, CLI scripts, the `FormAgent` example).

**PostgresFormStorage** drops the mandatory `pool` parameter. Instead:
- Constructor accepts `dsn` (or individual `host`/`port`/`database`/`user`/
  `password` kwargs) **or** an existing `pool`.
- `initialize()` creates the asyncpg pool (if not already provided) and
  runs the DDL.
- A new `close()` method closes the pool (only if the storage owns it).

**FormStorage ABC** gains a default-no-op `close()` method so that
`FormRegistry.on_shutdown` can call it unconditionally.

### Component Diagram

```
aiohttp.web.Application
  │
  ├─ on_startup ──→ FormRegistry.on_startup()
  │                    └─ storage.initialize()
  │                    └─ self.load_from_storage()  (optional)
  │
  ├─ on_shutdown ─→ FormRegistry.on_shutdown()
  │                    └─ storage.close()
  │
  └─ app['form_registry'] = FormRegistry
       │
       └─ _storage: PostgresFormStorage
            ├─ initialize() → asyncpg.create_pool() + CREATE TABLE
            └─ close()      → pool.close()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `aiohttp.web.Application` | uses | `on_startup` / `on_shutdown` signals |
| `FormStorage` (ABC) | extends | Add default `close()` method |
| `PostgresFormStorage` | modifies | Self-managed pool lifecycle |
| `setup_form_api()` | simplifies | No longer needs to stash `app['form_registry']` — registry does it |
| `setup_form_ui()` | no change | Still receives `registry` parameter |
| `app.py` (`Main`) | simplifies | Reduced boilerplate |

### Data Models

No new data models. Existing `FormSchema`, `StyleSchema` unchanged.

### New Public Interfaces

```python
# Updated FormRegistry.__init__ signature
class FormRegistry:
    def __init__(
        self,
        app: web.Application | None = None,
        storage: FormStorage | None = None,
    ) -> None: ...

    async def on_startup(self, app: web.Application) -> None: ...
    async def on_shutdown(self, app: web.Application) -> None: ...

# Updated FormStorage ABC
class FormStorage(ABC):
    async def close(self) -> None:
        """Release resources. Default no-op."""

# Updated PostgresFormStorage.__init__ (parrot-formdesigner)
class PostgresFormStorage(FormStorage):
    def __init__(
        self,
        *,
        pool: Any | None = None,
        dsn: str | None = None,
        schema: str = "navigator",
        table_name: str = "form_schemas",
        tenant: str | None = None,
        min_size: int = 2,
        max_size: int = 10,
        **pool_kwargs: Any,
    ) -> None: ...

    async def initialize(self, *, tenant: str | None = None) -> None: ...
    async def close(self) -> None: ...
```

---

## 3. Module Breakdown

### Module 1: FormStorage ABC — add `close()`

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py`
- **Responsibility**: Add `async def close(self) -> None` with a default no-op
  implementation to the `FormStorage` ABC.
- **Depends on**: none

### Module 2: PostgresFormStorage — self-managed pool

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py`
- **Responsibility**: Refactor `__init__` to accept optional `pool` OR
  connection parameters (`dsn`, `host`, etc.). Create pool in `initialize()`.
  Add `close()` to teardown the pool.
- **Depends on**: Module 1

### Module 3: FormRegistry — aiohttp lifecycle integration

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py`
- **Responsibility**: Add `app` parameter to `__init__`, register signals,
  implement `on_startup` / `on_shutdown`.
- **Depends on**: Module 1

### Module 4: Core package mirror update

- **Path**: `packages/ai-parrot/src/parrot/forms/registry.py`
- **Responsibility**: Update the core fallback `FormStorage` and `FormRegistry`
  to match the new signatures (add `close()` to `FormStorage`, add `app`
  parameter to `FormRegistry`).
- **Depends on**: Module 3

### Module 5: Core package storage mirror update

- **Path**: `packages/ai-parrot/src/parrot/forms/storage.py`
- **Responsibility**: Update the core fallback `PostgresFormStorage` to match
  the new constructor signature and add `close()`.
- **Depends on**: Module 2

### Module 6: Call-site simplification

- **Path**: `app.py`, `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
- **Responsibility**: Update `app.py` to use the new simplified instantiation.
  Remove the manual `app['form_registry'] = ...` line since `FormRegistry`
  now does it. Update `setup_form_api` to not redundantly stash the registry
  if it's already in `app`.
- **Depends on**: Module 3, Module 5

### Module 7: Tests

- **Path**: `packages/parrot-formdesigner/tests/unit/test_services.py`,
  `packages/ai-parrot/tests/unit/forms/test_registry.py`, new test files as needed
- **Responsibility**: Unit tests for the new lifecycle behavior, pool creation,
  close(), signal registration, backward compatibility (no `app`).
- **Depends on**: Module 2, Module 3, Module 4, Module 5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_registry_init_no_app` | Module 3 | `FormRegistry(storage=...)` still works without `app` |
| `test_registry_init_with_app` | Module 3 | `FormRegistry(app=app, storage=...)` registers itself in `app['form_registry']` |
| `test_registry_signals_registered` | Module 3 | `app.on_startup` and `app.on_shutdown` contain registry callbacks |
| `test_registry_on_startup_calls_initialize` | Module 3 | `on_startup` calls `storage.initialize()` |
| `test_registry_on_shutdown_calls_close` | Module 3 | `on_shutdown` calls `storage.close()` |
| `test_storage_close_default_noop` | Module 1 | `FormStorage.close()` does nothing by default |
| `test_postgres_storage_no_pool` | Module 2 | `PostgresFormStorage(schema=..., table_name=...)` constructs without pool |
| `test_postgres_storage_with_pool` | Module 2 | Passing `pool=...` uses the provided pool |
| `test_postgres_storage_initialize_creates_pool` | Module 2 | `initialize()` creates pool when none provided |
| `test_postgres_storage_close` | Module 2 | `close()` closes the pool |
| `test_postgres_storage_close_external_pool` | Module 2 | `close()` does NOT close an externally-provided pool |
| `test_backward_compat_no_app` | Module 6 | Existing code using `FormRegistry()` without app still works |

### Integration Tests

| Test | Description |
|---|---|
| `test_aiohttp_lifecycle_e2e` | Create app, add registry, simulate startup/shutdown signals, verify pool created and closed |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_app():
    """Create a minimal aiohttp application for testing."""
    from aiohttp.web import Application
    return Application()

@pytest.fixture
def mock_storage():
    """Create a mock FormStorage with spied initialize/close."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `FormRegistry(app=app, storage=storage)` registers itself as `app['form_registry']`
- [ ] `FormRegistry` registers `on_startup` and `on_shutdown` aiohttp signals automatically
- [ ] `FormRegistry.on_startup` calls `storage.initialize()`
- [ ] `FormRegistry.on_shutdown` calls `storage.close()`
- [ ] `FormStorage` ABC has a default no-op `async def close()`
- [ ] `PostgresFormStorage` can be constructed without a `pool` parameter
- [ ] `PostgresFormStorage.initialize()` creates an asyncpg pool when no pool was provided
- [ ] `PostgresFormStorage.close()` closes the asyncpg pool (only if self-owned)
- [ ] `FormRegistry()` without `app` still works (backward compatibility)
- [ ] `app.py` call site simplified — no manual `app['form_registry']` assignment
- [ ] All existing tests pass (`pytest tests/ -v`)
- [ ] New unit tests cover all lifecycle paths
- [ ] No breaking changes to existing public API

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# parrot-formdesigner package
from parrot_formdesigner.services.registry import FormRegistry, FormStorage  # verified: services/registry.py:122,35
from parrot_formdesigner.services.storage import PostgresFormStorage  # verified: services/storage.py:55
from parrot_formdesigner.services._identifiers import validate_identifier, qualified_table  # verified: services/_identifiers.py:23,43
from parrot_formdesigner.core.schema import FormSchema  # verified via services/registry.py:23
from parrot_formdesigner.core.style import StyleSchema  # verified via services/registry.py:24
from parrot_formdesigner.services.validators import FormValidator  # verified via services/registry.py:25

# Core package
from parrot.forms.registry import FormRegistry, FormStorage  # verified: forms/registry.py:94,29
from parrot.forms.storage import PostgresFormStorage  # verified: forms/storage.py:39

# aiohttp
from aiohttp import web  # used in routes.py, handlers.py

# asyncpg
import asyncpg  # used as TYPE_CHECKING import in core storage.py:33
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormStorage(ABC):                                    # line 35
    async def save(self, form, style=None, *, tenant=None) -> str:  # line 44
    async def load(self, form_id, version=None, *, tenant=None) -> FormSchema | None:  # line 66
    async def delete(self, form_id, *, tenant=None) -> bool:  # line 88
    async def list_forms(self, *, tenant=None) -> list[dict[str, Any]]:  # line 101
    # NOTE: close() does NOT exist yet — this spec adds it

class FormRegistry:                                        # line 122
    def __init__(self, storage: FormStorage | None = None) -> None:  # line 139
    _forms: dict[str, FormSchema]                          # line 145
    _lock: asyncio.Lock                                    # line 146
    _storage: FormStorage | None                           # line 147
    logger: logging.Logger                                 # line 150
    async def register(self, form, *, persist=False, overwrite=True) -> None:  # line 152
    async def get(self, form_id: str) -> FormSchema | None:  # line 220
    async def list_forms(self) -> list[FormSchema]:        # line 232
    async def load_from_storage(self, *, tenant=None) -> int:  # line 318
    @property has_storage -> bool:                         # line 357
    @property storage -> FormStorage | None:               # line 369
    async def clone_form(self, source_form_id, new_form_id, patch=None, *, persist=True, tenant=None) -> FormSchema:  # line 415

# packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py
class PostgresFormStorage(FormStorage):                    # line 55
    def __init__(self, pool, *, schema="navigator", table_name="form_schemas", tenant=None) -> None:  # line 74
    _pool: Any                                             # line 87
    _schema: str                                           # line 88
    _table: str                                            # line 89
    _tenant: str | None                                    # line 90
    async def initialize(self, *, tenant=None) -> None:    # line 185
    async def save(self, form, style=None, *, created_by=None, tenant=None) -> str:  # line 204
    async def load(self, form_id, version=None, *, tenant=None) -> FormSchema | None:  # line 249
    async def delete(self, form_id, *, tenant=None) -> bool:  # line 304
    async def list_forms(self, *, tenant=None) -> list[dict[str, Any]]:  # line 329

# packages/ai-parrot/src/parrot/forms/registry.py (core fallback)
class FormStorage(ABC):                                    # line 29
    async def save(self, form, style=None) -> str:         # line 39
    async def load(self, form_id, version=None) -> FormSchema | None:  # line 55
    async def delete(self, form_id) -> bool:               # line 73
    async def list_forms(self) -> list[dict[str, str]]:    # line 85

class FormRegistry:                                        # line 94
    def __init__(self, storage: FormStorage | None = None) -> None:  # line 111

# packages/ai-parrot/src/parrot/forms/storage.py (core fallback)
class PostgresFormStorage(FormStorage):                    # line 39
    def __init__(self, pool: Any) -> None:                 # line 106
    async def initialize(self) -> None:                    # line 115
    # NOTE: no close() method exists — uses class-level SQL constants

# app.py
class Main:                                                # line ~50
    # line ~238: form_registry = FormRegistry()
    # line ~239: self.app['form_registry'] = form_registry
    # line ~243: setup_form_api(self.app, form_registry, ...)

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def setup_form_api(app, registry, *, client=None, ...):    # line 84
    app["form_registry"] = registry                        # line 115
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FormRegistry.__init__` | `web.Application.on_startup` | `app.on_startup.append()` | aiohttp API |
| `FormRegistry.__init__` | `web.Application.on_shutdown` | `app.on_shutdown.append()` | aiohttp API |
| `FormRegistry.on_startup` | `FormStorage.initialize()` | method call | `storage.py:185` |
| `FormRegistry.on_shutdown` | `FormStorage.close()` | method call | NEW |
| `PostgresFormStorage.initialize` | `asyncpg.create_pool()` | function call | asyncpg API |
| `PostgresFormStorage.close` | `asyncpg.Pool.close()` | method call | asyncpg API |

### Does NOT Exist (Anti-Hallucination)

- ~~`FormStorage.close()`~~ — does not exist yet; this spec adds it
- ~~`FormStorage.initialize()`~~ — not on the ABC; only on `PostgresFormStorage`
- ~~`PostgresFormStorage.close()`~~ — does not exist yet; this spec adds it
- ~~`FormRegistry.on_startup`~~ — does not exist yet; this spec adds it
- ~~`FormRegistry.on_shutdown`~~ — does not exist yet; this spec adds it
- ~~`FormRegistry.app`~~ — does not exist yet; this spec adds it
- ~~`PostgresFormStorage(dsn=...)`~~ — not supported yet; this spec adds it
- ~~`asyncpg.Pool.terminate()`~~ — exists in asyncpg but prefer `pool.close()` for graceful shutdown

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use `app.on_startup.append(self.on_startup)` — the standard aiohttp pattern.
  The signal callback signature is `async def handler(app: web.Application)`.
- For `PostgresFormStorage` pool creation, use `asyncpg.create_pool()` which
  is the standard async pool factory.
- Follow the existing `_pool.acquire()` context manager pattern already used
  throughout `storage.py`.
- `close()` must be idempotent — calling it twice should not raise.

### Known Risks / Gotchas

- **Backward compatibility**: Existing code passing `FormRegistry(storage=...)` without
  `app` must continue to work. The `app` parameter is optional.
- **Externally-provided pool**: When `PostgresFormStorage` receives a `pool` kwarg,
  `close()` must NOT close it (the caller owns it). Track ownership with a
  `_owns_pool: bool` flag.
- **Signal ordering**: If `setup_form_api` also sets `app['form_registry']`, the
  registry will be set twice. This is harmless (same object) but `setup_form_api`
  should be updated to skip the assignment if already present.
- **`initialize()` with tenant**: The existing `PostgresFormStorage.initialize()`
  accepts an optional `tenant` kwarg. The new `FormRegistry.on_startup` should
  pass through the storage's default tenant if any.
- **Core package divergence**: The core `parrot/forms/storage.py` uses class-level
  SQL constants (not dynamic schema). Its `PostgresFormStorage` is simpler.
  Mirror the `close()` and constructor changes but keep the simpler SQL approach.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncpg` | `>=0.29` | Already a dependency; used for pool creation |
| `aiohttp` | `>=3.9` | Already a dependency; `web.Application` signals |

---

## 8. Open Questions

- [ ] Should `FormRegistry.on_startup` automatically call `load_from_storage()`
  after `initialize()`? — *Owner: Jesus*
  (Currently `load_from_storage()` is not called anywhere in `app.py`; adding
  it would auto-hydrate the in-memory cache on startup.)
- [ ] Should the DSN for `PostgresFormStorage` come from environment variables
  by default (e.g. `PARROT_FORM_DSN`) or always be explicit? — *Owner: Jesus*

---

## Worktree Strategy

- **Isolation unit**: per-spec (all tasks run sequentially in one worktree).
- All modules are tightly coupled (ABC change → storage → registry → call sites).
- No parallelizable tasks — strict dependency chain.
- **Cross-feature dependencies**: none. This is a self-contained refactoring
  of `FormRegistry` and `PostgresFormStorage`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-19 | Jesus Lara | Initial draft |
