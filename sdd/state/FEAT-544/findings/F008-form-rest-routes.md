---
id: F008
query_id: Q008
type: grep
intent: Routes for render/validate/submit
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F008 — Form REST routes (routes.py)

## Summary

Render, validate and submit are all mounted as public-form globs: `GET {tp}/forms/{form_uid}/render/{format}`, `POST {tp}/forms/{form_uid}/validate`, `POST {tp}/forms/{form_uid}/data` (submit). Partial saves at `{tp}/forms/{form_uid}/partial`, field uploads at `.../fields/{field_uid}/upload|file-upload`, lifecycle bridge at `.../events/{event_name}`. `tp` = `/api/v1/{tenant}` prefix.

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
  lines: 386-400
  excerpt: |
    app.router.add_get(f"{tp}/forms/{{form_uid}}/render/{{format}}", _wrap_auth(render_module.handle_render, tenant="public"))
    app.router.add_post(f"{tp}/forms/{{form_uid}}/validate", _wrap_auth(handler.validate, tenant="public"))
    app.router.add_post(f"{tp}/forms/{{form_uid}}/data", _wrap_auth(handler.submit_data, tenant="public"))
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
  lines: 414-440
