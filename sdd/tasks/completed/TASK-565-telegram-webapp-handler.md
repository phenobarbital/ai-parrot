# TASK-565: WebApp HTML Handler & Template

**Feature**: FEAT-081 parrot-formdesigner-renderer-telegram
**Spec**: `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-562, TASK-563
**Assigned-to**: unassigned

---

## Context

Serves the form as an HTML page at `/forms/{id}/telegram` with the Telegram WebApp
JS SDK embedded. Also implements the REST fallback endpoint for payloads exceeding
the 4 KB `sendData()` limit. Implements Spec Module 4.

---

## Scope

- Create Jinja2 template `telegram_webapp.html.j2` that:
  - Includes `<script src="https://telegram.org/js/telegram-web-app.js"></script>`.
  - Wraps the HTML5Renderer form output.
  - On form submit: serializes data as JSON, checks payload size.
  - If <=4 KB: calls `Telegram.WebApp.sendData(json)`.
  - If >4 KB: POSTs to `/api/v1/forms/{form_id}/telegram-submit` REST fallback.
  - Applies Telegram WebApp theme colors (`var(--tg-theme-bg-color)`, etc.).
  - Mobile-friendly viewport and styling.
- Create `handlers/telegram.py` with `TelegramWebAppHandler`:
  - `GET /forms/{form_id}/telegram` — serves the WebApp HTML page.
  - `POST /api/v1/forms/{form_id}/telegram-submit` — REST fallback endpoint that
    validates submission via `FormValidator` and returns JSON result.
- Add `telegram_webapp_page()` helper to `handlers/templates.py`.
- Write tests for the handler endpoints.

**NOT in scope**: aiogram Router/FSM (TASK-564), route registration (TASK-566).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/templates/telegram_webapp.html.j2` | CREATE | Jinja2 template with Telegram JS SDK |
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/telegram.py` | CREATE | aiohttp handler for WebApp serving |
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/templates.py` | MODIFY | Add telegram_webapp_page() |
| `packages/parrot-formdesigner/tests/unit/test_telegram_webapp.py` | CREATE | Handler tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.formdesigner.renderers.html5 import HTML5Renderer  # renderers/html5.py:73
from parrot.formdesigner.core.schema import FormSchema, RenderedForm  # core/schema.py
from parrot.formdesigner.core.style import StyleSchema  # core/style.py
from parrot.formdesigner.services.registry import FormRegistry  # services/registry.py
from parrot.formdesigner.services.validators import FormValidator, ValidationResult  # services/validators.py:66,52
from parrot.formdesigner.handlers.templates import page_shell, CSS  # handlers/templates.py
from aiohttp import web
import jinja2
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/renderers/html5.py:73
class HTML5Renderer(AbstractFormRenderer):
    def __init__(self, template_dir: str | Path | None = None) -> None:  # line 92
    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm:  # line 108

# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:20
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    api_key: str | None = None,
    prefix: str = "",
) -> None:

# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/templates.py:104
def page_shell(title: str, body: str, locale: str = "en", nav: bool = True) -> str:
```

### Does NOT Exist
- ~~`parrot.formdesigner.handlers.telegram`~~ — does not exist yet; this task creates it
- ~~`telegram_webapp_page()`~~ — does not exist in templates.py yet; this task adds it
- ~~`HTML5Renderer.render_for_telegram()`~~ — does not exist; use standard `render()`
- ~~`setup_form_routes()` telegram parameter~~ — does not accept telegram config; route will be added in TASK-566

---

## Implementation Notes

### Pattern to Follow
```python
# Follow same pattern as FormPageHandler in handlers/forms.py:
class TelegramWebAppHandler:
    def __init__(self, registry: FormRegistry, renderer: HTML5Renderer | None = None):
        self.registry = registry
        self.renderer = renderer or HTML5Renderer()
        self.validator = FormValidator()
        self.logger = logging.getLogger(__name__)

    async def serve_webapp(self, request: web.Request) -> web.Response:
        """GET /forms/{form_id}/telegram"""
        form_id = request.match_info["form_id"]
        form = await self.registry.get(form_id)
        if form is None:
            return web.Response(text="Form not found", status=404)
        rendered = await self.renderer.render(form)
        # Wrap in telegram_webapp_page template
        ...
```

### Key Constraints
- The Jinja2 template must use `autoescape=True` and `| safe` only for trusted
  `HTML5Renderer` output.
- `telegram-web-app.js` must be loaded BEFORE any custom JS.
- The form submit interceptor must prevent default form submission and use
  `Telegram.WebApp.sendData()` instead.
- REST fallback response format: `{"is_valid": bool, "errors": dict}` — same as
  the existing `/api/v1/forms/{id}/validate` endpoint.
- WebApp page should NOT include the nav bar (pass `nav=False` to page shell) or
  use a standalone template without the regular site chrome.
- Use `Telegram.WebApp.themeParams` for adaptive theming.

---

## Acceptance Criteria

- [ ] `GET /forms/{form_id}/telegram` serves HTML with `telegram-web-app.js` embedded
- [ ] HTML includes the rendered form from `HTML5Renderer`
- [ ] Form submit JS checks payload size and uses `sendData()` for <=4 KB
- [ ] Form submit JS falls back to REST POST for >4 KB payloads
- [ ] `POST /api/v1/forms/{form_id}/telegram-submit` validates and returns JSON
- [ ] 404 returned for unknown form_id
- [ ] Template applies Telegram theme CSS variables
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_telegram_webapp.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_telegram_webapp.py
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from parrot.formdesigner.handlers.telegram import TelegramWebAppHandler
from parrot.formdesigner.services.registry import FormRegistry
from parrot.formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot.formdesigner.core.types import FieldType


@pytest.fixture
def sample_form():
    return FormSchema(
        form_id="test-tg",
        title="Telegram Test",
        sections=[FormSection(section_id="s1", fields=[
            FormField(field_id="name", field_type=FieldType.TEXT, label="Name"),
        ])],
    )


class TestTelegramWebAppHandler:
    @pytest.mark.asyncio
    async def test_serve_webapp_contains_sdk(self, aiohttp_client, sample_form):
        """GET /forms/{id}/telegram includes telegram-web-app.js."""
        # Setup app with handler and registry containing sample_form
        # Assert response contains 'telegram-web-app.js'

    @pytest.mark.asyncio
    async def test_serve_webapp_404(self, aiohttp_client):
        """GET /forms/nonexistent/telegram returns 404."""

    @pytest.mark.asyncio
    async def test_rest_fallback_validates(self, aiohttp_client, sample_form):
        """POST /api/v1/forms/{id}/telegram-submit validates data."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
2. **Check dependencies** — verify TASK-562 and TASK-563 are completed
3. **Verify the Codebase Contract** — confirm all imports
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-565-telegram-webapp-handler.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
