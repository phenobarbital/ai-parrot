---
type: Wiki Overview
title: 'TASK-1583: exclude-provider registration (restart re-hydration)'
id: doc:sdd-tasks-completed-task-1583-exclude-provider-registration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements Module 7 of FEAT-241 in **this repo** (`packages/parrot-formdesigner`).
---

# TASK-1583: exclude-provider registration (restart re-hydration)

**Feature**: FEAT-241 — FormDesigner Public Forms
**Spec**: `sdd/specs/formdesigner-public-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1578, TASK-1581, TASK-1582
**Assigned-to**: unassigned

---

## Context

This task implements Module 7 of FEAT-241 in **this repo** (`packages/parrot-formdesigner`).

Without restart re-hydration, all runtime auth exemptions are wiped every time the
server restarts (the navigator-auth exclude list is re-seeded from defaults at boot —
`auth.py:535`). The provider pattern introduced in M2/TASK-1578 solves this:
callers register an async callable that returns paths; `auth_startup` invokes each
provider and registers the yielded paths via `register_exclusions`.

This task registers such a provider in `setup_form_api`: an async function that lists
all persisted `is_public=True` forms from `FormRegistry.list_forms` and yields their
public path patterns via `public_form_paths`.

---

## Scope

- In `setup_form_api` (api/routes.py), AFTER the auth toggle wiring added by TASK-1582,
  register an exclude-provider with `app["auth"].add_exclude_provider(...)` that:
  1. Calls `registry.list_forms()` to get all persisted public forms.
  2. Yields `public_form_paths(form.form_id, base_path)` for each form where `is_public=True`.
- Guard with `app.get("auth")` and `hasattr(auth, "add_exclude_provider")` — must be a
  no-op when navigator-auth is absent or old.
- Write unit tests: `packages/parrot-formdesigner/tests/unit/api/test_exclude_provider.py`.

**NOT in scope**: lifecycle toggle (M6/TASK-1582 — must be done first); navigator-auth
exclude-provider API (M2/TASK-1578 — must be done first in navigator-auth repo).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Register exclude-provider in `setup_form_api` after auth wiring |
| `packages/parrot-formdesigner/tests/unit/api/test_exclude_provider.py` | CREATE | Unit tests for the provider |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py (existing)
from parrot_formdesigner.services.registry import FormRegistry  # verified
from parrot_formdesigner.services.public_forms import public_form_paths  # from TASK-1581

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py (verified)
class FormRegistry:
    async def list_forms(self, *, tenant: str | None = None) -> list[FormSchema]:  # line 591
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py

def setup_form_api(
    app,
    registry: FormRegistry,
    *,
    base_path: str = "/api/v1",
    ...
) -> None:  # line 92

# navigator-auth (after TASK-1578):
# app["auth"].add_exclude_provider(async_callable)
# The provider signature: async () -> Iterable[str]

# From TASK-1582: auth wiring is already in setup_form_api at this point
```

### Does NOT Exist
- ~~`AuthHandler.add_exclude_provider`~~ until TASK-1578 merges — guard with `hasattr`
- ~~`FormRegistry.list_public_forms`~~ — does NOT exist; use `list_forms()` + filter by `is_public`
- ~~Any existing provider registration in routes.py~~ — greenfield addition

---

## Implementation Notes

### Provider Implementation

Add AFTER the auth toggle wiring from TASK-1582 (at the end of `setup_form_api`):

```python
# Register exclude-provider for restart re-hydration (FEAT-241 M7)
auth = app.get("auth")
if auth is not None and hasattr(auth, "add_exclude_provider"):
    _bp = base_path.rstrip("/")

    async def _public_forms_exclude_provider() -> list[str]:
        """Yield auth-exempt paths for all persisted is_public=True forms."""
        paths: list[str] = []
        try:
            forms = await registry.list_forms()
            for form in forms:
                if form.is_public:
                    paths.extend(public_form_paths(form.form_id, base_path=_bp))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "public_forms_exclude_provider: list_forms failed: %s", exc
            )
        return paths

    auth.add_exclude_provider(_public_forms_exclude_provider)
```

### Key Constraints
- Use `registry.list_forms()` (returns `list[FormSchema]`, line 591) NOT `list_form_ids()`.
- Filter by `form.is_public` — only public forms contribute paths.
- Provider failures must NOT raise (catch and log WARNING).
- Guard `app.get("auth")` and `hasattr(auth, "add_exclude_provider")` separately — both needed.
- The `_bp` closure must capture the stripped `base_path` (mirror the toggle wiring from TASK-1582).
- The provider is registered once; it will be called by `auth_startup` on every restart.

---

## Acceptance Criteria

- [ ] `setup_form_api` registers an exclude-provider with `app["auth"].add_exclude_provider`.
- [ ] The provider, when called, returns paths for all `is_public=True` forms from `list_forms()`.
- [ ] The provider returns an empty list when no public forms exist.
- [ ] The provider catches `list_forms()` exceptions and returns `[]` (no raise).
- [ ] When `app["auth"]` is absent, no exception and no provider is registered.
- [ ] When `app["auth"]` lacks `add_exclude_provider`, no exception (graceful degradation).
- [ ] All new tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_exclude_provider.py -v`.
- [ ] Existing tests pass: `pytest packages/parrot-formdesigner/tests/ -x -q`.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` passes.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/api/test_exclude_provider.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot_formdesigner.services.public_forms import public_form_paths


class TestExcludeProviderRegistration:
    def test_provider_registered_when_auth_present(self):
        """setup_form_api registers provider when app['auth'] has add_exclude_provider."""
        from aiohttp import web
        from parrot_formdesigner.api.routes import setup_form_api
        from parrot_formdesigner.services.registry import FormRegistry

        app = web.Application()
        auth = MagicMock()
        auth.add_exclude_provider = MagicMock()
        auth.register_exclusions = MagicMock()
        app["auth"] = auth

        registry = FormRegistry(require_tenant=False)
        setup_form_api(app, registry)

        auth.add_exclude_provider.assert_called_once()

    def test_no_error_when_auth_absent(self):
        """setup_form_api must not raise when app has no 'auth'."""
        from aiohttp import web
        from parrot_formdesigner.api.routes import setup_form_api
        from parrot_formdesigner.services.registry import FormRegistry

        app = web.Application()
        registry = FormRegistry(require_tenant=False)
        setup_form_api(app, registry)  # must not raise


@pytest.mark.asyncio
class TestExcludeProviderBehavior:
    async def test_provider_yields_public_form_paths(self):
        """Provider returns paths only for is_public=True forms."""
        from parrot_formdesigner.core.schema import FormSchema

        forms = [
            FormSchema(form_id="pub", title="Public", sections=[], is_public=True),
            FormSchema(form_id="priv", title="Private", sections=[], is_public=False),
        ]
        registry = MagicMock()
        registry.list_forms = AsyncMock(return_value=forms)

        # Simulate provider logic:
        paths: list[str] = []
        result = await registry.list_forms()
        for form in result:
            if form.is_public:
                paths.extend(public_form_paths(form.form_id))

        assert len(paths) == 5  # 5 patterns for "pub"
        assert all("/forms/pub" in p for p in paths)
        assert not any("/forms/priv" in p for p in paths)

    async def test_provider_empty_when_no_public_forms(self):
        """Provider returns empty list when no is_public=True forms."""
        from parrot_formdesigner.core.schema import FormSchema

        forms = [
            FormSchema(form_id="priv", title="Private", sections=[], is_public=False),
        ]
        paths: list[str] = []
        for form in forms:
            if form.is_public:
                paths.extend(public_form_paths(form.form_id))
        assert paths == []

    async def test_provider_handles_list_forms_exception(self):
        """Provider returns [] when list_forms() raises."""
        registry = MagicMock()
        registry.list_forms = AsyncMock(side_effect=RuntimeError("DB down"))

        paths: list[str] = []
        try:
            result = await registry.list_forms()
            for form in result:
                if form.is_public:
                    paths.extend(public_form_paths(form.form_id))
        except Exception:
            pass  # Provider must swallow this
        assert paths == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** `sdd/specs/formdesigner-public-forms.spec.md` §3 M7.
2. **Check dependencies**:
   - TASK-1578 (navigator-auth `add_exclude_provider`) — must be done in navigator-auth.
   - TASK-1581 (`public_form_paths`) — must exist in `services/public_forms.py`.
   - TASK-1582 (auth toggle wiring in `setup_form_api`) — must be present to know insertion point.
3. **Verify Codebase Contract**:
   - Read `routes.py` end of `setup_form_api` (after TASK-1582 changes) to find exact insertion point.
   - Confirm `registry.list_forms()` signature at registry.py:591.
4. **Implement** the exclude-provider in `setup_form_api` after the toggle wiring.
5. **Run tests**: `source .venv/bin/activate && pytest packages/parrot-formdesigner/tests/unit/api/test_exclude_provider.py -v`.
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
**Notes**: Added `_public_forms_exclude_provider` async function in `setup_form_api` (after the M6 toggle wiring). The provider calls `registry.list_forms()`, filters by `is_public`, and returns paths via `public_form_paths`. Guarded with `app.get("auth")` and `hasattr(auth, "add_exclude_provider")`. 9 unit tests created and passing.

**Deviations from spec**: none
>>>>>>> feat-241-formdesigner-public-forms
