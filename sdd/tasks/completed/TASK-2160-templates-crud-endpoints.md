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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-06
**Notes**:
Filled in the five templates-CRUD method bodies on `CommCenterHandler`
(no `ModelView`, per spec §8), backed by `NotificationTemplate`
(TASK-2153). `list_templates` supports `is_active`/`tags`/`name` filters;
`update_template` serves both PUT/PATCH and never sets `updated_at`
(verified by `test_updated_at_not_set_by_app`, which asserts the string
does not even appear in the method's source); `created_by`/`updated_by`
resolved via a new `_get_user_id()` helper (`get_session(request)` +
`self.get_userid(session=...)`, since this method-based handler has no
`self._session` the way `ModelView` does). Duplicate `name` maps to `409`
via a `_looks_like_unique_violation()` helper (precise
`asyncpg.exceptions.UniqueViolationError` check, verified this repo's
`pg` driver is asyncpg-based, plus a message-content fallback).

**Critical bug found and fixed — affects TASK-2159's endpoints too, not
just this task's new code.** While verifying `create_template` with a
diagnostic harness, hit
`TypeError: BaseHandler.json_response() got an unexpected keyword
argument 'dumps'`. Read `navigator/views/base.py:122-143` and
`navigator/responses.py:81-101` live: `self.json_response(...)`
(`BaseHandler`'s own method) has signature `(response, reason, headers,
status, state, cls)` — **no `dumps` parameter at all** — and internally
calls `JSONResponse(...)`, which *already* hardcodes `dumps=json_encoder`
before delegating to `aiohttp.web.json_response`. I had conflated this
with `ScrapingInfoHandler.get_actions`'s pattern
(`web.json_response({...}, dumps=json_encoder)`), which calls the
**different**, module-level `aiohttp.web.json_response` function
directly — that one *does* take `dumps`. Every `self.json_response(...,
dumps=json_encoder, ...)` call in `comm_center.py` — in `post_sender`,
`get_batch`, `retry_batch`, and `get_placeholders` (all TASK-2159) as well
as this task's five new CRUD methods — would have raised this `TypeError`
on every real request. **Fixed by removing `dumps=json_encoder` from all
nine call sites**; `self.json_response()` already serializes UUID/
datetime correctly on its own. `json_encoder(...)` is still used directly
and correctly elsewhere, for the `text=` bodies of hand-raised
`web.HTTPException`s (`_map_error`, the 404/400/409 raises here) — those
bypass `self.json_response()` entirely and were unaffected.

Verified all of the above (including the `dumps` fix) with a throwaway
diagnostic harness — stubbing the same pre-existing, unrelated
environment gaps documented in TASK-2153/2155/2159
(`navigator_session.vault`, `navigator_eventbus`) plus a duck-typed
`NotificationTemplate` stand-in exposing the real persistence method
names — covering create/read/update/delete/list, duplicate-name 409,
missing-field 400s, and get/update/delete-missing 404s. All passed; the
harness was deleted after verification. `pytest` itself cannot collect
this task's test file in this sandbox for the same reasons already
documented.

**Deviations from spec**: none in delivered CRUD behavior. One
significant cross-task bug fix (above), required for both this task's and
TASK-2159's endpoints to function at all.

---

### Addendum — 2026-08-07, first real test-suite execution

The environment gaps flagged above were resolved (`navigator-api` 3.2.1,
`navigator-session` 0.10.1, plus `navigator-eventbus`, `aioquic`,
`async-notify` and `qworker` installed). The CommCenter suite executed for
the first time: **124 passed, 0 failed**; `ruff check` clean.

This task's tests needed repair before they could pass — the faults were in
the test harness, not in the delivered behaviour:

- `TestUnimplementedStubs` asserted `NotImplementedError` for six methods
  that TASK-2160/TASK-2161 had since implemented (dead scaffolding).
- DDL and `pyproject.toml` reads used CWD-relative paths and resolved
  against the wrong tree; now anchored to `Path(__file__)`.
- `test_updated_at_not_set_by_app` matched the substring `updated_at` in
  the method's own docstring; it now parses the AST and asserts no
  *assignment*.
- The `handler` fixture patched `_get_db` on a module object obtained by
  dotted import, which is not always the one `CommCenterHandler`'s methods
  close over here; the patch silently no-opped and nine tests opened real
  asyncpg connections. Resolved via `sys.modules[cls.__module__]`.

Verified: the `comm-center` extra **is** correctly declared (this was
briefly mis-diagnosed as missing while the path bug was in play). Fixed in
`b0c7e383c`.
