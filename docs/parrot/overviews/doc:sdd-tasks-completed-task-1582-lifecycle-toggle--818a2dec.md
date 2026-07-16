---
type: Wiki Overview
title: 'TASK-1582: lifecycle toggle integration'
id: doc:sdd-tasks-completed-task-1582-lifecycle-toggle-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements Module 6 of FEAT-241 in **this repo** (`packages/parrot-formdesigner`).
---

# TASK-1582: lifecycle toggle integration

**Feature**: FEAT-241 — FormDesigner Public Forms
**Spec**: `sdd/specs/formdesigner-public-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1577, TASK-1580, TASK-1581
**Assigned-to**: unassigned

---

## Context

This task implements Module 6 of FEAT-241 in **this repo** (`packages/parrot-formdesigner`).

When a form's `is_public` transitions:
- `False → True`: its public URL patterns must be registered in navigator-auth's exclude list.
- `True → False` (or delete of a public form): its patterns must be unregistered.

The spec centralizes this toggle in `FormRegistry.register` and `FormRegistry.unregister`
to avoid 4-way duplication across `create_form` / `update_form` / `patch_form` / `publish_form`
/ `delete_form`. The registry needs a reference to the aiohttp `app` to access `app["auth"]`.

The toggle must degrade gracefully (no exception) when `app["auth"]` is absent
(formdesigner running without navigator-auth mounted).

---

## Scope

1. **Add `app` reference to `FormRegistry`**: store a weak reference to the aiohttp app
   (passed during `setup_form_api`); add a `set_app(app)` method, or accept it in `__init__`.
   Actually, the cleanest approach is to use an on_register/on_unregister **callback** — the
   FormRegistry already has `_on_unregister: list[...]` (line 208). We'll wire the toggle
   via callbacks set by `setup_form_api` so FormRegistry stays transport-agnostic.

2. **In `setup_form_api`** (`api/routes.py`): after mounting routes, if `app.get("auth")` is
   set, register `_on_register_callback` and `_on_unregister_callback` on the registry that
   call `app["auth"].register_exclusions` / `unregister_exclusions` with the public paths.
   If `app["auth"]` is absent, skip (no-op).

3. **In `FormRegistry.register`**: after storing the form in `_forms`, diff old vs new
   `is_public`. Fire `on_register` callbacks (already plumbed for other uses per spec) OR
   add new toggle-specific callbacks.

   Actually, reviewing the existing code: `_on_unregister` callbacks exist (line 208) for
   unregister events. We need similar callbacks for register events that carry BOTH the old
   and new form so we can diff `is_public`. The cleanest approach that avoids modifying
   FormRegistry's internal logic heavily:

   **Chosen approach**: add `_on_public_toggle: list[Callable[[str, bool, bool, str], Awaitable[None]]]`
   to FormRegistry. On `register`, compare `old_form.is_public vs new_form.is_public` and
   invoke callbacks with `(form_id, old_is_public, new_is_public, base_path)`. `setup_form_api`
   registers the callback that calls the auth handler.

   SIMPLER approach aligned with spec ("centralized in register"): FormRegistry stores an
   optional async callback `_public_toggle_callback(form_id, became_public: bool) -> None`.
   `setup_form_api` sets it. `register` calls it on transitions; `unregister` calls it with
   `became_public=False` when the form was public.

4. **Write unit tests** in `tests/unit/services/test_registry_public_toggle.py`.

**NOT in scope**: exclude-provider for restart re-hydration (M7/TASK-1583); navigator-auth
changes (those are TASK-1577/1578/1579 which must be done first).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py` | MODIFY | Add `_public_toggle_callback` + `set_public_toggle_callback()`; invoke on `is_public` transitions in `register` and `unregister` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | After route mounting, wire `_public_toggle_callback` if `app["auth"]` is present |
| `packages/parrot-formdesigner/tests/unit/services/test_registry_public_toggle.py` | CREATE | Unit tests for the toggle |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py (existing)
import logging
import asyncio
from typing import Any, Callable, Awaitable
from parrot_formdesigner.core.schema import FormSchema  # verified: schema.py:267

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py (existing)
from parrot_formdesigner.services.registry import FormRegistry   # verified: routes.py
from parrot_formdesigner.services.public_forms import public_form_paths  # NEW — from TASK-1581

# navigator_auth — already a hard dep (routes.py:34):
from navigator_auth.decorators import is_authenticated, user_session  # verified: routes.py:34
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py

class FormRegistry:  # line 146
    def __init__(
        self,
        storage=None,
        ...
    ) -> None:  # line 177 — extend with _public_toggle_callback init
        self._on_unregister: list[Callable[[str, str], Awaitable[None]]] = []  # line 208

    async def register(
        self,
        form: FormSchema,
        *,
        persist: bool = False,
        overwrite: bool = True,
        tenant: str | None = None,
    ) -> None:  # line 262
        # Inside: calls self._storage.save() at line 338-340 when persist=True
        # After storing, check old_is_public vs new form.is_public

    async def unregister(self, form_id: str, *, tenant: str | None = None) -> bool:  # line 430
        # Fires _on_unregister callbacks at line 455-460

    async def get(self, form_id: str, *, tenant: str | None = None) -> FormSchema | None:  # line 575

    @property
    def has_storage(self) -> bool:  # line 833

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py

def setup_form_api(
    app,
    registry,
    *,
    base_path: str = "/api/v1",
    ...
) -> None:  # line 92
    # ... route mounting ...
    # app["form_registry"] = registry  # line 160
    # app["auth"] key: if present, contains AuthHandler (registered by navigator-auth)

def _wrap_auth(handler):  # line 67
```

### Does NOT Exist
- ~~`FormRegistry._public_toggle_callback`~~ — **to be created by this task**
- ~~`FormRegistry.set_public_toggle_callback`~~ — **to be created by this task**
- ~~`app["auth"].register_exclusions`~~ until TASK-1577 merges in navigator-auth — guard with `hasattr`
- ~~`FormSchema.is_public`~~ until TASK-1580 completes — TASK-1580 is a dependency
- ~~`public_form_paths` in registry.py~~ — import from services.public_forms (TASK-1581)

---

## Implementation Notes

### Chosen Design: single async toggle callback

This keeps FormRegistry transport-agnostic. `setup_form_api` owns the auth wiring.

```python
# In FormRegistry.__init__ (add after _on_unregister line 208):
self._public_toggle_callback: (
    Callable[[str, bool], Awaitable[None]] | None
) = None

# New method on FormRegistry:
def set_public_toggle_callback(
    self,
    callback: Callable[[str, bool], Awaitable[None]],
) -> None:
    """Register a callback invoked when a form's is_public flag changes.

    Args:
        callback: Async callable (form_id: str, is_public: bool) -> None.
                  Called with is_public=True when the form becomes public;
                  is_public=False when it becomes private or is deleted.
    """
    self._public_toggle_callback = callback
```

### In `FormRegistry.register` (after storing the form to _forms):

```python
# After: self._forms[resolved][form.form_id] = form  (find the exact line)
if self._public_toggle_callback is not None:
    old_form = ...  # retrieve before overwriting (call self.get() BEFORE storing, or track old value)
    old_is_public = old_form.is_public if old_form is not None else False
    if old_is_public != form.is_public:
        try:
            await self._public_toggle_callback(form.form_id, form.is_public)
        except Exception as exc:
            self.logger.warning("public_toggle_callback failed: %s", exc)
```

**IMPORTANT**: The old form must be fetched BEFORE the new form overwrites it in `_forms`.
Look at the register body to find where `_forms[resolved][form.form_id]` is assigned and
fetch the current value immediately before.

### In `FormRegistry.unregister` (before removing from _forms):

```python
# Before removing from bucket:
if self._public_toggle_callback is not None:
    existing = bucket.get(form_id)  # the form about to be removed
    if existing is not None and existing.is_public:
        try:
            await self._public_toggle_callback(form_id, False)
        except Exception as exc:
            self.logger.warning("public_toggle_callback (unregister) failed: %s", exc)
```

### In `setup_form_api` (api/routes.py):

Add AFTER all routes are mounted (at the end of the function, after the `app.router.add_*` calls):

```python
# Wire is_public toggle → auth exclude list (FEAT-241)
auth = app.get("auth")
if auth is not None and hasattr(auth, "register_exclusions"):
    _bp = base_path.rstrip("/")
    async def _public_toggle(form_id: str, is_public: bool) -> None:
        paths = public_form_paths(form_id, base_path=_bp)
        if is_public:
            auth.register_exclusions(paths)
        else:
            auth.unregister_exclusions(paths)
    registry.set_public_toggle_callback(_public_toggle)
```

### Key Constraints
- The toggle callback must be a **no-op** when `app["auth"]` is absent — guard with `app.get("auth")`.
- Callback failures in `register`/`unregister` must be caught + logged at WARNING, NOT raised.
- Fetch the old form BEFORE overwriting in `register` to get the correct diff.
- Use `hasattr(auth, "register_exclusions")` to guard against old navigator-auth versions.
- Import `public_form_paths` from `parrot_formdesigner.services.public_forms`.

---

## Acceptance Criteria

- [ ] `False → True` transition calls `auth.register_exclusions(public_form_paths(form_id, base_path))`.
- [ ] `True → False` transition calls `auth.unregister_exclusions(public_form_paths(form_id, base_path))`.
- [ ] No change in `is_public` (`False → False`, `True → True`) does NOT invoke the callback.
- [ ] Deleting a public form (`unregister` when `is_public=True`) calls `_toggle_callback(form_id, False)`.
- [ ] Deleting a private form does NOT invoke the callback.
- [ ] When `app["auth"]` is absent, no exception is raised.
- [ ] When `_public_toggle_callback` is `None`, no exception in register/unregister.
- [ ] All new tests pass: `pytest packages/parrot-formdesigner/tests/unit/services/test_registry_public_toggle.py -v`.
- [ ] Existing tests pass: `pytest packages/parrot-formdesigner/tests/ -x -q`.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` passes.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/services/test_registry_public_toggle.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.core.schema import FormSchema


@pytest.fixture
def registry():
    return FormRegistry(require_tenant=False)


@pytest.fixture
def public_form():
    return FormSchema(form_id="contact", title="Contact", sections=[], is_public=True)


@pytest.fixture
def private_form():
    return FormSchema(form_id="contact", title="Contact", sections=[], is_public=False)


@pytest.mark.asyncio
class TestPublicToggleOnRegister:
    async def test_false_to_true_invokes_callback(self, registry, public_form):
        callback = AsyncMock()
        registry.set_public_toggle_callback(callback)
        await registry.register(public_form)
        callback.assert_awaited_once_with("contact", True)

    async def test_true_to_false_invokes_callback(self, registry, public_form, private_form):
        callback = AsyncMock()
        registry.set_public_toggle_callback(callback)
        await registry.register(public_form)
        callback.reset_mock()
        await registry.register(private_form)
        callback.assert_awaited_once_with("contact", False)

    async def test_no_change_no_callback(self, registry, public_form):
        callback = AsyncMock()
        registry.set_public_toggle_callback(callback)
        await registry.register(public_form)
        callback.reset_mock()
        await registry.register(public_form)  # same is_public=True
        callback.assert_not_awaited()

    async def test_no_callback_no_error(self, registry, public_form):
        """No callback set: register must not raise."""
        await registry.register(public_form)


@pytest.mark.asyncio
class TestPublicToggleOnUnregister:
    async def test_delete_public_form_invokes_callback(self, registry, public_form):
        callback = AsyncMock()
        await registry.register(public_form)
        registry.set_public_toggle_callback(callback)
        await registry.unregister("contact")
        callback.assert_awaited_once_with("contact", False)

    async def test_delete_private_form_no_callback(self, registry, private_form):
        callback = AsyncMock()
        await registry.register(private_form)
        registry.set_public_toggle_callback(callback)
        await registry.unregister("contact")
        callback.assert_not_awaited()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** `sdd/specs/formdesigner-public-forms.spec.md` §3 M6.
2. **Check dependencies**: TASK-1577 (navigator-auth bulk API), TASK-1580 (is_public field), TASK-1581 (public_form_paths) — all must be done.
3. **Verify Codebase Contract**:
   - Read `registry.py` lines 177-215 (`__init__` body) to find exact attribute setup.
   - Read `register` body (lines 262-370) to find WHERE `_forms[resolved][form.form_id]` is assigned.
   - Read `unregister` body (lines 430-462) to find where `bucket.pop(form_id)` is.
   - Read `routes.py` end of `setup_form_api` (lines 200-280) to find the last `app.router.add_*` call.
4. **Implement** `_public_toggle_callback`, `set_public_toggle_callback`, toggle invocations in `register`/`unregister`, and wiring in `setup_form_api`.
5. **Run tests**: `source .venv/bin/activate && pytest packages/parrot-formdesigner/tests/unit/services/test_registry_public_toggle.py -v`.
6. **Run regression tests**: `pytest packages/parrot-formdesigner/tests/ -x -q`.
7. **Commit** in the feature worktree.

---

## Completion Note

*(Agent fills this in when done)*

<<<<<<< HEAD
**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
=======
**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-16
**Notes**: Implemented `_public_toggle_callback` and `set_public_toggle_callback()` in FormRegistry; diff old vs new `is_public` in `register()`, invoke callback on transitions (False→True: register, True→False: unregister); unregister on `delete()` if form was public. Wired callback in `setup_form_api`. All tests pass.

**Deviations from spec**: none
>>>>>>> feat-241-formdesigner-public-forms
