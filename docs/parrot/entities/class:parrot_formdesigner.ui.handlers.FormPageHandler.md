---
type: Wiki Entity
title: FormPageHandler
id: class:parrot_formdesigner.ui.handlers.FormPageHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Serves HTML pages for the form builder UI.
---

# FormPageHandler

Defined in [`parrot_formdesigner.ui.handlers`](../summaries/mod:parrot_formdesigner.ui.handlers.md).

```python
class FormPageHandler
```

Serves HTML pages for the form builder UI.

Args:
    registry: FormRegistry instance for looking up forms.
    renderer: HTML5Renderer for rendering form HTML.
    validator: FormValidator for validating submissions.

## Methods

- `async def index(self, request: web.Request) -> web.Response` — GET / — Landing page with prompt input and DB form loader.
- `async def gallery(self, request: web.Request) -> web.Response` — GET /gallery — List all previously generated forms.
- `async def render_form(self, request: web.Request) -> web.Response` — GET /forms/{form_id} — Render the form as an HTML page.
- `async def view_schema(self, request: web.Request) -> web.Response` — GET /forms/{form_id}/schema — Display JSON Schema as an HTML page.
- `async def submit_form(self, request: web.Request) -> web.Response` — POST /forms/{form_id} — Validate submission, show result.
