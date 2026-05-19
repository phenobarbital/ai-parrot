---
id: F005
query: Q005
type: read
file: packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
---

## Route Registration & Auth (202 lines)

**Auth**: All routes wrapped with `_wrap_auth()` which applies
`@is_authenticated` + `@user_session()` from navigator_auth.

**setup_form_api()** signature accepts:
- app, registry, client, submission_storage, forwarder, base_path,
  blob_storage, resolver

New partial-saves endpoints would be added here with the same
`_wrap_auth()` pattern. The `setup_form_api()` function would need
a new `partial_store` parameter (or the store could be stashed on
`app["partial_store"]` like blob_storage).

**Existing route pattern**:
- `/api/v1/forms/{form_id}/data` — submit
- `/api/v1/forms/{form_id}/validate` — validate

**Proposed new routes**:
- `POST /api/v1/forms/{form_id}/partial` — save partial answers
- `GET /api/v1/forms/{form_id}/partial` — retrieve partial answers
- `DELETE /api/v1/forms/{form_id}/partial` — clear partial answers
