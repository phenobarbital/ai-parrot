---
id: F017
query_id: Q010
type: read
intent: submit_data request contract
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F017 — FormAPIHandler.submit_data — legacy JSON contract

## Summary
`submit_data` (POST `/forms/{form_uid}/data`) expects a JSON body of `{field_id: value, ...}` plus an optional reserved `visit_context` key; it validates (422), applies unknown-fields policy, persists (sink or local storage), forwards to the form's `endpoint` submit action, and returns 200 `{"submission_id", "is_valid": True, "forwarded", ...}`. Tenant membership enforced unless the form is public. Because the Adaptive Card inputs are keyed by `field_id`, a Teams `activity.value` minus `_`-prefixed control keys is already the legacy body shape.

## Citations
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  lines: 1464-1497
  symbol: `FormAPIHandler.submit_data` (docstring)
  excerpt: |
    1. Load form (404). 2. Parse JSON body (400). 3. ?merge_partials=true ... 4. Validate (422) ...
    5. Persist — EXCLUSIVELY via form.persistence sink or submission_storage ...
    6. Forward to endpoint if form has an ``endpoint`` submit action ... 8. Return composite result — always 200
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  lines: 1510-1530
  excerpt: |
    enforce_membership_unless_public(request, form, tenant)
    body = await request.json()  # 400 "Invalid JSON body"
    data, visit_context = self._extract_visit_context(form, body)
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  lines: 1003
  symbol: `FormAPIHandler.validate`
