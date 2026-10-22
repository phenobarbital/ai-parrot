# TASK-4634: HTTP surface — 409 mapping, `/availability`, route modes, tenant flag plumbing

**Feature**: FEAT-730 — FormDesigner public response controls
**Spec**: `sdd/specs/formdesigner-public-form-controls.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4630, TASK-4631, TASK-4632
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (handler + routes half) and the G8 flag plumbing (Juan,
2026-10-22: `setup_form_api(tenant_scoped_submissions: bool = False)`, FieldSync
passes True). The pipeline (TASK-4632) raises `SubmissionRejected`; REST `/data`
must answer HTTP 409 `{"error", "reason", "field_id"?}`. Clients need
`GET …/availability` to render the closed state without submitting. The
file-upload route becomes public-mode (the handler already enforces membership
for private forms after TASK-4633).

---

## Scope

- `FormAPIHandler.__init__`: kwarg `tenant_scoped_submissions: bool = False`; `_build_submission_pipeline` passes it.
- `submit_data`: `except SubmissionRejected` → 409 body.
- New `FormAPIHandler.get_availability`.
- `setup_form_api`: kwarg `tenant_scoped_submissions: bool = False` passed to `FormAPIHandler`; new `/availability` GET route (`tenant="public"`); file-upload route `tenant="public"`.
- HTTP tests.

**NOT in scope**: `on_submitted` (TASK-4635), audio WS (TASK-4636).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | ctor flag, pipeline flag, 409 arm, `get_availability` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | kwarg, availability route, file-upload public mode |
| `packages/parrot-formdesigner/tests/unit/api/test_public_form_controls_http.py` | CREATE | HTTP tests |

---

## Codebase Contract (Anti-Hallucination)

> Relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`. Verified @ `685e6176c`.

### Verified Imports
```python
# api/handlers.py already imports (module top, :32-35): from .tenant import (..., enforce_membership_unless_public, ...)
# api/handlers.py local import block inside submit_data (:1828-1833):
#   from ..services.submission_pipeline import (ImplausibleSubmission, PlausibilityRateLimited, SubmitSinkError, ValidationFailed)
# added by TASK-4632:   from ..services.submission_pipeline import SubmissionRejected
# added by TASK-4630:   from ..core.public_access import AvailabilityState, evaluate_open
```

### Existing Signatures to Use
```python
# api/handlers.py
class FormAPIHandler:                                                     # :111
    def __init__(self, registry, client=None, submission_storage=None, forwarder=None, partial_store=None,
                 org_graph_service=None, project_service=None, rbac_service=None, workday_adapter=None,
                 venue_service=None, rbac_enforcing=False, sink_factory=None) -> None   # :145-159
    #   self._sink_factory = sink_factory                                  (count 1)
    def _build_submission_pipeline(self, form=None) -> SubmissionPipeline # :263 — SubmissionPipeline(..., sink_factory=self._sink_factory, ...)
    def _get_tenant(self, request) -> str                                 # URL-declared tenant
    def _assert_form_tenant(self, form, tenant) -> None                   # :450
    async def get_form(self, request) -> web.Response                     # :974 (404 / _assert_form_tenant / enforce_membership_unless_public)
    async def submit_data(self, request) -> web.Response
    #   except SubmitSinkError as exc:                                     :1873 (count 1)
    #   return _reply(body_out, status=200)                                :1897
    # _reply(body, status=..., headers=...) — the a2ui-aware JSON reply helper used throughout submit_data

# api/routes.py
def setup_form_api(app, registry, *, ..., teams_renderer=None, llm_quota: "LLMQuota | None" = None) -> None  # :192-216
#   handler = FormAPIHandler(..., sink_factory=sink_factory,)            :350-363 (`        sink_factory=sink_factory,` count 1)
#   app["submission_pipeline"] = handler._build_submission_pipeline()     :367
#   tp = f"{bp}/{{tenant}}"
#   /data route: add_post(f"{tp}/forms/{{form_uid}}/data", _wrap_auth(handler.submit_data, tenant="public"))  :431-434
#   file-upload route: _wrap_auth(file_upload_module.handle_file_upload)  :459 (default tenant="required")
def _wrap_auth(handler, *, tenant: str = "required")                      # :84 — modes required|public|none
```
HTTP test harness to copy: `tests/formdesigner/test_http_plausibility.py` (submit_data through the real app).

### Does NOT Exist
- ~~`get_availability`, `/availability` route~~ — added here.
- ~~`tenant_scoped_submissions`~~ — added here (handler/routes) and in TASK-4632 (pipeline).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_public_form_controls_http.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler.submit_data",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler.get_form",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._build_submission_pipeline",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#setup_form_api"
  ]
}
```

---

## Implementation Notes

- `setup_form_api` is already over the complexity budget — add the kwarg and pass it; do not add branches inline.
- 409 is a controlled flow (like `FormEventAbort`): never dispatched to `onError`.
- Availability: `public_access None` → `{"accepting": true, "reason": null, "completion": null}`.
  `form_closed` via `evaluate_open`; `response_limit_reached` when `max_responses` is set and
  `self._submission_storage.count_responses(form_uid, tenant=<t>) >= max_responses`, where
  `<t>` is the URL tenant if `self._tenant_scoped_submissions` else `None` (count where the rows are written).
  No storage → treat as accepting (cannot count).

---

## Implementation Blueprint

### Steps (in order)
1. Ctor kwarg + attribute; pass through `_build_submission_pipeline` — *why*: the pipeline owns the tenant decision (TASK-4632).
2. 409 arm next to `SubmitSinkError` — *why*: AC2–AC4 over HTTP.
3. `get_availability` above `get_form` — *why*: AC5; same resolution rules as `get_form`.
4. Routes: kwarg, availability route after `/data`, file-upload `tenant="public"` — *why*: AC5, AC7.
5. HTTP tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        sink_factory: "SinkFactory | None" = None,' api/handlers.py)
# AFTER — insert below `        sink_factory: "SinkFactory | None" = None,` (verified: :159)
        tenant_scoped_submissions: bool = False,
```
```python
# occurrences: 1 (verified: grep -c '        self._sink_factory = sink_factory' api/handlers.py)
# AFTER — insert below `        self._sink_factory = sink_factory`
        # FEAT-730 G8: host opt-in to store generic submissions under the URL tenant.
        self._tenant_scoped_submissions = tenant_scoped_submissions
```
```python
# occurrences: 1 (verified: grep -c '            sink_factory=self._sink_factory,' api/handlers.py)
# AFTER — insert below `            sink_factory=self._sink_factory,` (inside _build_submission_pipeline)
            tenant_scoped_submissions=self._tenant_scoped_submissions,
```
```python
# occurrences: 1 (verified: grep -c '            ImplausibleSubmission,' api/handlers.py)
# AFTER — insert below `            ImplausibleSubmission,` (submit_data's local import block, :1829)
            SubmissionRejected,
```
```python
# occurrences: 1 (verified: grep -c '        except SubmitSinkError as exc:' api/handlers.py)
# BEFORE — insert above `        except SubmitSinkError as exc:` (verified: :1873)
        except SubmissionRejected as exc:
            # FEAT-730 — response-policy refusal; controlled flow, never routed to onError.
            body: dict[str, Any] = {"error": str(exc), "reason": exc.reason}
            if exc.field_id is not None:
                body["field_id"] = exc.field_id
            return _reply(body, status=409)
```
```python
# occurrences: 1 (verified: grep -c '    async def get_form(self, request: web.Request) -> web.Response:' api/handlers.py)
# BEFORE — insert above `    async def get_form(self, request: web.Request) -> web.Response:` (verified: :974)
    async def get_availability(self, request: web.Request) -> web.Response:
        """GET /{tenant}/forms/{form_uid}/availability — can this form take a response now? (FEAT-730)"""
        from datetime import datetime, timezone  # handlers.py has no module-level datetime import (verified)

        from ..core.public_access import AvailabilityState, evaluate_open

        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return JSONResponse({"error": f"Form '{form_uid}' not found"}, status=404)
        self._assert_form_tenant(form, tenant)
        enforce_membership_unless_public(request, form, tenant)
        cfg = form.public_access
        if cfg is None:
            return JSONResponse(AvailabilityState(accepting=True).model_dump(mode="json"))
        # FILL IN: reason = evaluate_open(cfg, now=datetime.now(timezone.utc)); if None and
        # cfg.max_responses and self._submission_storage: count_responses(form.form_uid, tenant=
        # tenant if self._tenant_scoped_submissions else None) >= max -> "response_limit_reached".
        # Return AvailabilityState(accepting=reason is None, reason=reason, completion=cfg.completion) — AC5.
        raise NotImplementedError
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    llm_quota: "LLMQuota | None" = None,' api/routes.py)
# AFTER — insert below `    llm_quota: "LLMQuota | None" = None,` (setup_form_api signature, :215-216)
    tenant_scoped_submissions: bool = False,
```
```python
# occurrences: 1 (verified: grep -c '        sink_factory=sink_factory,' api/routes.py)
# AFTER — insert below `        sink_factory=sink_factory,` (FormAPIHandler(...) construction, :362)
        tenant_scoped_submissions=tenant_scoped_submissions,
```
```python
# occurrences: 1 (verified: grep -c '        _wrap_auth(handler.submit_data, tenant="public"),' api/routes.py)
# AFTER the whole `app.router.add_post(f"{tp}/forms/{{form_uid}}/data", _wrap_auth(handler.submit_data, tenant="public"),)`
# statement (its closing `    )` follows :433) insert:
    # FEAT-730 — can this form take a response now? Auth-exempt for public forms (7th glob).
    app.router.add_get(
        f"{tp}/forms/{{form_uid}}/availability",
        _wrap_auth(handler.get_availability, tenant="public"),
    )
```
```python
# occurrences: 1 (verified: grep -c '        _wrap_auth(file_upload_module.handle_file_upload),' api/routes.py)
# REPLACE `        _wrap_auth(file_upload_module.handle_file_upload),` (verified: :459) with:
        _wrap_auth(file_upload_module.handle_file_upload, tenant="public"),  # FEAT-730: handler enforces membership unless public
```
Also document the new kwarg in `setup_form_api`'s docstring (one line: "tenant_scoped_submissions:
store generic `/data` submissions under the URL tenant; default False").

### `packages/parrot-formdesigner/tests/unit/api/test_public_form_controls_http.py` (CREATE)
```python
"""FEAT-730 — HTTP surface: 409 bodies, /availability, flag plumbing."""
# FILL IN: app built with setup_form_api(...) and a fake storage, copying the harness of
# tests/formdesigner/test_http_plausibility.py; requests through the real _wrap_auth chain.

async def test_submit_data_409_body(): ...           # each reason; field_id only for duplicate_response
async def test_availability_states(): ...            # open / closed / limit reached / no block
async def test_availability_private_form_like_get_form(): ...   # private, no membership -> same status as GET form
async def test_setup_form_api_passes_tenant_flag(): ...          # True -> app["submission_pipeline"].tenant_scoped_submissions is True; default False
async def test_file_upload_route_is_public_mode(): ...           # route resolves without a session for a public form
```

### FILL IN checklist
- [ ] `get_availability` body — AC5
- [ ] Test bodies (spec §4 Module 4 rows)

---

## Acceptance Criteria

- [ ] `/data` refusal → 409 `{error, reason, field_id?}` (AC2–AC4).
- [ ] `GET …/availability` correct for every state; private form answers like `GET …/forms/{uid}` (AC5).
- [ ] `setup_form_api(tenant_scoped_submissions=True)` reaches the pipeline; default False (AC8).
- [ ] File-upload route is public-mode (AC7 with TASK-4633).

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_public_form_controls_http.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py -q`

---

## Test Specification

Spec §4 rows `test_submit_data_409_body`, `test_availability_states` (Module 4).

---

## Agent Instructions

1. Feature worktree; TASK-4630/4631/4632 must be `done`.
2. Re-run every `grep -c`.
3. Implement; run Validation Commands; commit only the listed files.
4. `scripts/sdd/close_task.sh TASK-4634 formdesigner-public-form-controls verified`.

---

## Completion Note

*(Agent fills this in when done)*
