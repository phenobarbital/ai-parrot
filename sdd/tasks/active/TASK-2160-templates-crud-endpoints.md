# TASK-2160: Templates CRUD endpoints

**Feature**: FEAT-417 — CommCenter — Bulk Notification Sender over NotifyWorker
**Spec**: `sdd/specs/commcenter-notify.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2153, TASK-2159
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (CRUD half) + Module 1. Fills in the five templates-CRUD
method bodies stubbed by TASK-2159, backed by the model from TASK-2153.

Per spec §8, CRUD is **hand-written on `CommCenterHandler`** rather than a
`ModelView` subclass, because the requirement puts all endpoints on the same
`BaseHandler`. A `ModelView` would need a second class and separate route
registration.

---

## Scope

- Implement `list_templates`, `get_template`, `create_template`,
  `update_template`, `delete_template` on `CommCenterHandler`.
- Populate `created_by` / `updated_by` from the authenticated session.
- Map the unique-name violation to `409`.
- Support filtering the list by `is_active` and `tags`.
- Let `update_template` serve both `PUT` (full) and `PATCH` (partial).
- Unit tests.

**NOT in scope**:
- The model/DDL (TASK-2153).
- Route registration (TASK-2159 already did it).
- Template *resolution* during send (TASK-2157 owns that).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/comm_center.py` | MODIFY | Fill in the five CRUD methods |
| `packages/ai-parrot-server/tests/handlers/test_comm_center_templates.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified fresh 2026-08-06.

### Verified Imports

```python
import uuid
from typing import Any, Dict, List, Optional

from aiohttp import web
from asyncdb import AsyncDB                      # verified: handlers/bots.py:5
from asyncdb.exceptions import NoDataFound       # verified: handlers/bots.py:6
from navigator_auth.decorators import is_authenticated

from parrot.handlers.models import NotificationTemplate   # TASK-2153
from parrot.conf import PARROT_SCHEMA                     # verified live → "navigator"
```

### Existing Signatures to Use

```python
# navigator.views.base.BaseHandler — VERIFIED live
async def get_json(self, request: web.Request = None) -> Any
def json_response(self, response: dict = None, reason: str = None,
                  headers: dict = None, status: int = 200, ...)
def error(self, response: dict = None, exception: Exception = None,
          status: int = 400, ...) -> web.Response
async def get_userid(self, session, idx: str = 'user_id') -> int
def query_parameters(self, request: web.Request) -> dict
def match_parameters(self, request: web.Request)    # URL path params
```

```python
# packages/ai-parrot-server/src/parrot/handlers/models/notification_templates.py (TASK-2153)
class NotificationTemplate(Model):
    template_id: uuid.UUID   # PK, default_factory=uuid.uuid4
    name: str                # UNIQUE
    template_string: str
    subject / provider / description: Optional[str]
    tags: list
    is_active: bool = True
    created_at / updated_at: datetime
    created_by / updated_by: Optional[int]
    class Meta:
        driver = "pg"; name = "notification_templates"; schema = PARROT_SCHEMA
```

```python
# packages/ai-parrot-server/src/parrot/handlers/bots.py:109 — userid pattern
value = await self.get_userid(session=self._session)
```

### Does NOT Exist

- ~~`ModelView` being used for this feature~~ — spec §8 explicitly chose
  hand-written methods on `CommCenterHandler`. Do NOT introduce a `ModelView`.
- ~~A `user_id` column on `notification_templates`~~ — templates are **global**.
  Only `created_by` / `updated_by` exist. Do not filter the list by user.
- ~~Application code setting `updated_at`~~ — the DB trigger owns it
  (TASK-2153's DDL). Do not set it in Python on update.
- ~~`BaseHandler.get_session()`~~ — not in the verified member list.

---

## Implementation Notes

### Endpoint behavior

| Method | Path | Behavior |
|---|---|---|
| `GET` | `/templates` | List; optional `?is_active=true`, `?tags=a,b`, `?name=` |
| `GET` | `/templates/{template_id}` | One row, or `404` |
| `POST` | `/templates` | Create; `created_by` from session; `409` on duplicate `name` |
| `PUT` | `/templates/{template_id}` | Full update |
| `PATCH` | `/templates/{template_id}` | Partial update |
| `DELETE` | `/templates/{template_id}` | Delete, or `404` |

- `PUT`/`PATCH` set `updated_by` from the session; **never** set `updated_at`.
- Duplicate `name` → catch the unique violation and return `409` with a clear
  message (do not leak the raw Postgres error).
- Validate that `template_string` is non-empty on create.

### Key Constraints
- `@is_authenticated` on all five (may already be applied at the route level by
  TASK-2159 — verify and do not double-apply).
- Async throughout; use `AsyncDB('pg', dsn=default_dsn)` per the repo pattern.
- Return `json_response(..., status=...)`; use `self.error(...)` for failures.
- Google-style docstrings + type hints; `self.logger` for writes.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/bots.py:5-6,109,214-223` — AsyncDB + userid
- `packages/ai-parrot-server/src/parrot/handlers/scraping/info.py` — response style

---

## Acceptance Criteria

- [ ] All five CRUD methods implemented on `CommCenterHandler` (no `ModelView`)
- [ ] Create returns `201`/`200` with the new `template_id`
- [ ] Duplicate `name` → `409` with a clean message
- [ ] `GET` by id returns `404` when absent
- [ ] List supports `is_active` / `tags` / `name` filters
- [ ] `PUT` and `PATCH` both work; `updated_by` set from session
- [ ] **`updated_at` is never set by application code** (trigger owns it)
- [ ] `DELETE` removes the row; `404` when absent
- [ ] All endpoints require authentication
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_comm_center_templates.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
import pytest


class TestTemplatesCRUD:
    async def test_create_and_read(self, client, auth):
        r = await client.post("/api/v1/comm_center/templates", json={
            "name": "welcome", "template_string": "Hola {{ name }}",
            "subject": "Bienvenido", "provider": "email"})
        assert r.status in (200, 201)
        tid = (await r.json())["template_id"]
        g = await client.get(f"/api/v1/comm_center/templates/{tid}")
        assert (await g.json())["name"] == "welcome"

    async def test_duplicate_name_conflicts(self, client, auth):
        payload = {"name": "dup", "template_string": "x"}
        await client.post("/api/v1/comm_center/templates", json=payload)
        r = await client.post("/api/v1/comm_center/templates", json=payload)
        assert r.status == 409

    async def test_get_missing_returns_404(self, client, auth):
        import uuid
        r = await client.get(f"/api/v1/comm_center/templates/{uuid.uuid4()}")
        assert r.status == 404

    async def test_patch_partial_update(self, client, auth): ...

    async def test_updated_at_not_set_by_app(self, client, auth):
        """The trigger owns updated_at — the UPDATE statement must not set it."""
        ...

    async def test_created_by_from_session(self, client, auth): ...

    async def test_list_filters_by_is_active(self, client, auth): ...

    async def test_requires_authentication(self, client): ...
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 1/7, §8 (the hand-written-CRUD decision)
2. **Check dependencies** — TASK-2153 and TASK-2159 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm the stub methods TASK-2159 left,
   and that the model matches TASK-2153's final shape
4. **Update status** in `sdd/tasks/index/commcenter-notify.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** acceptance criteria
7. **Move** to `sdd/tasks/completed/TASK-2160-templates-crud-endpoints.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
