---
id: F005
query_id: Q007
type: read
intent: Find form public URLs and how routes are auth-wrapped
executed_at: 2026-06-16T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F005 — formdesigner routes: blanket `_wrap_auth`, candidate public URLs

## Summary

`setup_form_api()` mounts the JSON REST surface under `base_path` (default
`/api/v1`). EVERY route is wrapped with `_wrap_auth`, which applies
`user_session()` + `is_authenticated(...)`. navigator-auth is a HARD import here
(FEAT-152). The form-relative URLs that a public form needs anonymous access to:

- `GET  {bp}/forms/{form_id}`            (get_form)        — line 206
- `GET  {bp}/forms/{form_id}/schema`     (get_schema/JSON) — line 222-224
- `GET  {bp}/forms/{form_id}/render/{format}` (rendered)   — line 230-233
- `POST {bp}/forms/{form_id}/data`       (submit results)  — line 239-241
- (maybe) `POST {bp}/forms/{form_id}/validate`             — line 236-238

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
  lines: 67-89
  symbol: `_wrap_auth`
  excerpt: |
    def _wrap_auth(handler):
        decorated = user_session()(_inner)
        decorated = is_authenticated(content_type="application/json")(decorated)
        return decorated

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
  lines: 200-241
  symbol: `setup_form_api route table`
  excerpt: |
    app.router.add_get(f"{bp}/forms/{{form_id}}", _wrap_auth(handler.get_form))
    app.router.add_get(f"{bp}/forms/{{form_id}}/schema", _wrap_auth(handler.get_schema))
    app.router.add_get(f"{bp}/forms/{{form_id}}/render/{{format}}", _wrap_auth(render_module.handle_render))
    app.router.add_post(f"{bp}/forms/{{form_id}}/data", _wrap_auth(handler.submit_data))

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
  lines: 34
  symbol: hard navigator-auth import
  excerpt: |
    from navigator_auth.decorators import is_authenticated, user_session

## Notes

`fnmatch` exclude patterns are glob, so render's `{format}` collapses to a single
pattern `/api/v1/forms/<id>/render/*`. Exact paths for the others.
