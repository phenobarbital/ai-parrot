---
type: Wiki Entity
title: FormAPIHandler
id: class:parrot_formdesigner.api.handlers.FormAPIHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Serves JSON REST API endpoints for form management.
---

# FormAPIHandler

Defined in [`parrot_formdesigner.api.handlers`](../summaries/mod:parrot_formdesigner.api.handlers.md).

```python
class FormAPIHandler
```

Serves JSON REST API endpoints for form management.

All API routes are protected by navigator-auth session authentication.
The decorators are applied at route-registration time in
``api/routes.py``.

User identity context (``org_id``, ``programs``) is extracted from the
authenticated session via the :meth:`_get_org_id` and :meth:`_get_programs`
helper methods.

Args:
    registry: FormRegistry instance for storing and retrieving forms.
    client: Optional LLM client for natural language form creation.
    submission_storage: Optional storage backend for form submissions.
    forwarder: Optional submission forwarder for endpoint-bound submits.
    partial_store: Optional Redis-backed store for ephemeral partial form
        answers.  When ``None``, partial save endpoints return 503.
    org_graph_service: Optional ``OrgGraphService`` for ``GET /org/graph``.
        When ``None``, the endpoint returns 501 Not Implemented.
    project_service: Optional ``ProjectService`` for org project endpoints.
    rbac_service: Optional ``RBACService`` for policy management endpoints.
    workday_adapter: Optional ``WorkdayIdentitySyncAdapter`` for
        ``POST /org/sync/workday``.
    rbac_enforcing: When ``False`` (default), RBAC gate-keeping on existing
        form endpoints runs in **shadow mode** — it logs permission checks
        but never blocks requests. Set to ``True`` only when nav-auth
        policies are fully configured. Consistent with ``Policy.enforcing=False``.

## Methods

- `async def save_partial(self, request: web.Request) -> web.Response` — POST /api/v1/forms/{form_id}/partial — Save partial answers.
- `async def get_partial(self, request: web.Request) -> web.Response` — GET /api/v1/forms/{form_id}/partial — Retrieve cached partial answers.
- `async def delete_partial(self, request: web.Request) -> web.Response` — DELETE /api/v1/forms/{form_id}/partial — Clear cached partial answers.
- `async def list_forms(self, request: web.Request) -> web.Response` — GET /api/v1/forms — List all registered forms with rich metadata.
- `async def get_form(self, request: web.Request) -> web.Response` — GET /api/v1/forms/{form_id} — Get full FormSchema as JSON.
- `async def get_schema(self, request: web.Request) -> web.Response` — GET /api/v1/forms/{form_id}/schema — Get JSON Schema (structural).
- `async def get_style(self, request: web.Request) -> web.Response` — GET /api/v1/forms/{form_id}/style — Get style schema.
- `async def remote_event(self, request: web.Request) -> web.Response` — POST /api/v1/forms/{form_id}/events/{event_name} — Remote event bridge.
- `async def validate(self, request: web.Request) -> web.Response` — POST /api/v1/forms/{form_id}/validate — Validate form submission.
- `async def create_form(self, request: web.Request) -> web.Response` — POST /api/v1/forms — Create a form from a natural language prompt.
- `async def edit_form(self, request: web.Request) -> web.Response` — POST /api/v1/forms/{form_id}/edit — Edit a form using natural language.
- `async def clone_form(self, request: web.Request) -> web.Response` — POST /api/v1/forms/{form_id}/clone — Clone a form under a new ID.
- `async def update_form(self, request: web.Request) -> web.Response` — PUT /api/v1/forms/{form_id} — Fully replace a registered form.
- `async def patch_form(self, request: web.Request) -> web.Response` — PATCH /api/v1/forms/{form_id} — Partially update a registered form.
- `async def delete_form(self, request: web.Request) -> web.Response` — DELETE /api/v1/forms/{form_id} — Remove a registered form.
- `async def submit_data(self, request: web.Request) -> web.Response` — POST /api/v1/forms/{form_id}/data — Receive and process a form submission.
- `async def load_from_db(self, request: web.Request) -> web.Response` — POST /api/v1/forms/from-db — Load a form from database definition.
- `async def publish_form(self, request: web.Request) -> web.Response` — POST /api/v1/forms/{form_id}/publish — Publish current form as immutable snapshot.
- `async def list_fields(self, request: web.Request) -> web.Response` — GET /api/v1/fields — List all reusable fields for the current tenant.
- `async def create_field(self, request: web.Request) -> web.Response` — POST /api/v1/fields — Add a field definition to the question bank.
- `async def list_versions(self, request: web.Request) -> web.Response` — GET /api/v1/forms/{form_id}/versions — List published version history.
- `async def get_version(self, request: web.Request) -> web.Response` — GET /api/v1/forms/{form_id}/versions/{version} — Retrieve a frozen snapshot.
- `async def get_import_report(self, request: web.Request) -> web.Response` — GET /api/v1/forms/{form_id}/import-report — Latest ImportDiffReport.
- `async def get_org_graph(self, request: web.Request) -> web.Response` — GET /api/v1/org/graph — Return the org graph for the session's org.
- `async def create_project(self, request: web.Request) -> web.Response` — POST /api/v1/org/projects — Create a fieldsync project.
- `async def map_project_workday(self, request: web.Request) -> web.Response` — POST /api/v1/org/cost-centers/{project_id}/workday-map
- `async def assign_user_role(self, request: web.Request) -> web.Response` — POST /api/v1/org/users/{user_id}/assign — Assign a role to a user.
- `async def sync_workday_identities(self, request: web.Request) -> web.Response` — POST /api/v1/org/sync/workday — Trigger Workday identity sync (stub).
- `async def list_sites(self, request: web.Request) -> web.Response` — GET /api/v1/org/stores/{store_id}/sites — List sites under a store.
- `async def create_site(self, request: web.Request) -> web.Response` — POST /api/v1/org/stores/{store_id}/sites — Create a site.
- `async def list_locations(self, request: web.Request) -> web.Response` — GET /api/v1/org/sites/{site_id}/locations — List locations in a site.
- `async def create_location(self, request: web.Request) -> web.Response` — POST /api/v1/org/sites/{site_id}/locations — Create a location.
- `async def get_location(self, request: web.Request) -> web.Response` — GET /api/v1/org/locations/{location_id} — Fetch one location.
