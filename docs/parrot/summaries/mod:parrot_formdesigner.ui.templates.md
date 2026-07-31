---
type: Wiki Summary
title: parrot_formdesigner.ui.templates
id: mod:parrot_formdesigner.ui.templates
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTML page templates and CSS for parrot-formdesigner HTTP handlers.
relates_to:
- concept: func:parrot_formdesigner.ui.templates.error_page
  rel: defines
- concept: func:parrot_formdesigner.ui.templates.form_page
  rel: defines
- concept: func:parrot_formdesigner.ui.templates.gallery_page
  rel: defines
- concept: func:parrot_formdesigner.ui.templates.index_page
  rel: defines
- concept: func:parrot_formdesigner.ui.templates.page_shell
  rel: defines
- concept: func:parrot_formdesigner.ui.templates.schema_page
  rel: defines
---

# `parrot_formdesigner.ui.templates`

HTML page templates and CSS for parrot-formdesigner HTTP handlers.

All template builders accept an optional ``prefix`` argument (default
``""``). When the form-designer routes are mounted behind a URL prefix via
``setup_form_routes(app, prefix="/form")``, callers resolve the prefix
with ``request.app.get("_form_prefix", "")`` and pass it through so that
every rendered link and JS ``fetch()`` target matches the real route.

Extracted from examples/forms/form_server.py.

## Functions

- `def page_shell(title: str, body: str, locale: str='en', nav: bool=True, prefix: str='') -> str` — Wrap body HTML in a full page shell.
- `def index_page(prefix: str='') -> str` — Return the HTML body for the index page (prompt builder + DB loader).
- `def gallery_page(form_items_html: str) -> str` — Return the HTML body for the gallery page.
- `def form_page(form_fragment: str) -> str` — Return the HTML body wrapping a rendered form fragment.
- `def schema_page(form_id: str, title: str, schema_json: str, style_json: str, prefix: str='') -> str` — Return the HTML body for the JSON Schema view page.
- `def error_page(message: str, prefix: str='') -> str` — Return an error page body.
