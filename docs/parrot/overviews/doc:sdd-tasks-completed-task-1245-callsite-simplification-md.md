---
type: Wiki Overview
title: 'TASK-1245: Call-Site Simplification'
id: doc:sdd-tasks-completed-task-1245-callsite-simplification-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Now that `FormRegistry` self-registers into the aiohttp app and hooks into
---

# TASK-1245: Call-Site Simplification

**Feature**: FEAT-185 — Refactor FormRegistry
**Spec**: `sdd/specs/refactor-formregistry.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1242, TASK-1243
**Assigned-to**: unassigned

---

## Context

Now that `FormRegistry` self-registers into the aiohttp app and hooks into
lifecycle signals, and `PostgresFormStorage` manages its own pool, the
boilerplate in `app.py` and `setup_form_api()` can be reduced significantly.

Implements spec §3 Module 6.

---

## Scope

- **`app.py`** — Replace the current multi-step setup:
  ```python
  # BEFORE (current):
  # __init__:
  form_registry = FormRegistry()
  self.app['form_registry'] = form_registry
  setup_form_api(self.app, form_registry, ...)
  setup_form_ui(self.app, form_registry, ...)

  # on_startup:
  pool = await asyncpg.create_pool(dsn=default_dsn)
  storage = PostgresFormStorage(pool=pool, schema="navigator", ...)
  await storage.initialize()
  form_registry = app['form_registry']
  form_registry.set_storage(storage)
  app['form_pool'] = pool

  # on_shutdown:
  pool = app.get('form_pool')
  if pool: await pool.close()
  ```
  With:
  ```python
  # AFTER:
  # __init__:
  storage = PostgresFormStorage(
      dsn=default_dsn,
      schema="navigator",
      table_name="form_schemas",
      tenant=None,
  )
  form_registry = FormRegistry(app=self.app, storage=storage)
  setup_form_api(self.app, form_registry, ...)
  setup_form_ui(self.app, form_registry, ...)

  # on_startup / on_shutdown: no form-related code needed
  ```
- **Remove** the manual `app['form_pool']` stashing and pool close from
  `on_shutdown` in `app.py`.
- **Remove** the manual `app['form_registry'] = form_registry` in `app.py`
  (registry now does this in its `__init__`).
- **`setup_form_api()`** in `routes.py` — guard the `app["form_registry"]`
  assignment: only set it if not already present (since `FormRegistry.__init__`
  now sets it when `app` is provided).
- Keep the `on_startup` websockets init and other non-form code unchanged.

**NOT in scope**: Changing `setup_form_ui()`, changing test files, core
package updates (TASK-1244).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `app.py` | MODIFY | Simplify FormRegistry + PostgresFormStorage setup |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Guard `app['form_registry']` assignment |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# app.py
from parrot_formdesigner.services.registry import FormRegistry  # verified: app.py:56
from parrot_formdesigner.api import setup_form_api             # verified: app.py:54
from parrot_formdesigner.services.storage import PostgresFormStorage  # will need to import
import asyncpg  # currently imported in app.py for pool creation

# routes.py
from ..services.registry import FormRegistry  # verified: routes.py:37
```

### Existing Signatures to Use

```python
# app.py — Main class structure
class Main:                                                    # line ~50
    def __init__(self, ...):                                   # creates self.app
        # line 241: form_registry = FormRegistry()
        # line 242: self.app['form_registry'] = form_registry
        # line 246: setup_form_api(self.app, form_registry, ...)
        # line 253: setup_form_ui(self.app, form_registry, ...)

    async def on_startup(self, app):                           # line 284
        # line 289: app['websockets'] = []
        # line 290-292: pool = await asyncpg.create_pool(dsn=default_dsn)
        # line 293-298: storage = PostgresFormStorage(pool=pool, ...)
        # line 299: await storage.initialize()
        # line 300: form_registry = app['form_registry']
        # line 301: form_registry.set_storage(storage)
        # line 302: app['form_pool'] = pool

    async def on_shutdown(self, app):                          # line 304
        # line 309-311: o365 manager shutdown
        # line 313-315: pool = app.get('form_pool'); pool.close()

# routes.py
def setup_form_api(app, registry, *, ...):                     # line 84
    app["form_registry"] = registry                            # line 115
```

### Does NOT Exist

- ~~`default_dsn` as a global~~ — it IS defined somewhere in app.py; verify the variable name before using
- ~~`FormRegistry(app=..., storage=...)`~~ — will exist after TASK-1242 lands
- ~~`PostgresFormStorage(dsn=...)`~~ — will exist after TASK-1243 lands

---

## Implementation Notes

### Key Constraints

- `default_dsn` is used in `on_startup`. Find where it's defined in `app.py`
  and use the same variable in the `__init__` block.
- Keep the `on_startup` method — it still has `app['websockets'] = []` and
  potentially other non-form setup. Only remove the form-related pool/storage lines.
- Keep the `on_shutdown` method — remove only the form-pool close block.
  The O365 auth manager shutdown must stay.
- `setup_form_api` should use `app.setdefault("form_registry", registry)` or
  check `if "form_registry" not in app` before assigning.

---

## Acceptance Criteria

- [ ] `app.py` constructs `PostgresFormStorage` without a pool in `__init__`
- [ ] `app.py` constructs `FormRegistry(app=self.app, storage=storage)`
- [ ] `app.py.__init__` no longer manually sets `app['form_registry']`
- [ ] `app.py.on_startup` no longer creates asyncpg pool or PostgresFormStorage
- [ ] `app.py.on_shutdown` no longer manually closes `form_pool`
- [ ] `app['form_pool']` is no longer stashed (pool is owned by storage)
- [ ] `setup_form_api()` guards the `app['form_registry']` assignment
- [ ] Application still starts and serves forms correctly

---

## Test Specification

```python
# Integration test — verify the simplified app bootstraps correctly.
# Manual verification: start the app and hit GET /api/v1/forms.
# Unit test for the guard in setup_form_api:

def test_setup_form_api_skips_registry_if_present():
    from aiohttp.web import Application
    from parrot_formdesigner.api.routes import setup_form_api
    from parrot_formdesigner.services.registry import FormRegistry

    app = Application()
    registry = FormRegistry()
    app['form_registry'] = registry  # pre-set

    setup_form_api(app, registry)
    assert app['form_registry'] is registry  # not overwritten
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/refactor-formregistry.spec.md`
2. **Check dependencies** — verify TASK-1242 and TASK-1243 are complete
3. **Find** where `default_dsn` is defined in `app.py` (search for it)
4. **Simplify** the setup following the scope above
5. **Verify** the app still imports and initializes correctly
6. **Move this file** to `sdd/tasks/completed/TASK-1245-callsite-simplification.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: SDD Worker (claude-sonnet-4-6)
**Date**: 2026-05-19
**Notes**: Simplified app.py to use `PostgresFormStorage(dsn=default_dsn, ...)` and `FormRegistry(app=self.app, storage=storage)`. Removed manual `app['form_registry']` assignment, pool creation/init in on_startup, and pool close in on_shutdown. Removed now-unused `import asyncpg`. Updated `setup_form_api()` in routes.py with `if "form_registry" not in app` guard.

**Deviations from spec**: none
