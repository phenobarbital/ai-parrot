---
type: Wiki Overview
title: 'TASK-1578: navigator-auth exclude-provider callback'
id: doc:sdd-tasks-completed-task-1578-navigator-auth-exclude-provider-callback-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements Module 2 of FEAT-241 in the **sibling repo `../navigator-auth`**.
---

# TASK-1578: navigator-auth exclude-provider callback

**Feature**: FEAT-241 — FormDesigner Public Forms
**Spec**: `sdd/specs/formdesigner-public-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1577
**Assigned-to**: unassigned

---

## Context

This task implements Module 2 of FEAT-241 in the **sibling repo `../navigator-auth`**.
It adds an exclude-provider callback registry to `AuthHandler` and wires it into the
existing `auth_startup` hook so parrot-formdesigner can supply a provider that
re-hydrates auth-exempt paths after a server restart.

Without this, every restart wipes all runtime exemptions (the exclude list is re-seeded
from defaults at `setup()` time — auth.py:535). The provider pattern is the canonical
solution: callers register an async callable that yields paths; `auth_startup` invokes
each provider and calls `register_exclusions` with the results.

**NOTE — Cross-repo task**: all files are under `../navigator-auth/`, NOT this repo.

---

## Scope

- Add `_exclude_providers: list[Callable[[], Awaitable[Iterable[str]]]]` storage to `AuthHandler.__init__`.
- Add `add_exclude_provider(provider: Callable[[], Awaitable[Iterable[str]]]) -> None`.
- In `auth_startup` (existing hook, line 110), iterate providers and call
  `self.register_exclusions(await provider())` for each.
- Write unit tests: `../navigator-auth/tests/unit/test_exclude_provider.py`.

**NOT in scope**: the parrot-formdesigner provider registration (M7/TASK-1583); the
bulk mutation API (M1/TASK-1577 — must be done first).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `../navigator-auth/navigator_auth/auth.py` | MODIFY | Add `_exclude_providers` list; `add_exclude_provider`; invoke providers in `auth_startup` |
| `../navigator-auth/tests/unit/test_exclude_provider.py` | CREATE | Unit tests for provider registration and startup invocation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# ../navigator-auth/navigator_auth/auth.py
from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY  # verified: auth.py:26

# standard library
from typing import Callable, Awaitable, Iterable
```

### Existing Signatures to Use
```python
# ../navigator-auth/navigator_auth/auth.py

class AuthHandler:
    def __init__(self, app_name: str = "auth", secure_cookies: bool = True, **kwargs) -> None:  # line 69
        # self.app set during setup(); extend __init__ with:
        # self._exclude_providers: list[Callable[[], Awaitable[Iterable[str]]]] = []

    async def auth_startup(self, app):  # line 110 — EXISTING startup hook appended at line 530
        # ... existing backend startup code ...
        # ADD: iterate self._exclude_providers here, after existing backend startup

    def setup(self, app: web.Application) -> web.Application:  # line 505
        self.app.on_startup.append(self.auth_startup)          # line 530 — already there
        self.app[AUTH_EXCLUDE_LIST_KEY] = list(exclude_list)   # line 535

    # NEW method added by TASK-1577 (must exist before this task runs):
    def register_exclusions(self, paths: Iterable[str]) -> None: ...
```

### Does NOT Exist
- ~~`AuthHandler._exclude_providers`~~ — **to be created by this task**
- ~~`AuthHandler.add_exclude_provider`~~ — **to be created by this task**
- ~~Any provider invocation in `auth_startup`~~ — does NOT exist today; to be added
- ~~`AuthHandler.register_exclusions`~~ until TASK-1577 is done — depend on it

---

## Implementation Notes

### Pattern to Follow

```python
# In AuthHandler.__init__ (after existing attribute assignments):
self._exclude_providers: list[Callable[[], Awaitable[Iterable[str]]]] = []

# New method:
def add_exclude_provider(
    self, provider: Callable[[], Awaitable[Iterable[str]]]
) -> None:
    """Register an async callable that yields auth-exempt paths.

    On each server startup, AuthHandler will call every registered provider
    and pass the yielded paths to register_exclusions(). This re-hydrates
    runtime exemptions after a restart.

    Args:
        provider: Async callable with no arguments returning an iterable of
                  path strings (glob patterns accepted).
    """
    self._exclude_providers.append(provider)

# In auth_startup (add at the END of the existing method body):
async def auth_startup(self, app):
    # ... existing code ...
    # Re-hydrate exclude-provider paths after each startup:
    for provider in self._exclude_providers:
        try:
            paths = await provider()
            self.register_exclusions(paths)
        except Exception as exc:
            self.logger.warning(
                "AuthHandler: exclude provider %r failed: %s", provider, exc
            )
```

### Key Constraints
- `_exclude_providers` must be initialized in `__init__`, not in `setup()`, so it is
  ready before `setup()` is called (callers may call `add_exclude_provider` before mounting).
- Provider failures must be caught and logged (warning), NOT raised — a broken provider
  must not prevent the server from starting.
- `register_exclusions` is implemented by TASK-1577; this task DEPENDS on it.

---

## Acceptance Criteria

- [ ] `add_exclude_provider(fn)` appends the callable to `_exclude_providers`.
- [ ] On `auth_startup`, each registered provider is awaited and its paths are passed
      to `register_exclusions`.
- [ ] A failing provider is logged at WARNING and does not abort startup.
- [ ] A provider registered BEFORE `setup()` is called still runs on startup.
- [ ] All unit tests pass: `cd ../navigator-auth && pytest tests/unit/test_exclude_provider.py -v`.
- [ ] `ruff check navigator_auth/auth.py` passes.

---

## Test Specification

```python
# ../navigator-auth/tests/unit/test_exclude_provider.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from navigator_auth.auth import AuthHandler
from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY


@pytest.fixture
def auth_handler():
    handler = AuthHandler.__new__(AuthHandler)
    handler._exclude_providers = []
    handler.app = {AUTH_EXCLUDE_LIST_KEY: []}
    handler.logger = MagicMock()
    return handler


class TestAddExcludeProvider:
    def test_registers_provider(self, auth_handler):
        async def my_provider():
            return ["/a", "/b"]
        auth_handler.add_exclude_provider(my_provider)
        assert my_provider in auth_handler._exclude_providers

    def test_multiple_providers(self, auth_handler):
        p1 = AsyncMock(return_value=["/a"])
        p2 = AsyncMock(return_value=["/b"])
        auth_handler.add_exclude_provider(p1)
        auth_handler.add_exclude_provider(p2)
        assert len(auth_handler._exclude_providers) == 2


@pytest.mark.asyncio
class TestExcludeProviderInvocation:
    async def test_provider_paths_registered_on_startup(self, auth_handler):
        async def provider():
            return ["/api/v1/forms/contact", "/api/v1/forms/contact/schema"]
        auth_handler.add_exclude_provider(provider)

        # Simulate the startup invocation segment (isolated):
        for p in auth_handler._exclude_providers:
            paths = await p()
            auth_handler.register_exclusions(paths)

        lst = auth_handler.app[AUTH_EXCLUDE_LIST_KEY]
        assert "/api/v1/forms/contact" in lst
        assert "/api/v1/forms/contact/schema" in lst

    async def test_failing_provider_is_logged_not_raised(self, auth_handler):
        async def bad_provider():
            raise RuntimeError("DB unavailable")
        auth_handler.add_exclude_provider(bad_provider)

        # Must not raise; must log a warning
        for p in auth_handler._exclude_providers:
            try:
                paths = await p()
                auth_handler.register_exclusions(paths)
            except Exception as exc:
                auth_handler.logger.warning(
                    "AuthHandler: exclude provider %r failed: %s", p, exc
                )
        auth_handler.logger.warning.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-public-forms.spec.md` for full context.
2. **Check TASK-1577 is complete** — `register_exclusions` must exist in `auth.py`.
3. **This is a cross-repo task**: work in `../navigator-auth/`.
4. **Verify Codebase Contract** — confirm `auth_startup` at line 110 and `on_startup` append at line 530.
5. **Implement** `_exclude_providers`, `add_exclude_provider`, and startup invocation.
6. **Run tests**: `cd ../navigator-auth && source .venv/bin/activate && pytest tests/unit/test_exclude_provider.py -v`.
7. **Commit**: `git add navigator_auth/auth.py tests/unit/test_exclude_provider.py && git commit -m "feat: M2 — exclude-provider callback (FEAT-241)"`.

---

## Completion Note

<<<<<<< HEAD
*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
=======
**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-16
**Notes**: Added `_exclude_providers` list to `AuthHandler.__init__`; added
`add_exclude_provider()` method; updated `auth_startup` to iterate providers
and call `register_exclusions()` on each, logging WARNING on failures. All 7
unit tests pass. Committed in navigator-auth on branch `feat-241-public-forms`.

**Deviations from spec**: none
>>>>>>> feat-241-formdesigner-public-forms
