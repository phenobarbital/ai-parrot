# TASK-2112: `UserInfoService` + `EmployeeProfile`

**Feature**: FEAT-406 — PBAC Guardrails
**Spec**: `sdd/specs/pbac-guardrails.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The PBAC engine needs structured user attributes, but the current `UserInfo` /
`UserProfileKB` knowledge bases flatten `auth.vw_users` into prose "facts" for the
system prompt. There is no single structured source for PBAC `EvalContext`
construction or for the LLM to query as JSON.

This task introduces `UserInfoService` — a standalone service that loads a curated
`EmployeeProfile` (Pydantic) from `auth.vw_users` via asyncdb, with a TTL-cached
per-user lookup. The manager field is resolved as a nested `ManagerRef` object
with one extra DB lookup.

This is a parallel lane — no dependency on the guardrail tasks (Lane A).

Implements spec §3 Module 4.

---

## Scope

- Create `EmployeeProfile` (Pydantic BaseModel) in `packages/ai-parrot/src/parrot/auth/userinfo.py`:
  - Fields: `user_id`, `username`, `display_name`, `email`, `job_code`, `title`,
    `department_code`, `groups` (list[str]), `programs` (list[str]), `worker_type`,
    `manager` (nested `ManagerRef | None`)
- Create `ManagerRef` (Pydantic BaseModel): `user_id`, `display_name`, `email`
- Create `UserInfoService` class:
  - Lazy DSN via `querysource.conf` (same pattern as `stores/kb/user.py:25-26`)
  - `TTLCache` per user (mirror `stores/kb/user.py:27` — `max_size=500, default_ttl=600`)
  - `async def get_profile(self, user_id) -> EmployeeProfile | None`:
    - Fetch from `auth.vw_users` via asyncdb `fetch_one`
    - If `manager_id` present, sub-lookup for manager row → `ManagerRef`
    - Cache the assembled profile
    - Missing row → `None`, no exception
- Export from `parrot/auth/__init__.py`: `EmployeeProfile`, `UserInfoService`
- Write unit tests

**NOT in scope**: `UserinfoTool` (TASK-2113), PBAC attribute enrichment (TASK-2114),
or any modification to existing `UserInfo`/`UserProfileKB` KBs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/userinfo.py` | CREATE | `EmployeeProfile`, `ManagerRef`, `UserInfoService` |
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | Export new classes |
| `packages/ai-parrot/tests/auth/test_userinfo_service.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field

# Lazy DSN pattern — from stores/kb/user.py:25-26
from navconfig import config as _qs_conf       # querysource.conf
from asyncdb import AsyncDB                     # asyncdb fetch_one

# TTLCache pattern — from stores/kb/user.py:27
from parrot.stores.cache import TTLCache        # stores/cache.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/stores/kb/user.py:25-30
# Lazy DSN + TTLCache pattern:
_qs_conf = None
def _get_qs_conf():
    global _qs_conf
    if _qs_conf is None:
        _qs_conf = lazy_import("querysource.conf")
    return _qs_conf
# TTLCache(max_size=500, default_ttl=600) at line 27

# packages/ai-parrot/src/parrot/stores/kb/user.py:49-57 — auth.vw_users columns:
# user_id, display_name, username, email, job_code, associate_id, associate_oid,
# title, worker_type, manager_id

# packages/ai-parrot/src/parrot/stores/kb/user.py:116-124 — UserProfileKB columns:
# first_name, last_name, email, job_code, title, department_code, groups, programs
```

### Does NOT Exist
- ~~`parrot/auth/userinfo.py`~~ — does not exist; this task creates it.
- ~~`UserInfoService`~~ — does not exist anywhere.
- ~~`EmployeeProfile`~~ — does not exist anywhere.
- ~~`ManagerRef`~~ — does not exist anywhere.
- ~~`auth.vw_users.department_code`~~ — column is in `UserProfileKB`'s view; verify it's also in `vw_users` or use the profile KB query.
- ~~`auth.vw_users.groups` / `auth.vw_users.programs`~~ — these are in the profile KB's distinct view, not necessarily in `vw_users`; may need a join or second query.

---

## Implementation Notes

### Pattern to Follow
Mirror `stores/kb/user.py` for the lazy DSN and TTLCache pattern:
```python
import logging
from typing import Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_qs_conf = None
def _get_dsn():
    global _qs_conf
    if _qs_conf is None:
        from navconfig import config
        _qs_conf = config
    return _qs_conf.default_dsn

class ManagerRef(BaseModel):
    user_id: int | str
    display_name: str | None = None
    email: str | None = None

class EmployeeProfile(BaseModel):
    user_id: int | str
    username: str | None = None
    # ... all fields per spec §2 Data Models
    manager: ManagerRef | None = None

class UserInfoService:
    def __init__(self, dsn=None, cache_ttl=600, cache_max_size=500):
        self._dsn = dsn
        self._cache = TTLCache(max_size=cache_max_size, default_ttl=cache_ttl)
        self.logger = logging.getLogger(__name__)

    async def get_profile(self, user_id) -> EmployeeProfile | None:
        cached = self._cache.get(str(user_id))
        if cached is not None:
            return cached
        # fetch from auth.vw_users, resolve manager, cache, return
```

### Key Constraints
- `groups` and `programs` may require a separate query or join — verify the actual
  `auth.vw_users` schema at runtime or check `UserProfileKB` for the query pattern
- `manager` must be the nested `{user_id, display_name, email}` object (spec Q6)
- Missing row → `None`, never an exception
- `asyncdb` is async — all DB calls must be `await`ed
- No modification to existing `UserInfo`/`UserProfileKB` classes

### References in Codebase
- `packages/ai-parrot/src/parrot/stores/kb/user.py` — lazy DSN, TTLCache, `auth.vw_users` query
- `packages/ai-parrot/src/parrot/stores/cache.py` — TTLCache implementation

---

## Acceptance Criteria

- [ ] `EmployeeProfile` Pydantic model with all curated fields
- [ ] `ManagerRef` nested model with `{user_id, display_name, email}`
- [ ] `UserInfoService.get_profile(user_id)` returns `EmployeeProfile` for valid user
- [ ] Second call within TTL hits cache (single DB query verified)
- [ ] Unknown user → `None`, no exception
- [ ] Exported from `parrot.auth`: `from parrot.auth import EmployeeProfile, UserInfoService`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/auth/test_userinfo_service.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/auth/userinfo.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/auth/test_userinfo_service.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.auth.userinfo import EmployeeProfile, ManagerRef, UserInfoService


@pytest.fixture
def fake_vw_users_row():
    return {
        "user_id": 42, "username": "jlara", "display_name": "Jesus Lara",
        "email": "jlara@example.com", "job_code": "ENG-3", "title": "Sr Engineer",
        "department_code": "TECH", "worker_type": "FTE", "manager_id": 10,
        "groups": ["engineering", "platform"], "programs": ["ai-parrot"],
    }


@pytest.fixture
def fake_manager_row():
    return {"user_id": 10, "display_name": "Manager Name", "email": "mgr@example.com"}


class TestEmployeeProfile:
    def test_profile_curated_fields(self, fake_vw_users_row, fake_manager_row):
        """EmployeeProfile exposes exactly the curated set; manager is nested."""

    def test_manager_ref_nested(self):
        """ManagerRef has user_id, display_name, email."""


class TestUserInfoService:
    async def test_get_profile_returns_profile(self):
        """Valid user_id → EmployeeProfile."""

    async def test_profile_cache_ttl(self):
        """Second call within TTL hits cache (single DB query)."""

    async def test_profile_missing_row(self):
        """Unknown user → None, no exception."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task (parallel lane)
3. **Verify the Codebase Contract** — read `stores/kb/user.py` to confirm DSN/TTLCache pattern and `auth.vw_users` columns
4. **Update status** in `sdd/tasks/index/pbac-guardrails.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2112-userinfo-service-employee-profile.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
