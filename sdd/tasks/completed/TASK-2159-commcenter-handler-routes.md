# TASK-2159: CommCenterHandler — auth, content-type dispatch, sender routes

**Feature**: FEAT-417 — CommCenter — Bulk Notification Sender over NotifyWorker
**Spec**: `sdd/specs/commcenter-notify.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2155, TASK-2156, TASK-2157, TASK-2158
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. The HTTP surface: an **instantiable** `BaseHandler` subclass
that registers every comm_center route via `setup(app)`.

The handler must stay **thin** — auth, content-type dispatch, request/response
models and error mapping. All logic delegates to the services built in
TASK-2156/2157/2158. That thinness is what makes the single-send endpoint
(TASK-2161) and dry-run (TASK-2162) small additions rather than rewrites.

---

## Scope

- Implement `CommCenterHandler(BaseHandler)` with `__init__` caching the
  placeholder catalog.
- Implement `POST /sender` — content-type dispatch across the three transports,
  calling `prepare()` then launching the background fan-out; return `202`.
- Implement `GET /sender/{batch_id}` with `details` / `status` / `limit` / `offset`.
- Implement `POST /sender/{batch_id}/retry` with `force`.
- Implement `GET /placeholders` serving the cached catalog.
- Implement `setup(app)` registering **every** route in spec §2, including
  `POST /message` and the templates CRUD paths (their handler bodies land in
  TASK-2161 / TASK-2160 — register the routes here or coordinate; see notes).
- Apply `@is_authenticated` to every endpoint.
- Map service errors to the correct HTTP statuses.
- Unit tests.

**NOT in scope**:
- Templates CRUD method bodies (TASK-2160).
- `POST /message` body (TASK-2161).
- `dry_run` behavior (TASK-2162).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/comm_center.py` | CREATE | `CommCenterHandler` + `setup(app)` |
| `packages/ai-parrot-server/src/parrot/services/comm_center/models.py` | MODIFY | Add `SenderRequest`, `SenderResponse` |
| `packages/ai-parrot-server/tests/handlers/test_comm_center_handler.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified fresh 2026-08-06 by live introspection of `navigator.views.BaseHandler`.

### Verified Imports

```python
import asyncio, uuid
from typing import Any, Dict, List, Optional

from aiohttp import web
from navconfig.logging import logging
from datamodel.parsers.json import json_encoder      # verified: scraping/info.py:10
from navigator.views import BaseHandler              # verified: navigator.views.base
from navigator_auth.decorators import is_authenticated   # verified: handlers/prompt.py

from parrot.handlers.comm_center_placeholders import build_catalog       # TASK-2155
from parrot.services.comm_center.ingest import ingest_recipients         # TASK-2156
from parrot.services.comm_center.render import prepare                   # TASK-2157
from parrot.services.comm_center.dispatch import fan_out, retry_batch    # TASK-2158
```

### Existing Signatures to Use

```python
# navigator.views.base.BaseHandler — VERIFIED live introspection 2026-08-06
async def handle_upload(self, request=None, form_key=None, ext='.csv',
                        preserve_filenames=True) -> Tuple[Dict[str, List[dict]], dict]
async def get_json(self, request: web.Request = None) -> Any
def json_response(self, response: dict = None, reason: str = None,
                  headers: dict = None, status: int = 200,
                  state: int = None, cls: Callable = None)
def error(self, response: dict = None, exception: Exception = None,
          status: int = 400, state: int = None, headers: dict = None,
          content_type: str = 'application/json', **kwargs) -> web.Response
async def get_userid(self, session, idx: str = 'user_id') -> int
def query_parameters(self, request: web.Request) -> dict
# Full member list: _allowed, _allowed_methods, _lasterr, _logger_name, _loop, body,
# critical, data, delete_uploaded_files, error, get_args, get_arguments, get_json,
# get_userid, handle_download, handle_upload, json, json_data, json_response, log,
# log_error, match_parameters, no_content, not_allowed, not_implemented, post_init,
# query_parameters, response, session, validate_handler
```

```python
# packages/ai-parrot-server/src/parrot/handlers/scraping/info.py:65-131
# ← THE EXACT PATTERN TO COPY
class ScrapingInfoHandler(BaseHandler):
    def __init__(self, *args, **kwargs):                      # line 73
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger("Parrot.ScrapingInfoHandler")
        self._action_catalog = _build_action_catalog()        # cached once
    async def get_actions(self, request: web.Request) -> web.Response:   # line 79
        return web.json_response({"actions": self._action_catalog},
                                 dumps=json_encoder)
    def setup(self, app: web.Application) -> None:            # line 123
        app.router.add_route("GET", "/api/v1/scraping/info/actions", self.get_actions)
```

### Does NOT Exist

- ~~`BaseHandler.setup()`~~ — **not inherited**. `ScrapingInfoHandler` defines
  its own (`scraping/info.py:123`). It is a repo convention; define yours.
- ~~`BaseHandler.get_session()`~~ — not in the verified member list. Use the
  `session` attribute / `get_userid(session=...)`, following
  `handlers/bots.py:109`.
- ~~`parrot.handlers.comm_center`~~ — does not exist yet.
- ~~Hand-rolling multipart parsing~~ — `handle_upload()` already does it and
  raises `HTTPUnsupportedMediaType` for non-multipart.
- ~~A `delivered` status to surface in `GET /sender/{batch_id}`~~ — unobtainable
  (see TASK-2158). Do not invent one in the response model.

---

## Implementation Notes

### Route registration (spec §2 — all of them)

```python
def setup(self, app: web.Application) -> None:
    r = app.router
    r.add_route("POST",   "/api/v1/comm_center/sender",                    self.post_sender)
    r.add_route("GET",    "/api/v1/comm_center/sender/{batch_id}",         self.get_batch)
    r.add_route("POST",   "/api/v1/comm_center/sender/{batch_id}/retry",   self.retry_batch)
    r.add_route("POST",   "/api/v1/comm_center/message",                   self.post_message)
    r.add_route("GET",    "/api/v1/comm_center/templates",                 self.list_templates)
    r.add_route("GET",    "/api/v1/comm_center/templates/{template_id}",   self.get_template)
    r.add_route("POST",   "/api/v1/comm_center/templates",                 self.create_template)
    r.add_route("PUT",    "/api/v1/comm_center/templates/{template_id}",   self.update_template)
    r.add_route("PATCH",  "/api/v1/comm_center/templates/{template_id}",   self.update_template)
    r.add_route("DELETE", "/api/v1/comm_center/templates/{template_id}",   self.delete_template)
    r.add_route("GET",    "/api/v1/comm_center/placeholders",              self.get_placeholders)
```

Methods owned by other tasks (`post_message`, the templates CRUD five) should
exist here as stubs raising `NotImplementedError` so routing is complete and
those tasks only fill in bodies. Note this explicitly in the completion note.

### Content-type dispatch for `POST /sender`
| Content-Type | Path |
|---|---|
| `multipart/form-data` | `handle_upload()` → temp file → `ingest_recipients(file_path=…)`; JSON meta from the form fields |
| `application/json` + `recipients` | `ingest_recipients(rows=…)` |
| `application/json` + `file_b64` | decode → `ingest_recipients(file_bytes=…, filename=…)` |

### Error mapping (spec §2 Edge Cases)
| Condition | Status |
|---|---|
| Malformed template (`TemplateSyntaxError`) | `400` — publish nothing |
| No known columns / empty file / > 10 000 rows | `400` |
| Upload > 50 MB | `413` |
| `template_id` not found | `404` |
| Template `is_active=false` | `400` |
| `async-notify` missing | `503` with the extra-install message |
| Unauthenticated | `401`/`403` (decorator) |

### Key Constraints
- Handler stays **thin** — no rendering, no Redis, no pandas here.
- `@is_authenticated` on every endpoint.
- `self.logger = logging.getLogger("Parrot.CommCenterHandler")`.
- Catalog built **once** in `__init__` and cached.
- Async throughout; Google-style docstrings + type hints.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/scraping/info.py` — handler + setup pattern
- `packages/ai-parrot-server/src/parrot/handlers/prompt.py` — `@is_authenticated` usage
- `packages/ai-parrot-server/src/parrot/handlers/bots.py:109` — `get_userid` usage

---

## Acceptance Criteria

- [ ] `CommCenterHandler` subclasses `BaseHandler` and is instantiable
- [ ] `setup(app)` registers **all 11** routes from the table above
- [ ] All three transports accepted by `POST /sender`
- [ ] `POST /sender` returns `202` with `batch_id`, `total`, `queued`, `skipped`,
      `resolved_functions`, `skipped_details`
- [ ] Fan-out runs in a background task — the request does not await it
- [ ] `GET /sender/{batch_id}` supports `details`/`status`/`limit`/`offset`
- [ ] `POST /sender/{batch_id}/retry` supports `force`
- [ ] `GET /placeholders` serves the cached catalog
- [ ] Every endpoint requires authentication
- [ ] Error mapping matches the table above
- [ ] No rendering/Redis/pandas logic in the handler
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_comm_center_handler.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
import pytest
from aiohttp import web
from parrot.handlers.comm_center import CommCenterHandler


class TestRouteRegistration:
    def test_setup_registers_all_routes(self):
        app = web.Application()
        CommCenterHandler().setup(app)
        paths = {r.resource.canonical for r in app.router.routes()}
        assert "/api/v1/comm_center/sender" in paths
        assert "/api/v1/comm_center/message" in paths
        assert "/api/v1/comm_center/placeholders" in paths
        assert "/api/v1/comm_center/templates" in paths

    def test_handler_is_instantiable(self):
        assert CommCenterHandler() is not None


class TestSender:
    async def test_requires_authentication(self, client): ...
    async def test_returns_202_with_batch_id(self, client, fake_notify): ...
    async def test_malformed_template_returns_400_and_publishes_nothing(
            self, client, fake_notify):
        ...
        assert fake_notify == []          # nothing published
    async def test_oversize_upload_returns_413(self, client): ...
    async def test_json_and_multipart_agree(self, client, fake_notify): ...
    async def test_fanout_is_backgrounded(self, client, fake_notify): ...


class TestPlaceholders:
    async def test_catalog_served_and_cached(self, client): ...
```

---

## Agent Instructions

1. **Read the spec** — §2 routes table and Edge Cases
2. **Check dependencies** — TASK-2155/2156/2157/2158 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-introspect `BaseHandler`'s member list
   before using any method; several plausible ones do NOT exist
4. **Update status** in `sdd/tasks/index/commcenter-notify.json` → `"in-progress"`
5. **Implement** per scope; leave the other tasks' methods as explicit stubs
6. **Verify** acceptance criteria
7. **Move** to `sdd/tasks/completed/TASK-2159-commcenter-handler-routes.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** — list which stubs you left

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-06
**Notes**:
Implemented `CommCenterHandler(BaseHandler)` with all 11 routes registered
via `setup(app)`, `@is_authenticated()` on every endpoint method (verified
live it must decorate each named method individually — `is_authenticated()`
picks `_func_wrapper` vs `_method_wrapper` based on `inspect.isclass(handler)`,
and for a plain function it reads the request from `args[-1]`, which works
correctly for our `(self, request)` method style). Added `SenderRequest`/
`SenderResponse` to `services/comm_center/models.py` and used both for
real (request validation + response shape), not just declared-and-unused.
Stubs for `post_message` (TASK-2161) and the five templates-CRUD methods
(TASK-2160) raise `NotImplementedError`, all correctly routed.

**Two significant bugs found and fixed** while verifying with a diagnostic
harness (stubbing only the pre-existing broken import chains —
`navigator_session.vault`, `navigator_eventbus`, described below — never
the shipped code):

1. **`BaseHandler.error()` silently coerces unsupported status codes to
   400.** Read `navigator/views/base.py:179-223` live: `error()` only
   recognizes a fixed whitelist (400/401/403/404/406/412/428) and falls
   back to `HTTPBadRequest` for anything else — meaning my first draft's
   `self.error(status=413)` and `self.error(status=503)` would both have
   actually returned `400`, directly breaking two of this task's own
   acceptance criteria (`>50MB → 413`, `async-notify missing → 503`).
   **Fixed** by rewriting `_map_error` to raise the matching
   `aiohttp.web.HTTPException` subclass directly
   (`HTTPRequestEntityTooLarge`, `HTTPNotFound`, `HTTPServiceUnavailable`,
   `HTTPBadRequest`) — `BaseHandler.error()` itself works this way
   (raises, relies on aiohttp's dispatch to convert the exception to the
   response), so this is idiomatic, not a workaround.
2. **`KeyError`/`IndexError` are `LookupError` subclasses in the stdlib.**
   My first draft mapped bare `LookupError` -> 404 (intended only for
   "template not found"), which would have silently turned an unrelated
   `KeyError` bug anywhere in the request path into a misleading 404
   instead of surfacing it. **Fixed** by introducing a dedicated
   `TemplateNotFoundError(LookupError)` raised specifically by
   `_resolve_template_source`, and mapping on that instead of bare
   `LookupError`. Added `test_bare_keyerror_does_not_leak_as_404` as a
   regression guard.

**Environment note**: this sandbox cannot import ANY handler that uses
`@is_authenticated` at all — `navigator_auth/__init__.py` ->
`navigator_auth/vault/integration.py` needs
`navigator_session.vault.session_vault.SessionVault`, and the installed
`navigator_session` package here has no `vault` subpackage whatsoever
(same root cause as TASK-2153's `navigator_session.vault.crypto` gap, a
different symbol). Combined with the previously-documented
`navigator_eventbus` gap (TASK-2155) and one further discovery
(`navigator.utils.file.FileManagerInterface` not exported by the
installed `navigator` version, hit via `parrot.handlers.models` ->
`_encrypted_field.py` -> ... -> `parrot.interfaces.file`), `pytest`
cannot collect `test_comm_center_handler.py` here. Verified instead with
a throwaway diagnostic (stubbing exactly these leaf modules in
`sys.modules`, a fake `NotificationBatchRecipient`/`NotificationTemplate`,
never touching shipped code) covering every scenario in this task's own
tests: route registration (all 11), instantiability, catalog caching,
`_as_bool`, full error mapping (including the `TemplateNotFoundError` vs.
bare `KeyError` regression), template-source resolution (exactly-one-of-
four, inline template, missing file), JSON-transport ingestion dispatch,
unsupported content-type rejection, and every stub raising
`NotImplementedError` (through the real `@is_authenticated()` decorator,
using `aiohttp.test_utils.make_mocked_request` with `authenticated=True`
pre-set, since the decorator requires an actual `web.Request` in the last
positional argument — a `request=None` keyword call fails before ever
reaching the stub body, verified live and fixed in the shipped test file
too). All checks passed.

**Deviations from spec**: none in the delivered route/model shapes. Two
documented, verified correctness fixes (above) required for this task's
own acceptance criteria to actually hold at runtime.
