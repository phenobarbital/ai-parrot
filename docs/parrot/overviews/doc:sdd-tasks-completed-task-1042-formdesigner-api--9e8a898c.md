---
type: Wiki Overview
title: 'TASK-1042: Build `parrot_formdesigner.api` package — REST surface with hard
  navigator-auth'
id: doc:sdd-tasks-completed-task-1042-formdesigner-api-package-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This is the largest Wave 1 task: it migrates the entire JSON REST'
relates_to:
- concept: mod:parrot
  rel: mentions
---

# TASK-1042: Build `parrot_formdesigner.api` package — REST surface with hard navigator-auth

**Feature**: FEAT-152 — parrot-formdesigner Structural Refactor
**Spec**: `sdd/specs/formdesigner-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1041
**Assigned-to**: unassigned

---

## Context

This is the largest Wave 1 task: it migrates the entire JSON REST
surface of `parrot-formdesigner` out of `handlers/` and into a new
`api/` sub-package. It also introduces the **render dispatcher**
(path-param `/render/{format}` route) and wires the form-controls
registry from TASK-1041 into the `GET /api/v1/form-controls` endpoint.

It also makes `navigator-auth` a HARD dependency: the
`try/except ImportError` block at `handlers/routes.py:31-35` is gone;
`is_authenticated` and `user_session` are imported unconditionally at
module top.

The old `handlers/api.py` and the REST half of `handlers/routes.py` are
COPIED into the new locations and adapted; the deletion of the old
`handlers/` directory happens in TASK-1044 after `ui/` is also in place.

Spec sections: §1 Goals (render dispatcher, hard auth dep); §2
Architectural Design (Component Diagram, render dispatcher behaviour);
§2 New Public Interfaces (`setup_form_api`, `register_renderer`,
`get_renderer`, `supported_formats`); §3 Module 2; §6 Codebase Contract
(every entry under "Existing Class Signatures" and "Verified Imports").

---

## Scope

Create the following under
`packages/parrot-formdesigner/src/parrot_formdesigner/api/`:

1. **`__init__.py`** — exports `setup_form_api`. Imports
   `parrot_formdesigner.controls.builtin` for its registration
   side-effect (so the controls registry is seeded before any request).
2. **`_utils.py`** — verbatim copies of `_deep_merge`, `_loc_to_str`,
   `_bump_version` from `handlers/api.py:36-103`. No semantic change.
3. **`handlers.py`** — `FormAPIHandler` migrated from
   `handlers/api.py:108-679`. **Remove** the `get_html(request)` method
   (line 331); the dispatcher replaces it. Keep all other methods
   (`list_forms`, `get_form`, `get_schema`, `get_style`, `validate`,
   `create_form`, `update_form` (PUT), `patch_form` (RFC 7396 PATCH),
   `submit_data`, `load_from_db`). Update internal helper references
   to `from ._utils import _deep_merge, _loc_to_str, _bump_version`.
4. **`render.py`** — render dispatcher:
   - Module-level `_RENDERERS: dict[str, AbstractFormRenderer]` seeded
     with `{"html": HTML5Renderer(), "adaptive": AdaptiveCardRenderer()}`.
     Constructor args mirror what `handlers/api.py` currently does.
   - `register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None`.
   - `get_renderer(format_key: str) -> AbstractFormRenderer | None`.
   - `supported_formats() -> list[str]` (sorted, stable).
   - `async def handle_render(request)` aiohttp handler:
     - Extracts `form_id` and `format` from match_info.
     - Looks up renderer; on miss returns
       `web.json_response({"supported": supported_formats()}, status=415)`.
     - Loads form from `request.app["form_registry"]` (set by
       `setup_form_api`).
     - Calls `await renderer.render(form, ...)` — pass through `locale`,
       `prefilled`, `errors` from query/body if applicable (mirror the
       current `get_html` arg-handling at `handlers/api.py:331-370`).
     - Returns `web.Response(body=rendered.content,
       content_type=rendered.content_type)`.
5. **`controls.py`** — `async def handle_form_controls(request)`
   returning `web.json_response({"controls": [c.model_dump() for c in
   get_controls()]})`.
6. **`operations.py`** — Wave 1 STUB ONLY. `async def
   handle_operations(request)` returns `web.json_response({"detail":
   "not implemented"}, status=501)`. TASK-1048 replaces the body with
   the real implementation.
7. **`routes.py`** —
   ```python
   from navigator_auth.decorators import is_authenticated, user_session
   ```
   (HARD import — no `try/except`). Define
   `setup_form_api(app, registry, *, client=None, submission_storage=None,
   forwarder=None, base_path="/api/v1")` that mounts the route table
   below; every route is decorated with `is_authenticated` (Telegram
   webhook routes, if any, do not belong here — they go in `ui/`).

   Route table:
   | Method | Path | Handler |
   |---|---|---|
   | GET | `{base_path}/forms` | `FormAPIHandler.list_forms` |
   | POST | `{base_path}/forms` | `FormAPIHandler.create_form` |
   | GET | `{base_path}/forms/{form_id}` | `FormAPIHandler.get_form` |
   | PUT | `{base_path}/forms/{form_id}` | `FormAPIHandler.update_form` |
   | PATCH | `{base_path}/forms/{form_id}` | `FormAPIHandler.patch_form` |
   | GET | `{base_path}/forms/{form_id}/schema` | `FormAPIHandler.get_schema` |
   | GET | `{base_path}/forms/{form_id}/style` | `FormAPIHandler.get_style` |
   | GET | `{base_path}/forms/{form_id}/render/{format}` | `render.handle_render` |
   | POST | `{base_path}/forms/{form_id}/validate` | `FormAPIHandler.validate` |
   | POST | `{base_path}/forms/{form_id}/data` | `FormAPIHandler.submit_data` |
   | POST | `{base_path}/forms/{form_id}/load_from_db` | `FormAPIHandler.load_from_db` |
   | GET | `{base_path}/form-controls` | `controls.handle_form_controls` |
   | PATCH | `{base_path}/forms/{form_id}/operations` | `operations.handle_operations` |

   `setup_form_api` must also store the registry on
   `app["form_registry"] = registry` so the dispatcher can read it.

8. **Tests** under `packages/parrot-formdesigner/tests/unit/api/`:
   - `test_render_dispatcher.py` — register/get/supported, 415 on
     unknown format, html and adaptive happy paths.
   - `test_setup_form_api.py` — every documented route exists,
     `app["form_registry"]` is set, `is_authenticated` is applied.
   - `test_form_controls_endpoint.py` — endpoint payload shape after
     `controls.builtin` is imported (1 entry per `FieldType`).
   - `test_operations_stub.py` — Wave 1 returns 501.
   - `test_no_navigator_auth_fails_at_import.py` — using
     `monkeypatch.setitem(sys.modules, 'navigator_auth.decorators',
     None)` and `importlib.reload`, importing `api.routes` raises
     `ImportError`.

**NOT in scope:**
- Deleting `handlers/` (that's TASK-1044).
- Empty `__init__.py` rewrite (that's TASK-1044).
- Building `ui/` (that's TASK-1043).
- Building `xforms.py` / `pdf.py` renderers (Wave 2).
- Implementing the operations PATCH body (TASK-1048).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/__init__.py` | CREATE | Re-exports + side-effect import |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py` | CREATE | Migrated helpers |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | CREATE | FormAPIHandler (no get_html) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | CREATE | Dispatcher + register_renderer |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/controls.py` | CREATE | /form-controls handler |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py` | CREATE | 501 stub |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | CREATE | setup_form_api + hard nav-auth import |
| `packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py` | CREATE | |
| `packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py` | CREATE | |
| `packages/parrot-formdesigner/tests/unit/api/test_form_controls_endpoint.py` | CREATE | |
| `packages/parrot-formdesigner/tests/unit/api/test_operations_stub.py` | CREATE | |
| `packages/parrot-formdesigner/tests/unit/api/test_no_navigator_auth_fails_at_import.py` | CREATE | |

(`handlers/api.py` and `handlers/routes.py` are NOT modified or deleted
in this task. TASK-1044 removes them.)

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (use VERBATIM)

```python
# Source classes (read-only — re-used unchanged)
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField, RenderedForm
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:21,68,108,140
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.style import StyleSchema
from parrot_formdesigner.renderers.base import AbstractFormRenderer
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:14
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer
from parrot_formdesigner.services.registry import FormRegistry, FormStorage
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:105
from parrot_formdesigner.services.validators import FormValidator
from parrot_formdesigner.controls.registry import get_controls
# from TASK-1041

# HARD nav-auth import (replaces handlers/routes.py:31-35 try/except)
from navigator_auth.decorators import is_authenticated, user_session

# aiohttp
from aiohttp import web
```

### Existing Code to Migrate

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/handlers/api.py:36
def _deep_merge(base: dict, patch: dict) -> dict: ...  # RFC 7396 — copy verbatim to api/_utils.py
def _loc_to_str(value: object) -> str | None: ...      # line 62 — copy verbatim
def _bump_version(version: str) -> str: ...            # line 86 — copy verbatim

# packages/parrot-formdesigner/src/parrot_formdesigner/handlers/api.py:109
class FormAPIHandler:
    def __init__(self, registry: FormRegistry, client=None,
                 submission_storage=None, forwarder=None) -> None: ...   # line 125
    async def list_forms(self, request) -> web.Response: ...              # line 224
    async def get_form(self, request) -> web.Response: ...                # line 284
    async def get_schema(self, request) -> web.Response: ...              # line 299
    async def get_style(self, request) -> web.Response: ...               # line 315
    async def get_html(self, request) -> web.Response: ...                # line 331  → DELETE in this task
    async def validate(self, request) -> web.Response: ...                # line 347
    async def create_form(self, request) -> web.Response: ...             # line 372
    async def update_form(self, request) -> web.Response: ...             # line 421
    async def patch_form(self, request) -> web.Response: ...              # line 468  (RFC 7396 — keep alongside /operations per Q2)
    async def submit_data(self, request) -> web.Response: ...             # line 519
    async def load_from_db(self, request) -> web.Response: ...            # line 610

# packages/parrot-formdesigner/src/parrot_formdesigner/handlers/routes.py:31-35
try:
    from navigator_auth.decorators import is_authenticated, user_session
    _AUTH_AVAILABLE = True
except ImportError:
    _AUTH_AVAILABLE = False
# → REMOVED. api/routes.py imports unconditionally at module top.

# packages/parrot-formdesigner/src/parrot_formdesigner/handlers/routes.py:82
def setup_form_routes(...) -> None: ...
# → REPLACED by api/routes.setup_form_api + ui/routes.setup_form_ui.
```

### `AbstractFormRenderer.render()` signature (used by dispatcher)

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:14
class AbstractFormRenderer(ABC):
    @abstractmethod
    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm: ...                            # lines 25-46
```

### `RenderedForm` shape

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:140
class RenderedForm(BaseModel):
    content: Any                     # bytes or str — passed straight to web.Response.body
    content_type: str
    style_output: Any | None = None
    metadata: dict[str, Any] | None = None
```

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractFormRenderer.format_name`~~ — renderers do NOT self-identify.
  Dispatcher keeps its own name → renderer dict.
- ~~`FormAPIHandler.render_dispatch()`~~ — does not exist; the
  dispatcher is a free function in `api/render.py`.
- ~~`navigator_auth.NoAuth` import name~~ — that's a runtime backend
  configured by the host app, NOT a name `parrot-formdesigner` imports.
- ~~`web.RouteTableDef` decorators in current routes.py~~ — current
  pattern is imperative `app.router.add_route(...)`. Match the existing
  style in `handlers/routes.py`.
- ~~`request.app["registry"]`~~ — set the key explicitly to
  `"form_registry"` (per spec) to avoid clashing with consumer apps.
- ~~A `delete_form` method on `FormAPIHandler`~~ — does not exist
  today; do not add one in this task (out of scope).

---

## Implementation Notes

### Pattern to Follow

- Migration shape: open `handlers/api.py` and `handlers/routes.py`,
  copy the relevant blocks into the new files. Update only:
  - Imports (point to `parrot_formdesigner.api._utils` for helpers).
  - `get_html` removal.
  - Hard `navigator_auth` import in `routes.py`.
- Render dispatcher: copy the body of `FormAPIHandler.get_html`
  (`handlers/api.py:331-370`) into `api/render.py:handle_render`,
  generalising it for any registered format. Pass through the form,
  style, locale, prefilled, errors arguments to `renderer.render(...)`.

### Key Constraints

- Async throughout — every aiohttp handler is `async def`.
- Logger: `logger = logging.getLogger(__name__)` at module top in
  `routes.py`, `render.py`, `controls.py`, `operations.py`.
- The hard `navigator_auth` import in `routes.py` MUST be at the
  module top — not inside `setup_form_api` — so import-time failure
  is loud (test
  `test_no_navigator_auth_fails_at_import.py` verifies this).
- `api/__init__.py` does `import parrot_formdesigner.controls.builtin`
  so the registry is seeded before consumers call
  `setup_form_api(app, registry)`. Do NOT do this in `routes.py` —
  keep it in `__init__.py` so `from parrot_formdesigner.api import
  setup_form_api` triggers the seed.

### `setup_form_api` skeleton

```python
def setup_form_api(
    app: web.Application,
    registry: FormRegistry,
    *,
    client=None,
    submission_storage=None,
    forwarder=None,
    base_path: str = "/api/v1",
) -> None:
    app["form_registry"] = registry
    handler = FormAPIHandler(
        registry=registry, client=client,
        submission_storage=submission_storage, forwarder=forwarder,
    )
    app.router.add_get(f"{base_path}/forms",
                       is_authenticated()(handler.list_forms))
    # ... full route table
    app.router.add_get(
        f"{base_path}/forms/{{form_id}}/render/{{format}}",
        is_authenticated()(render.handle_render),
    )
    app.router.add_get(f"{base_path}/form-controls",
                       is_authenticated()(controls.handle_form_controls))
    app.router.add_patch(
        f"{base_path}/forms/{{form_id}}/operations",
        is_authenticated()(operations.handle_operations),
    )
```

(Note: the exact decorator-application style — `is_authenticated()(...)`
vs `is_authenticated(handler)` — must match the navigator-auth API
that `handlers/routes.py:_wrap_auth` currently uses; copy that pattern.)

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.api import setup_form_api` succeeds.
- [ ] `parrot_formdesigner.api._utils` exposes the three helpers with
      identical bodies to `handlers/api.py:36-103`.
- [ ] `parrot_formdesigner.api.handlers.FormAPIHandler` has every
      method listed in the §Codebase Contract EXCEPT `get_html`.
- [ ] `parrot_formdesigner.api.render.register_renderer(...)`,
      `get_renderer(...)`, `supported_formats()`, `handle_render(...)`
      exist.
- [ ] On import, `_RENDERERS` contains `"html"` and `"adaptive"`.
- [ ] `GET /api/v1/forms/{id}/render/<unknown>` returns 415 with
      `{"supported": [...]}`.
- [ ] `GET /api/v1/forms/{id}/render/html` delegates to
      `HTML5Renderer.render()` and returns the rendered content with
      its `content_type`.
- [ ] `GET /api/v1/form-controls` returns `{"controls": [...]}` with
      one entry per `FieldType` value (because `api/__init__.py`
      imported `controls.builtin`).
- [ ] `PATCH /api/v1/forms/{id}/operations` returns 501 in Wave 1.
- [ ] Stubbing out `navigator_auth.decorators` causes
      `import parrot_formdesigner.api.routes` to raise `ImportError`.
- [ ] Every route in `setup_form_api`'s table is registered exactly
      once and is wrapped with `is_authenticated`.
- [ ] `app["form_registry"] is registry` after `setup_form_api(app,
      registry)`.
- [ ] All unit tests in `tests/unit/api/` pass.
- [ ] No linting errors: `ruff check
      packages/parrot-formdesigner/src/parrot_formdesigner/api/`.

---

## Test Specification

(Skeletons — flesh out with the codebase's existing aiohttp test
patterns; see `tests/integration/handlers/` for current style.)

```python
# tests/unit/api/test_render_dispatcher.py
import pytest
from parrot_formdesigner.api.render import (
    register_renderer, get_renderer, supported_formats, _RENDERERS,
)
from parrot_formdesigner.renderers.base import AbstractFormRenderer

def test_html_and_adaptive_seeded():
    assert "html" in _RENDERERS
    assert "adaptive" in _RENDERERS

def test_register_renderer_overwrites():
    class _R(AbstractFormRenderer):
        async def render(self, form, style=None, **kw): ...
    r = _R()
    register_renderer("xml", r)
    assert get_renderer("xml") is r

def test_supported_formats_sorted():
    assert supported_formats() == sorted(supported_formats())


# tests/unit/api/test_setup_form_api.py
import pytest
from aiohttp import web
from parrot_formdesigner.api import setup_form_api
from parrot_formdesigner.services.registry import FormRegistry

async def test_setup_mounts_routes(aiohttp_client):
    app = web.Application()
    registry = FormRegistry()
    setup_form_api(app, registry)
    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/api/v1/forms" in paths
    assert "/api/v1/forms/{form_id}/render/{format}" in paths
    assert "/api/v1/form-controls" in paths
    assert "/api/v1/forms/{form_id}/operations" in paths
    assert app["form_registry"] is registry


# tests/unit/api/test_no_navigator_auth_fails_at_import.py
import sys, importlib, pytest

def test_missing_navigator_auth_breaks_routes_import(monkeypatch):
    monkeypatch.setitem(sys.modules, "navigator_auth", None)
    monkeypatch.setitem(sys.modules, "navigator_auth.decorators", None)
    sys.modules.pop("parrot_formdesigner.api.routes", None)
    with pytest.raises(ImportError):
        importlib.import_module("parrot_formdesigner.api.routes")
```

---

## Agent Instructions

When you pick up this task:

1. Read the full spec, especially §2 Architectural Design and §6
   Codebase Contract.
2. Verify TASK-1041 (controls registry) is in `tasks/completed/`.
3. Open `handlers/api.py` and `handlers/routes.py` side-by-side with
   your new files; migrate code in chunks, running tests after each
   chunk.
4. Implement in this order: `_utils.py` → `handlers.py` → `render.py`
   → `controls.py` → `operations.py` (stub) → `routes.py` →
   `__init__.py`.
5. Move this task to `sdd/tasks/completed/`, update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-05-07
**Notes**:
- Created `parrot_formdesigner/api/` with `_utils.py` (verbatim helpers from handlers/api.py:36-103), `handlers.py` (FormAPIHandler migrated, get_html removed), `render.py` (dispatcher with `_RENDERERS` dict, `register_renderer`, `get_renderer`, `supported_formats`, `handle_render`), `controls.py` (form-controls endpoint), `operations.py` (Wave 1 501 stub), `routes.py` (HARD navigator-auth import, `setup_form_api` mounting all routes).
- All 12 unit tests pass (`tests/unit/api/`).
- **Out-of-scope fix**: restored `renderers/templates/{form,telegram_webapp}.html.j2` (force-added through .gitignore) — these were lost during the parrot.formdesigner → parrot_formdesigner namespace migration but are required for HTML5Renderer to instantiate. Without them, the existing `handlers/api.py:136 self.html_renderer = HTML5Renderer()` was already broken. pyproject.toml declares them as package-data.
- **Out-of-scope side effect**: tests in `tests/unit/test_handlers.py` that exercised `setup_form_routes` with the old conditional auth path now fail (since navigator-auth is hard-installed and the auth fallback is gone). These will be cleaned up in TASK-1044 when handlers/ is deleted.
- Naming pitfall fixed: removed `from .. import controls` from `api/__init__.py` to prevent shadowing of `api/controls.py` in relative imports from `api/routes.py`.
