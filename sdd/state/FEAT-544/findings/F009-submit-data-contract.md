---
id: F009
query_id: Q009
type: read
intent: submit_data handler contract
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F009 — submit_data: request/response contract

## Summary

`POST .../data` accepts a JSON body of `{field_id: value}` answers (optional `visit_context` split off), supports `?merge_partials=true`, validates (422 `{is_valid:false, errors:{field_id:[...]}}`, `__unknown__` key for reject policy), runs lifecycle hooks, persists exclusively via sink or submission_storage, forwards when `form.submit.action_type==endpoint`, returns composite 200 JSON. `validate` returns `{is_valid, errors}` with 200/422. Wire contract is field_id-keyed everywhere.

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  lines: 1464-1500
  symbol: `FormHandler.submit_data`
  excerpt: |
    POST /api/v1/forms/{form_uid}/data — Receive and process a form submission.
    4. Validate submission data (422 if invalid).
    6. Forward to endpoint if form has an ``endpoint`` submit action
    8. Return composite result — always 200, even when forwarding fails.
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  lines: 1610-1615
  excerpt: |
    return JSONResponse({"is_valid": False, "errors": result.errors}, status=422)
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  lines: 1003-1040
  symbol: `FormHandler.validate`
  excerpt: |
    return JSONResponse({"is_valid": is_valid, "errors": errors}, status=200 if is_valid else 422)
