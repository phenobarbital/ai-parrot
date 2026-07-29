---
type: Wiki Overview
title: 'TASK-1577: navigator-auth exclude-list mutation API'
id: doc:sdd-tasks-completed-task-1577-navigator-auth-exclude-list-mutation-api-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements Module 1 of FEAT-241 in the **sibling repo `../navigator-auth`**.
---

# TASK-1577: navigator-auth exclude-list mutation API

**Feature**: FEAT-241 — FormDesigner Public Forms
**Spec**: `sdd/specs/formdesigner-public-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements Module 1 of FEAT-241 in the **sibling repo `../navigator-auth`**.
It adds idempotent mutation methods to `AuthHandler` so parrot-formdesigner (M6) can
register and unregister auth-exempt paths at runtime.

The existing `add_exclude_list` (line 666) already appends to
`app[AUTH_EXCLUDE_LIST_KEY]`, but it is NOT idempotent (duplicates allowed) and there
is NO removal API. This task fixes both gaps with four clean methods.

**NOTE — Cross-repo task**: all files are under `../navigator-auth/`, NOT this repo.
The sdd-worker implements this directly in the sibling repo's working tree.

---

## Scope

- Make `add_exclude_list(path)` idempotent (append only if `path` not already present).
- Add `remove_exclude_list(path: str) -> None` — idempotent (no-op if absent).
- Add `register_exclusions(paths: Iterable[str]) -> None` — bulk idempotent add.
- Add `unregister_exclusions(paths: Iterable[str]) -> None` — bulk idempotent remove.
- Write unit tests: `../navigator-auth/tests/unit/test_exclude_list_mutations.py`.

**NOT in scope**: exclude-provider callbacks (M2/TASK-1578), decorator changes (M3/TASK-1579).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `../navigator-auth/navigator_auth/auth.py` | MODIFY | Make `add_exclude_list` idempotent; add `remove_exclude_list`, `register_exclusions`, `unregister_exclusions` |
| `../navigator-auth/tests/unit/test_exclude_list_mutations.py` | CREATE | Unit tests for all four mutation methods |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# ../navigator-auth/navigator_auth/auth.py
from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY  # verified: auth.py:26, conf.py:45

# standard library
from typing import Iterable
```

### Existing Signatures to Use
```python
# ../navigator-auth/navigator_auth/auth.py

class AuthHandler:
    def __init__(self, app_name: str = "auth", secure_cookies: bool = True, **kwargs) -> None:  # line 69
        self.name: str = app_name                          # line 70
        # self.app is set during setup()

    def setup(self, app: web.Application) -> web.Application:  # line 505
        self.app[AUTH_EXCLUDE_LIST_KEY] = list(exclude_list)  # line 535 — mutable list, re-seeded each boot
        self.app[self.name] = self                            # line 537

    def add_exclude_list(self, path: str):                     # line 666 — CURRENT (non-idempotent)
        self.app[AUTH_EXCLUDE_LIST_KEY].append(path)

    async def verify_exceptions(self, request: web.Request) -> bool:  # line 669
        for pattern in request.app.get(AUTH_EXCLUDE_LIST_KEY, ()):    # line 675
            if fnmatch.fnmatch(request.path, pattern):                # line 676
                return True

# ../navigator-auth/navigator_auth/conf.py
AUTH_EXCLUDE_LIST_KEY = "auth_exclude_list"  # line 45 (= "auth_exclude_list")
exclude_list = EXCLUDE_DEFAULTS + [...]      # line 58 — default seed (list)
```

### Does NOT Exist
- ~~`AuthHandler.remove_exclude_list`~~ — **to be created by this task**
- ~~`AuthHandler.register_exclusions`~~ — **to be created by this task**
- ~~`AuthHandler.unregister_exclusions`~~ — **to be created by this task**
- ~~`AuthHandler.add_exclude_provider`~~ — that's M2/TASK-1578
- ~~`frozenset` anywhere in navigator_auth exclude logic~~ — it's a mutable list

---

## Implementation Notes

### Pattern to Follow

Mirror the existing `add_exclude_list` idiom, mutating `self.app[AUTH_EXCLUDE_LIST_KEY]` in place:

```python
def add_exclude_list(self, path: str) -> None:
    """Idempotent: append path only if not already present."""
    lst: list[str] = self.app[AUTH_EXCLUDE_LIST_KEY]
    if path not in lst:
        lst.append(path)

def remove_exclude_list(self, path: str) -> None:
    """Idempotent: remove path if present, no-op otherwise."""
    lst: list[str] = self.app[AUTH_EXCLUDE_LIST_KEY]
    try:
        lst.remove(path)
    except ValueError:
        pass

def register_exclusions(self, paths: Iterable[str]) -> None:
    """Bulk idempotent add."""
    for path in paths:
        self.add_exclude_list(path)

def unregister_exclusions(self, paths: Iterable[str]) -> None:
    """Bulk idempotent remove."""
    for path in paths:
        self.remove_exclude_list(path)
```

### Key Constraints
- **Backward compatibility**: existing callers (`backends/external.py`, `adfs.py`,
  `oauth2/backend.py`, `basic.py`) call `add_exclude_list` which currently appends
  unconditionally. Making it idempotent (de-duplicate) is safe — all existing callers
  pass distinct paths so behavior is unchanged.
- Methods must operate on `self.app[AUTH_EXCLUDE_LIST_KEY]` (the per-app list), NOT on
  any global structure.
- Do NOT touch `base_middleware.exclude_routes` (the frozen per-middleware tuple — non-goal).

---

## Acceptance Criteria

- [ ] `add_exclude_list(path)` is idempotent: calling twice with the same path does not duplicate.
- [ ] `remove_exclude_list(path)` removes the path; calling on an absent path is a no-op (no exception).
- [ ] `register_exclusions(paths)` adds N paths idempotently.
- [ ] `unregister_exclusions(paths)` removes N paths idempotently.
- [ ] Existing callers that use `add_exclude_list` continue to work.
- [ ] All unit tests pass: `cd ../navigator-auth && pytest tests/unit/test_exclude_list_mutations.py -v`
- [ ] `ruff check navigator_auth/auth.py` in navigator-auth passes.

---

## Test Specification

```python
# ../navigator-auth/tests/unit/test_exclude_list_mutations.py
import pytest
from unittest.mock import MagicMock
from navigator_auth.auth import AuthHandler
from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY


@pytest.fixture
def auth_handler():
    handler = AuthHandler.__new__(AuthHandler)
    app = {AUTH_EXCLUDE_LIST_KEY: []}
    handler.app = app
    return handler


class TestAddExcludeListIdempotent:
    def test_adds_path(self, auth_handler):
        auth_handler.add_exclude_list("/api/v1/forms/test")
        assert "/api/v1/forms/test" in auth_handler.app[AUTH_EXCLUDE_LIST_KEY]

    def test_no_duplicate_on_second_add(self, auth_handler):
        auth_handler.add_exclude_list("/api/v1/forms/test")
        auth_handler.add_exclude_list("/api/v1/forms/test")
        lst = auth_handler.app[AUTH_EXCLUDE_LIST_KEY]
        assert lst.count("/api/v1/forms/test") == 1


class TestRemoveExcludeList:
    def test_removes_existing_path(self, auth_handler):
        auth_handler.app[AUTH_EXCLUDE_LIST_KEY].append("/api/v1/forms/test")
        auth_handler.remove_exclude_list("/api/v1/forms/test")
        assert "/api/v1/forms/test" not in auth_handler.app[AUTH_EXCLUDE_LIST_KEY]

    def test_noop_on_absent_path(self, auth_handler):
        # Must not raise
        auth_handler.remove_exclude_list("/nonexistent")


class TestBulkMutations:
    def test_register_exclusions_bulk(self, auth_handler):
        paths = ["/a", "/b", "/c"]
        auth_handler.register_exclusions(paths)
        for p in paths:
            assert p in auth_handler.app[AUTH_EXCLUDE_LIST_KEY]

    def test_register_exclusions_idempotent(self, auth_handler):
        auth_handler.register_exclusions(["/x", "/x"])
        assert auth_handler.app[AUTH_EXCLUDE_LIST_KEY].count("/x") == 1

    def test_unregister_exclusions_bulk(self, auth_handler):
        auth_handler.app[AUTH_EXCLUDE_LIST_KEY].extend(["/a", "/b", "/c"])
        auth_handler.unregister_exclusions(["/a", "/c"])
        lst = auth_handler.app[AUTH_EXCLUDE_LIST_KEY]
        assert "/a" not in lst
        assert "/c" not in lst
        assert "/b" in lst

    def test_unregister_exclusions_noop_on_absent(self, auth_handler):
        auth_handler.unregister_exclusions(["/nonexistent1", "/nonexistent2"])
        # Must not raise
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-public-forms.spec.md` for full context.
2. **This is a cross-repo task**: work in `../navigator-auth/`, NOT in this repo.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `add_exclude_list` at line 666 of `../navigator-auth/navigator_auth/auth.py`.
   - Confirm `AUTH_EXCLUDE_LIST_KEY` at line 45 of `../navigator-auth/navigator_auth/conf.py`.
4. **Implement** following the scope above.
5. **Verify** all acceptance criteria are met.
6. **Run tests** in the navigator-auth repo: `cd ../navigator-auth && source .venv/bin/activate && pytest tests/unit/test_exclude_list_mutations.py -v`.
7. **Commit** in the navigator-auth repo: `git add navigator_auth/auth.py tests/unit/test_exclude_list_mutations.py && git commit -m "feat: M1 — exclude-list mutation API (FEAT-241)"`.

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
**Notes**: Implemented all four mutation methods in `../navigator-auth/navigator_auth/auth.py`.
Made `add_exclude_list` idempotent; added `remove_exclude_list`, `register_exclusions`,
`unregister_exclusions`. All 11 unit tests pass. `Iterable` was already imported from
`collections.abc` at the top of auth.py (no import change needed). Committed in
navigator-auth on branch `feat-241-public-forms`.

**Deviations from spec**: none
>>>>>>> feat-241-formdesigner-public-forms
