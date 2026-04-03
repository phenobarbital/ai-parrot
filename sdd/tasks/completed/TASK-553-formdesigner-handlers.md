# TASK-553: HTTP Handlers & REST API

**Feature**: formdesigner-package
**Feature ID**: FEAT-079
**Spec**: `sdd/specs/formdesigner-package.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-548, TASK-550, TASK-551, TASK-552
**Assigned-to**: unassigned

---

## Context

Implements Module 6 of FEAT-079. Creates production-quality aiohttp HTTP handlers
and REST API extracted from `examples/forms/form_server.py`, plus new endpoints for
JSON Schema and style schema serving.

This is the most complex task. The example `form_server.py` (~500 lines) contains
embedded CSS, HTML, handler logic that must be refactored into clean, reusable handler
classes in `parrot/formdesigner/handlers/`.

---

## Scope

### handlers/templates.py
Extract CSS and HTML page shell from `examples/forms/form_server.py` into a templates
module with constants/functions:
- `CSS` — the full CSS string
- `page_shell(title, body)` — returns complete HTML page
- `index_page(forms)` — landing page with prompt form and DB form loader
- `gallery_page(forms)` — lists all registered forms
- `form_page(form_schema, html_form)` — render form HTML5 page
- `error_page(message)` — generic error page

### handlers/forms.py — `FormPageHandler`
aiohttp view class serving HTML pages:
- `GET /` → index page (prompt builder + DB form loader)
- `GET /gallery` → gallery of all registered forms
- `GET /forms/{form_id}` → render HTML5 form
- `POST /forms/{form_id}` → validate submission, return result page

### handlers/api.py — `FormAPIHandler`
aiohttp view class serving JSON REST API:
- `POST /api/forms` — create form from NL prompt (uses `CreateFormTool`)
- `GET /api/forms` — list registered forms
- `GET /api/forms/{form_id}` — get form schema (full `FormSchema` as JSON)
- `GET /api/forms/{form_id}/schema` — get JSON Schema (structural, via `JSONSchemaRenderer`)
- `GET /api/forms/{form_id}/style` — get style schema
- `GET /api/forms/{form_id}/html` — render HTML5 form (returns HTML string)
- `POST /api/forms/{form_id}/validate` — validate submission data
- `POST /api/forms/from-db` — load form from database via `DatabaseFormTool`

### handlers/routes.py — `setup_form_routes()`
```python
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client=None,
    prefix: str = "",
) -> None:
```
Registers all routes on the aiohttp `app`. One-liner integration for any aiohttp app.

- Create unit tests in `packages/parrot-formdesigner/tests/unit/test_handlers.py`

**NOT in scope**: `examples/forms/form_server.py` simplification (that's TASK-555).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/__init__.py` | CREATE | Exports FormPageHandler, FormAPIHandler, setup_form_routes |
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/templates.py` | CREATE | CSS + HTML page builders extracted from form_server.py |
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/forms.py` | CREATE | FormPageHandler: HTML page routes |
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py` | CREATE | FormAPIHandler: JSON REST API routes |
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py` | CREATE | setup_form_routes() helper |
| `packages/parrot-formdesigner/tests/unit/test_handlers.py` | CREATE | Unit tests using aiohttp TestClient |

---

## Implementation Notes

### Handler Class Pattern
Follow existing `parrot/handlers/` pattern. Use `web.View` or plain handler functions:
```python
import logging
from aiohttp import web
from parrot.formdesigner.services.registry import FormRegistry
from parrot.formdesigner.renderers.html5 import HTML5Renderer


class FormAPIHandler:
    def __init__(self, registry: FormRegistry, client=None):
        self.registry = registry
        self.renderer = HTML5Renderer()
        self.logger = logging.getLogger(__name__)

    async def list_forms(self, request: web.Request) -> web.Response:
        forms = self.registry.list()
        return web.json_response([f.model_dump() for f in forms])
```

### Route Registration Pattern
```python
def setup_form_routes(app, *, registry=None, client=None, prefix=""):
    if registry is None:
        registry = FormRegistry()
    api = FormAPIHandler(registry=registry, client=client)
    page = FormPageHandler(registry=registry, client=client)

    app.router.add_get(f"{prefix}/", page.index)
    app.router.add_get(f"{prefix}/gallery", page.gallery)
    app.router.add_get(f"{prefix}/forms/{{form_id}}", page.render_form)
    app.router.add_post(f"{prefix}/forms/{{form_id}}", page.submit_form)
    app.router.add_post(f"{prefix}/api/forms", api.create_form)
    app.router.add_get(f"{prefix}/api/forms", api.list_forms)
    app.router.add_get(f"{prefix}/api/forms/{{form_id}}", api.get_form)
    app.router.add_get(f"{prefix}/api/forms/{{form_id}}/schema", api.get_schema)
    app.router.add_get(f"{prefix}/api/forms/{{form_id}}/style", api.get_style)
    app.router.add_get(f"{prefix}/api/forms/{{form_id}}/html", api.get_html)
    app.router.add_post(f"{prefix}/api/forms/{{form_id}}/validate", api.validate)
    app.router.add_post(f"{prefix}/api/forms/from-db", api.load_from_db)
```

### Reading form_server.py
The CSS constant `_CSS` and HTML generation functions in `examples/forms/form_server.py`
must be moved to `handlers/templates.py`. Read the full file before implementing.

### Key Constraints
- All handler methods must be `async def`
- Use `web.json_response()` for JSON endpoints
- Use `web.Response(text=..., content_type="text/html")` for HTML endpoints
- Log all errors with `self.logger.exception()`
- Return 404 when `registry.get(form_id)` returns None
- Return 422 with validation errors dict for failed validations

---

## Acceptance Criteria

- [ ] `from parrot.formdesigner.handlers import setup_form_routes` works
- [ ] `from parrot.formdesigner.handlers import FormAPIHandler, FormPageHandler` works
- [ ] `setup_form_routes(app, registry=registry)` registers all 12 routes
- [ ] `GET /api/forms` returns JSON list
- [ ] `GET /api/forms/{id}/schema` returns JSON Schema dict
- [ ] `GET /api/forms/{id}/style` returns style schema dict
- [ ] `GET /api/forms/{id}/html` returns HTML string
- [ ] `POST /api/forms/{id}/validate` returns validation results
- [ ] `GET /forms/{id}` returns HTML page
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_handlers.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_handlers.py
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from parrot.formdesigner.core import FormSchema, FormField, FieldType
from parrot.formdesigner.services import FormRegistry
from parrot.formdesigner.handlers import setup_form_routes


@pytest.fixture
def registry() -> FormRegistry:
    r = FormRegistry()
    r.register(FormSchema(
        form_id="test",
        title="Test",
        fields=[FormField(name="name", field_type=FieldType.TEXT, label="Name")],
    ))
    return r


@pytest.fixture
def app_with_routes(registry) -> web.Application:
    app = web.Application()
    setup_form_routes(app, registry=registry)
    return app


@pytest.mark.asyncio
class TestFormAPIHandler:
    async def test_list_forms(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/forms")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, list)

    async def test_get_schema(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/forms/test/schema")
        assert resp.status == 200
        schema = await resp.json()
        assert "properties" in schema

    async def test_get_html(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/forms/test/html")
        assert resp.status == 200
        text = await resp.text()
        assert "<form" in text

    async def test_get_unknown_form_returns_404(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/forms/nonexistent")
        assert resp.status == 404

    async def test_validate_form(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.post("/api/forms/test/validate", json={"name": "John"})
        assert resp.status in (200, 422)


class TestSetupFormRoutes:
    def test_registers_routes(self, app_with_routes):
        routes = [r.resource.canonical for r in app_with_routes.router.routes()]
        assert "/api/forms" in routes or any("/api/forms" in r for r in routes)
```

---

## Agent Instructions

1. **Verify** TASK-548, TASK-550, TASK-551, TASK-552 are in `sdd/tasks/completed/`
2. **Read** `examples/forms/form_server.py` in full before implementing
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** scope above
5. **Verify** acceptance criteria
6. **Move** to `sdd/tasks/completed/`
7. **Update index** → `"done"`
8. **Commit**: `sdd: implement TASK-553 HTTP handlers for parrot-formdesigner`

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
