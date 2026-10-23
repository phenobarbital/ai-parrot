# TASK-4651: Authenticated, fail-closed audit read endpoint

**Feature**: FEAT-732 — FormDesigner validation audit trail
**Spec**: `sdd/specs/formdesigner-validation-audit-trail.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4646
**Assigned-to**: unassigned

---

## Context

The trace is persisted into `context`, but `api/routes.py` registers **no** GET for
submissions at all, and the trace must never ride on the submit/validate responses (spec
decision 4). This task adds the one read path: an authenticated, permission-gated GET that
returns only the audit projection — never the submitted answers. It also adds a
**fail-closed** permission gate, because the existing `_rbac_shadow_gate` allows in three
places (`api/handlers.py:2239` service missing, `:2254` resolution raising, `:2271` shadow
mode, which is the default). Implements spec §2 G, §3 Module 6 and §8 Q1/Q2 as resolved.

It depends on TASK-4646 only because both edit `api/handlers.py` (serialized by the task
graph); it needs no symbol from it. Its tests store a `FormSubmission` with a prepared
`context`, so it does not need the pipeline (TASK-4650) either.

---

## Scope

- Add the module-level constant `READ_FORM_AUDIT = "read_form_audit"` to `api/handlers.py`.
- Add `FormAPIHandler._rbac_require(request, codename, *, scope=None)` — fail-closed.
- Add `FormAPIHandler.get_submission_audit(request)`.
- Register `GET {tp}/forms/{form_uid}/data/{submission_id}/audit` with `_wrap_auth(...)` at
  its **default** `tenant="required"` — never `"public"`.
- Write tests, including a regression test that the audit URL matches none of the
  public-form exemption globs.

### Decisions this task implements (spec §8, resolved 2026-10-23 — do not re-decide)
1. **Scope floor**: `has_permission(READ_FORM_AUDIT, scope=RBACScope.CLIENT)`. Scope levels
   genuinely work (`services/rbac.py:84`, `:200-208`): an `own`/`team` grant → 403;
   `client`/`global` → allowed.
2. **Row identity is the handler's job**: `has_permission` evaluates no resource
   (`rbac.py:182`) and compiled policies hardcode `resources=["form:*"]` (`rbac.py:298`).
   The tenant comes from `_get_tenant` (already validated by `requires_tenant`); the row's
   `form_uid` must equal the path's.
3. **Order**: permission gate → storage availability → lookup. A caller without the
   permission learns nothing about which submissions exist (403 for real and fake ids alike).
4. **No ownership filtering**: `FormSubmission.user_id` is `None` on any form without a
   `metadata` block (`api/handlers.py:1841`, `services/submission_pipeline.py:346`).
5. **No policy is seeded**: operators grant `read_form_audit` through the existing
   `POST /org/users/{user_id}/assign` (`api/routes.py:552-555`). Seeding would not work
   anyway: `RBACService.resolve` projects only `user__{user_id}__*` policies (`rbac.py:496`).

### Responses
| Case | Status | Body |
|---|---|---|
| No permission / RBAC service `None` / resolution raises / grant narrower than CLIENT | 403 | aiohttp `HTTPForbidden` |
| Submission storage not configured | 503 | `{"error": "Submission storage not configured"}` |
| Row exists, `form_uid` matches | 200 | `{submission_id, form_uid, form_version, is_valid, validation, llm_validation}` |
| No row, and the form declares `persistence` (FEAT-457 sink) | 501 | `{"error": "...written to its own persistence sink; read the audit trail from that sink's context column"}` |
| No row, or `form_uid` mismatch | 404 | `{"error": "Submission not found"}` |

The 501 row exists because a form declaring `persistence` writes **exclusively** to its own
sink (`services/submission_pipeline.py:366-391`) — `get_submission` cannot see those rows,
and a bare 404 would wrongly tell an auditor the submission does not exist. The form is
looked up **only** on the miss path, so the common case costs one query.

**NOT in scope**:
- Reading audit trails out of FEAT-457 sinks — the 501 points there; it is a follow-up.
- Listing submissions, or any write endpoint.
- Changing `_rbac_shadow_gate` — it stays fail-open for the routes it already protects.
- Seeding RBAC policies.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `READ_FORM_AUDIT`, `_rbac_require`, `get_submission_audit` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Register the GET route |
| `packages/parrot-formdesigner/tests/unit/api/test_submission_audit_endpoint.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already at module level in api/handlers.py:
from aiohttp import web                                   # line 17
from navigator.responses import JSONResponse              # line 19
# RBACScope is imported LOCALLY inside the method body — the existing idiom at
# api/handlers.py:2487; the module imports only RBACService, and only under TYPE_CHECKING (line 103):
from ..services.rbac import RBACScope                     # verified: services/rbac.py:67
# tests:
from parrot_formdesigner.api.handlers import FormAPIHandler, READ_FORM_AUDIT
from parrot_formdesigner.services.public_forms import public_form_paths   # verified: services/public_forms.py:13
from parrot_formdesigner.services.rbac import PermissionRecord, RBACContext, RBACScope   # verified: rbac.py:135,162,67
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
def extract_form_uid(request: web.Request) -> _uuid.UUID: ...        # line 39 ← module-level anchor
class FormAPIHandler:
    def __init__(self, ..., submission_storage=None, ..., rbac_service=None, ..., rbac_enforcing=False): ...  # line 150+
    self.registry = registry                                         # line 161
    self._submission_storage = submission_storage                    # line 163
    self._rbac_service = rbac_service                                # line 173
    def _get_tenant(self, request: web.Request) -> str: ...          # line 397 — returns declared_tenant(request) = request.get("tenant")
    async def get_partial(self, request: web.Request) -> web.Response: ...   # line 777 — the authenticated-GET pattern to mirror (503 when its store is None)
    async def _rbac_shadow_gate(self, request: web.Request, codename: str) -> None: ...   # line 2220
        #   lines 2241-2249 — how it derives user_id and program_id=0 (copy this part verbatim)
        #   line 2252: ctx = await self._rbac_service.resolve(user_id, program_id=program_id, tenant=tenant)
    # FEAT-302 — Org Graph endpoints                                  # line 2288 ← method anchor (comment, unique)
    async def assign_user_role(self, request) -> web.Response: ...   # line 2442 — the grant path

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:
    async def get(self, form_uid: uuid.UUID, *, tenant: str | None = None) -> FormSchema | None: ...  # line 976

# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py
class FormSubmissionStorage:
    async def get_submission(self, submission_id: str, *, tenant: str | None = None) -> FormSubmission | None: ...  # line 420

# packages/parrot-formdesigner/src/parrot_formdesigner/services/rbac.py
class RBACContext(BaseModel):
    def has_permission(self, codename: str, scope: RBACScope | None = None) -> bool: ...   # line 182

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def _wrap_auth(handler: _Handler, *, tenant: str = "required") -> _Handler: ...   # line 85
#   lines 431-434 — the submit_data route; its closing `)` is line 434 ← route anchor
#     app.router.add_post(
#         f"{tp}/forms/{{form_uid}}/data",
#         _wrap_auth(handler.submit_data, tenant="public"),
#     )

# packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py
def public_form_paths(form_uid: str, tenant: str, base_path: str = "/api/v1") -> list[str]: ...   # line 13
#   returns exact paths + ONE wildcard (`/render/*`); `/data` is exact, so `/data/{id}/audit` does not match
```

### Does NOT Exist
- ~~a submission GET route~~ — `api/routes.py` registers none today; this is the first.
- ~~`FormAPIHandler.get_submission`~~ / ~~`.list_submissions`~~ — no such handler methods.
- ~~`FormAPIHandler._rbac_require`~~ — added here; only the fail-OPEN `_rbac_shadow_gate` exists.
- ~~`RBACContext.has_permission(..., resource=...)`~~ — signature is `(codename, scope=None)`;
  hence `_rbac_require(..., scope=)`, never `resource=`.
- ~~`request.match_info["tenant"]`~~ as the tenant source — use `self._get_tenant(request)`.
- ~~`FormSubmissionStorage.get_audit()`~~ — does not exist; use `get_submission` and project.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_submission_audit_endpoint.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._rbac_shadow_gate",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._get_tenant",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#extract_form_uid",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py#FormSubmissionStorage.get_submission",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/rbac.py#RBACContext.has_permission",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py#public_form_paths",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#_wrap_auth"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `READ_FORM_AUDIT` — *why*: one constant the docs (TASK-4652) and operators reference.
2. Add `_rbac_require` — *why*: fail-closed is the whole point (spec AC17); keep it a
   sibling, not a modification, of the shadow gate.
3. Add `get_submission_audit`, following the Responses table — *why*: spec AC16/AC17b.
4. Register the route — *why*: `tenant="required"` by omission keeps it non-public.
5. Test, then run the Validation Commands.

### `api/handlers.py` (MODIFY — constant)
```python
# occurrences: 1 (verified: grep -c 'def extract_form_uid(request: web.Request) -> _uuid.UUID:' api/handlers.py)
# BEFORE — insert above `def extract_form_uid(request: web.Request) -> _uuid.UUID:` (verified: api/handlers.py:39)
#: RBAC codename for the FEAT-732 audit read. Granted per user, at CLIENT scope or
#: wider, through POST /org/users/{user_id}/assign. Never seeded.
READ_FORM_AUDIT = "read_form_audit"


```

### `api/handlers.py` (MODIFY — gate + endpoint)
```python
# occurrences: 1 (verified: grep -c '    # FEAT-302 — Org Graph endpoints' api/handlers.py)
# BEFORE — insert above the `    # ----…` line that precedes `    # FEAT-302 — Org Graph endpoints` (verified: api/handlers.py:2287-2288)
    async def _rbac_require(
        self, request: web.Request, codename: str, *, scope: "RBACScope | None" = None
    ) -> None:
        """Fail-CLOSED permission gate — the audit sibling of ``_rbac_shadow_gate`` (FEAT-732).

        Raises ``web.HTTPForbidden`` when the RBAC service is unavailable, when
        resolution raises, or when ``codename`` is not held at ``scope`` or wider —
        independent of ``self.rbac_enforcing``. Deliberately NOT ``_rbac_shadow_gate``,
        which allows in all three cases (handlers.py:2239, 2254, 2271).

        Takes ``scope``, not a resource: ``RBACContext.has_permission`` accepts
        ``(codename, scope)`` only and evaluates no resource (services/rbac.py:182).
        """
        if self._rbac_service is None:
            self.logger.warning("_rbac_require: DENY codename=%s — no RBAC service configured", codename)
            raise web.HTTPForbidden(reason=f"Permission denied: {codename}")
        # FILL IN: derive user_id and tenant exactly as _rbac_shadow_gate does (handlers.py:2241-2249,
        #   program_id=0 with its H-4 comment), resolve, and call ctx.has_permission(codename, scope=scope).
        #   ANY exception from resolve → log a warning and raise HTTPForbidden (fail closed — never return).
        #   Not allowed → log a warning with user_id/codename/tenant and raise HTTPForbidden.

    async def get_submission_audit(self, request: web.Request) -> web.Response:
        """GET ``/forms/{form_uid}/data/{submission_id}/audit`` — the FEAT-732 audit projection.

        Authenticated and never public. Order is part of the contract: permission
        gate FIRST, then storage availability, then the lookup — so a caller without
        the permission learns nothing about which submission ids exist.

        Returns:
            200 ``{submission_id, form_uid, form_version, is_valid, validation, llm_validation}``
            — never the submitted answers. 403 without ``read_form_audit`` at CLIENT scope.
            503 when submission storage is not configured. 501 when the row is absent and
            the form writes to its own persistence sink. 404 otherwise.
        """
        from ..services.rbac import RBACScope  # local import — the idiom at handlers.py:2487

        await self._rbac_require(request, READ_FORM_AUDIT, scope=RBACScope.CLIENT)
        if self._submission_storage is None:
            return JSONResponse({"error": "Submission storage not configured"}, status=503)
        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        submission_id = request.match_info["submission_id"]
        row = await self._submission_storage.get_submission(submission_id, tenant=tenant)
        if row is None or row.form_uid != form_uid:
            # FILL IN: ONLY when row is None, look the form up (self.registry.get(form_uid, tenant=tenant));
            #   if it exists and declares `persistence`, return the 501 body from the Responses table.
            #   Every other miss — including a form_uid mismatch — is the 404 body.
            return JSONResponse({"error": "Submission not found"}, status=404)
        context = row.context or {}
        return JSONResponse(
            {
                "submission_id": row.submission_id,
                "form_uid": str(row.form_uid),
                "form_version": row.form_version,
                "is_valid": row.is_valid,
                "validation": context.get("validation"),
                "llm_validation": context.get("llm_validation"),
            }
        )
```
**Why**: the projection names its keys explicitly — `row.data`, `extra_data`, `ip`,
`user_agent` and every other column stay out by construction, not by an exclusion list
someone could forget to extend. `context.get(...)` returns `None` for submissions stored
before FEAT-732, which is the honest answer.

### `api/routes.py` (MODIFY)
```python
# FILL IN: disambiguate — attach below the closing `    )` of the submit_data route, i.e. the 4-line block
#     app.router.add_post(
#         f"{tp}/forms/{{form_uid}}/data",
#         _wrap_auth(handler.submit_data, tenant="public"),
#     )
#   (`_wrap_auth(handler.submit_data, tenant="public"),` occurs once — verified: api/routes.py:433). Insert:
    # FEAT-732 — audit projection of one submission. NOT a public-form glob:
    # tenant="required" (the default) plus a fail-closed permission gate.
    app.router.add_get(
        f"{tp}/forms/{{form_uid}}/data/{{submission_id}}/audit",
        _wrap_auth(handler.get_submission_audit),
    )
```

### FILL IN checklist
- [ ] `_rbac_require` — resolution and scope check, fail closed on every path; bounded by AC17.
- [ ] `get_submission_audit` — 501 vs 404 on the miss path; bounded by the Responses table.
- [ ] Route disambiguation.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] 403 when the caller holds no `read_form_audit`; when the grant is `own` or `team`; when
      `rbac_service is None`; when `resolve` raises — each at `rbac_enforcing=False` (spec AC17).
- [ ] 200 with a `client` and with a `global` grant; the body has exactly the six keys and
      no submitted answer (spec AC16).
- [ ] A caller without the permission gets 403 for an existing **and** a non-existent
      `submission_id` (spec AC17b); `get_submission` is never awaited for that caller.
- [ ] An existing `submission_id` under a different path `form_uid` → 404 (spec AC17b).
- [ ] No row + form with `persistence` → 501; no row + plain form → 404.
- [ ] Storage `None` + permission held → 503.
- [ ] A pre-FEAT-732 row (`context=None`) → 200 with `validation: null`, `llm_validation: null`.
- [ ] The audit URL matches none of `public_form_paths(...)`'s globs.
- [ ] The route is registered as GET at `{tp}/forms/{form_uid}/data/{submission_id}/audit`.
- [ ] `_rbac_shadow_gate` is unchanged; `test_api_feat302.py` still passes.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_submission_audit_endpoint.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_api_feat302.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_rbac_service.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/api/test_submission_audit_endpoint.py
import json
import uuid
from fnmatch import fnmatch
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot_formdesigner.api.handlers import READ_FORM_AUDIT, FormAPIHandler
from parrot_formdesigner.services.public_forms import public_form_paths
from parrot_formdesigner.services.rbac import PermissionRecord, RBACContext, RBACScope
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage

_UID = uuid.UUID("33333333-3333-3333-3333-333333333333")
_TENANT = "t1"


def _request(*, form_uid=_UID, submission_id="sub-1") -> MagicMock:
    """Mirror tests/formdesigner/test_http_plausibility.py:54-67 — the declared tenant is read via req.get."""
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": str(form_uid), "submission_id": submission_id}
    req.get = MagicMock(side_effect=lambda key, default=None: _TENANT if key == "tenant" else default)
    user = MagicMock(); user.id = "auditor"; user.organizations = []
    req.user = user
    req.session = {"session": {"programs": [_TENANT]}}
    return req


def _grant(scope: RBACScope) -> RBACContext:
    """An RBACContext holding read_form_audit at `scope` (see test_api_feat302.py:158-167)."""
    # FILL IN: PermissionRecord(user_id="auditor", codename=READ_FORM_AUDIT, scope=scope, program_id=0,
    #   policy_name=f"user__auditor__{READ_FORM_AUDIT}__{scope.value}__prog0", tenant=_TENANT)


def _handler(*, rbac_service=None, stored=None, form=None) -> FormAPIHandler:
    """FormAPIHandler with a mocked registry and submission storage (see test_api_feat302.py:91-112)."""
    # FILL IN: registry = MagicMock(spec=FormRegistry); registry.get = AsyncMock(return_value=form);
    #   storage = MagicMock(spec=FormSubmissionStorage); storage.get_submission = AsyncMock(return_value=stored);
    #   return FormAPIHandler(registry=registry, submission_storage=storage, rbac_service=rbac_service)


class TestGate:
    async def test_no_permission_403(self): ...
    async def test_own_scope_403(self): ...
    async def test_team_scope_403(self): ...
    async def test_no_rbac_service_403(self): ...
    async def test_resolution_raises_403(self): ...
    async def test_shadow_mode_does_not_open_it(self): ...     # rbac_enforcing=False explicitly
    async def test_gate_precedes_lookup(self): ...            # get_submission never awaited


class TestProjection:
    async def test_client_scope_200_six_keys(self): ...
    async def test_global_scope_200(self): ...
    async def test_never_returns_answers(self): ...            # stored data={"secret": "x"} absent from body
    async def test_legacy_row_has_null_trace(self): ...
    async def test_form_uid_mismatch_404(self): ...
    async def test_unknown_submission_404(self): ...
    async def test_sink_persisted_form_501(self): ...
    async def test_storage_missing_503(self): ...


def test_audit_url_is_not_a_public_form_glob():
    sid = "sub-1"
    url = f"/api/v1/{_TENANT}/forms/{_UID}/data/{sid}/audit"
    assert not any(fnmatch(url, p) for p in public_form_paths(str(_UID), _TENANT))

# FILL IN: one route-registration test — build an app with setup_form_api the way
#   tests/unit/api/test_setup_form_api.py does and assert a GET resource with the canonical
#   path "{tp}/forms/{form_uid}/data/{submission_id}/audit" exists.
```

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug formdesigner-validation-audit-trail --feature-id FEAT-732`
2. **Read the spec** — §2 G, §3 Module 6, §7 R3/R4/R4b, §8 Q1/Q2.
3. **Check dependencies** — TASK-4646 must be `done` (shared file `api/handlers.py`).
4. **Verify the Codebase Contract** — re-run every `grep -c`; TASK-4646 shifted handlers.py lines, so locate by anchor text.
5. **Update status** → `"in-progress"`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the three listed files.
9. **Close** — `scripts/sdd/close_task.sh TASK-4651 formdesigner-validation-audit-trail verified`.
10. **Completion Note** — record the 501 sink limitation as a follow-up.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: the 501 response for sink-persisted forms is an addition to the spec's response set.
